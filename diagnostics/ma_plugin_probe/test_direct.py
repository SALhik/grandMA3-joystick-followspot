"""Run the real packaged Lua with doubles only for MA's unavailable host APIs."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from followspot_core import Settings


HERE = Path(__file__).resolve().parent


class DirectPackageTests(unittest.TestCase):
    def setUp(self):
        self.lua = shutil.which('lua5.5') or shutil.which('lua')
        if not self.lua:
            self.skipTest('Local Lua unavailable; real MA checks remain manual')
        self.temp = tempfile.TemporaryDirectory(prefix="MA direct ' package ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = self.root / 'settings.json'
        self.settings.write_text(json.dumps(Settings(marker_id=9, initial_x=2, z=3,
            test_size=4, test_period=2, test_brightness=37,
            executor_page=4, executor_number=205).to_dict()))
        self.package = self.root / 'direct.xml'

    def build(self, destination=None):
        before = self.settings.read_bytes()
        result = subprocess.run([sys.executable, str(HERE / 'build_direct.py'),
            '--settings', str(self.settings), '--output', str(destination or self.package)],
            capture_output=True, text=True)
        self.assertEqual(self.settings.read_bytes(), before)
        return result

    def run_package(self, mode='normal', choice=1):
        built = self.build()
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        blocks = ET.parse(self.package).findall('./UserPlugin/ComponentLua/FileContent/Block')
        source = self.root / 'embedded.lua'
        source.write_bytes(b''.join(base64.b64decode(b.attrib['Base64']) for b in blocks))
        runner = self.root / 'run.lua'
        runner.write_text(RUNNER)
        outcome = subprocess.run([self.lua, str(runner), str(source), mode, str(choice)],
            env=dict(os.environ, FOLLOWSPOT_DIRECT_REPORTS=str(self.root / 'reports'),
                     DIRECT_TRACE=str(self.root / 'trace.tsv')),
            capture_output=True, text=True, timeout=10)
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
        trace = (self.root / 'trace.tsv').read_text().splitlines()
        reports = list((self.root / 'reports').glob('run.*/report.txt'))
        return trace, reports[0].read_text() if reports else '', outcome.stdout

    def test_direct_cycle_writes_configured_xyz_without_commands_or_faders(self):
        # Wrong channel IDs, metre conversion, endpoints, or a network fallback fail here.
        trace, report, _ = self.run_package()
        writes = [line.split('\t') for line in trace if line.startswith('XYZ\t')]
        self.assertGreater(len(writes), 150)
        self.assertEqual([int(row[1]) for row in writes[:3]], [11, 12, 13])
        self.assertEqual([float(row[2]) for row in writes[:3]], [51, 50, 51.5])
        self.assertEqual([float(row[2]) for row in writes[-3:]], [51, 50, 51.5])
        self.assertAlmostEqual(max(float(r[2]) for r in writes if r[1] == '11'), 53)
        self.assertAlmostEqual(min(float(r[2]) for r in writes if r[1] == '11'), 49)
        self.assertFalse(any(line.startswith('FADER\t') for line in trace))
        self.assertIn('reason=completed', report)
        self.assertIn('selection_preserved=true', report)
        self.assertIn('readback_matches=true', report)
        self.assertIn('onPC_version=2.5.test', report)
        self.assertIn('visible_movement=operator_check_required', report)

    def test_empty_selection_is_allowed_without_selecting_the_marker(self):
        trace, report, _ = self.run_package(mode='empty_selection')
        self.assertTrue(any(line.startswith('XYZ\t') for line in trace))
        self.assertIn('reason=completed', report)
        self.assertIn('selection_preserved=true', report)

    def test_inspection_is_read_only(self):
        trace, report, _ = self.run_package(choice=3)
        self.assertEqual(trace, [])
        self.assertIn('reason=inspected', report)
        self.assertIn('XYZ_X', report)
        self.assertIn('channel=11', report)
        self.assertIn('absolute', report)

    def test_cancel_does_not_write_or_create_a_report(self):
        trace, report, _ = self.run_package(choice=0)
        self.assertEqual(trace, [])
        self.assertEqual(report, '')

    def test_brightness_uses_the_assigned_object_on_the_configured_page(self):
        trace, report, _ = self.run_package(choice=2)
        self.assertEqual([line for line in trace if line.startswith('FADER\t')],
                         ['FADER\tFaderMaster\t37'])
        self.assertIn('reason=completed', report)
        self.assertIn('brightness_readback=37', report)

    def test_deferred_brightness_readback_allows_one_press_and_a_full_motion_cycle(self):
        # MA applies SetFader after yielding; an immediate read still returns 0.
        trace, report, _ = self.run_package(mode='fader_delayed', choice=2)
        self.assertIn('reason=completed', report)
        self.assertEqual([line for line in trace if line.startswith('FADER\t')],
                         ['FADER\tFaderMaster\t37'])
        writes = [line.split('\t') for line in trace if line.startswith('XYZ\t')]
        self.assertGreater(len(writes), 150)
        self.assertEqual([float(row[2]) for row in writes[:3]], [51, 50, 51.5])
        self.assertEqual([float(row[2]) for row in writes[-3:]], [51, 50, 51.5])
        self.assertIn('brightness_before=0', report)
        self.assertIn('brightness_readback=37', report)
        elapsed = float(next(line.split('=', 1)[1] for line in report.splitlines()
                             if line.startswith('elapsed=')))
        self.assertGreaterEqual(elapsed, 2.1)

    def test_brightness_that_never_applies_times_out_without_starting_xyz(self):
        trace, report, _ = self.run_package(mode='fader_stuck', choice=2)
        self.assertEqual(trace, ['FADER\tFaderMaster\t37'])
        self.assertIn('reason=error', report)
        self.assertIn('brightness_readback=0', report)
        elapsed = float(next(line.split('=', 1)[1] for line in report.splitlines()
                             if line.startswith('elapsed=')))
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 1.2)

    def test_stop_during_brightness_wait_prevents_any_subsequent_xyz_writes(self):
        trace, report, _ = self.run_package(mode='cleanup_fader_wait', choice=2)
        self.assertEqual(trace, ['FADER\tFaderMaster\t37'])
        self.assertIn('reason=requested_stop', report)
        self.assertIn('frames_written=0', report)

    def test_changed_target_during_brightness_wait_prevents_xyz_output(self):
        trace, report, _ = self.run_package(mode='repatch_fader_wait', choice=2)
        self.assertEqual(trace, ['FADER\tFaderMaster\t37'])
        self.assertIn('reason=error', report)
        self.assertIn('target', report.lower())

    def test_all_channels_are_resolved_before_any_xyz_or_fader_output(self):
        trace, report, _ = self.run_package(mode='missing_attribute', choice=2)
        self.assertEqual(trace, [])
        self.assertIn('reason=error', report)
        self.assertIn('XYZ_Y', report)

    def test_readback_mismatch_stops_without_continuing_the_figure_eight(self):
        trace, report, _ = self.run_package(mode='bad_readback')
        self.assertEqual(len(trace), 3)
        self.assertIn('reason=error', report)
        self.assertIn('readback_matches=false', report)
        self.assertIn('XYZ_X', report)

    def test_selection_change_is_reported_and_stops_further_writes(self):
        trace, report, _ = self.run_package(mode='selection_change')
        self.assertEqual(len(trace), 3)
        self.assertIn('reason=error', report)
        self.assertIn('selection_preserved=false', report)

    def test_cleanup_stops_the_suspended_coroutine_and_retains_its_last_output(self):
        trace, report, _ = self.run_package(mode='cleanup')
        self.assertEqual(len(trace), 3)
        self.assertIn('reason=requested_stop', report)
        self.assertNotIn('reason=completed', report)

    def test_replaced_marker_cannot_receive_a_stale_channel_write(self):
        trace, report, _ = self.run_package(mode='repatch')
        self.assertEqual(len(trace), 3)
        self.assertIn('reason=error', report)
        self.assertIn('target', report.lower())

    def test_long_scheduler_gap_stops_before_a_large_position_jump(self):
        trace, report, _ = self.run_package(mode='stall')
        self.assertEqual(len(trace), 3)
        self.assertIn('reason=timing_gap', report)

    def test_missing_api_prevents_output_and_names_the_missing_function(self):
        trace, report, _ = self.run_package(mode='missing_api')
        self.assertEqual(trace, [])
        self.assertIn('reason=error', report)
        self.assertIn('SetProgPhaser', report)

    def test_missing_encoder_observation_cannot_claim_preserved_context(self):
        trace, report, _ = self.run_package(mode='missing_encoders')
        self.assertEqual(trace, [])
        self.assertIn('reason=error', report)
        self.assertIn('GetSelectedAttribute', report)
        self.assertNotIn('encoders_preserved=true', report)

    def test_partial_write_failure_cannot_keep_the_previous_readback_success(self):
        trace, report, _ = self.run_package(mode='partial_write')
        self.assertEqual(len(trace), 4)
        self.assertIn('reason=error', report)
        self.assertIn('readback_matches=pending', report)

    def test_context_is_observed_again_after_a_write_raises(self):
        trace, report, _ = self.run_package(mode='partial_selection_error')
        self.assertEqual(len(trace), 4)
        self.assertIn('reason=error', report)
        self.assertIn('selection_preserved=false', report)

    def test_scheduler_gap_after_the_final_write_is_reported_before_completion(self):
        trace, report, _ = self.run_package(mode='final_stall')
        self.assertGreater(len(trace), 150)
        self.assertIn('reason=timing_gap', report)
        self.assertNotIn('reason=completed', report)

    def test_builder_refuses_to_overwrite_operator_settings(self):
        result = self.build(destination=self.settings)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('overwrite', result.stderr)

    def test_missing_settings_cannot_build_a_real_output_package_with_defaults(self):
        result = subprocess.run([sys.executable, str(HERE / 'build_direct.py'),
            '--settings', str(self.root / 'missing.json'), '--output', str(self.package)],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.package.exists())

    def test_an_alias_of_the_settings_input_cannot_be_overwritten(self):
        alias = self.root / 'alias.xml'
        alias.symlink_to(self.settings)
        result = self.build(destination=alias)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('overwrite', result.stderr)


# MA is the only boundary that cannot run in a stock Lua interpreter. These
# doubles expose real channel addressing, readback and stop effects to the tests.
# Shell/file IO and the packaged Lua, including its actual coroutine, stay real.
RUNNER = r'''
local mode, choice = arg[2], tonumber(arg[3])
local trace = assert(io.open(os.getenv('DIRECT_TRACE'), 'w'))
local now, changed, valid = 0, false, true
local values, write_calls = {}, 0
local marker = {SubfixtureIndex=7, MovementSpace='Stage'}
function marker:ToAddr() return 'MArker 9' end
local assigned = {}
local level = 12
local pending_level, apply_at = nil, nil
if mode:find('fader_', 1, true) then level = 0 end
function assigned:ToAddr() return 'Sequence 23' end
function assigned:SetFader(t)
    assert(t.token == 'FaderMaster' and t.value == 37)
    if mode:find('fader_', 1, true) then
        if mode ~= 'fader_stuck' then pending_level, apply_at = t.value, now + 0.1 end
    else
        level = t.value
    end
    trace:write('FADER\t' .. t.token .. '\t' .. t.value .. '\n'); trace:flush()
end
function assigned:GetFader(t) assert(t.token == 'FaderMaster'); return level end
local executor = {}
function executor:GetAssignedObj() return assigned end
function ObjectList(query)
    if query == 'MArker 9' then return {marker} end
    assert(query == 'Page 4.205', 'Unexpected object query: ' .. tostring(query))
    return {executor}
end
function GetAttributeIndex(name)
    local attrs = {XYZ_X=0, XYZ_Y=1, XYZ_Z=2}
    if mode == 'missing_attribute' and name == 'XYZ_Y' then return nil end
    return attrs[name]
end
function GetUIChannelIndex(sf, attribute)
    assert(sf == marker.SubfixtureIndex)
    return 11 + attribute
end
function GetProgPhaser(channel, with_flags)
    assert(channel >= 11 and channel <= 13)
    if mode == 'bad_readback' and values[channel] then return {[1]={absolute=0}} end
    return values[channel] or {[1]={absolute=25}}
end
function SetProgPhaser(channel, value)
    write_calls = write_calls + 1
    if (mode == 'partial_write' or mode == 'partial_selection_error') and write_calls == 5 then
        if mode == 'partial_selection_error' then changed = true end
        error('injected partial-frame write failure')
    end
    assert(channel >= 11 and channel <= 13)
    assert(type(value[1].absolute) == 'number')
    assert(value[1].absolute >= 0 and value[1].absolute <= 100)
    values[channel] = value
    trace:write(string.format('XYZ\t%d\t%.9f\n', channel, value[1].absolute)); trace:flush()
    if mode == 'selection_change' then changed = true end
end
if mode == 'missing_api' then SetProgPhaser = nil end
function SelectionFirst()
    if mode == 'empty_selection' then return nil end
    if changed then return 7, 0, 0, 0 end
    return 22, 3, 4, 5
end
function SelectionNext(index) return nil end
local attribute = {ToAddr=function() return 'Attribute 6' end}
function GetSelectedAttribute() return attribute end
function SelectedFeature() return nil end
if mode == 'missing_encoders' then GetSelectedAttribute = nil; SelectedFeature = nil end
function IsObjectValid(obj) return obj ~= marker or valid end
function Time() return now end
function HostOS() return 'Mac' end
function HostType() return 'onPC' end
function Version() return '2.5.test' end
function Printf(fmt, ...) print(string.format(fmt, ...)) end
function Cmd() error('Direct test must not use command-line output or network setup') end
local boxes = 0
function MessageBox(options)
    boxes = boxes + 1
    if boxes == 1 then
        assert(options.message:find('MArker 9', 1, true))
        return {success=true, result=choice}
    end
    print('SUMMARY ' .. options.message)
    return {success=true, result=0}
end
local main, cleanup = assert(loadfile(arg[1]))()
local thread = coroutine.create(main)
local resumes = 0
while coroutine.status(thread) ~= 'dead' do
    local ok, delay = coroutine.resume(thread)
    assert(ok, delay)
    resumes = resumes + 1
    assert(resumes < 300, 'Finite direct test failed to terminate')
    if coroutine.status(thread) ~= 'dead' then
        now = now + (delay or 1/30)
        if pending_level and now >= apply_at then level, pending_level = pending_level, nil end
        if mode == 'cleanup' then cleanup() end
        if mode == 'cleanup_fader_wait' then cleanup() end
        if mode == 'repatch' then valid = false end
        if mode == 'repatch_fader_wait' then valid = false end
        if mode == 'stall' then now = now + 1 end
        if mode == 'final_stall' and resumes == 61 then now = now + 1 end
    end
end
trace:close()
'''


if __name__ == '__main__':
    unittest.main()
