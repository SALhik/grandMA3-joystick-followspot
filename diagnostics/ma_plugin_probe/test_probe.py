"""Behavior checks for the experimental, synthetic-only MA diagnostic."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent


class EmulatorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / 'emulator.py').is_file(), 'Emulator has not been implemented')
        spec = importlib.util.spec_from_file_location('probe_emulator', HERE / 'emulator.py')
        self.emulator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.emulator)
        self.temp = tempfile.TemporaryDirectory(prefix="MA probe ' spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.token = 'test-owner'
        (self.root / 'lease').write_text(self.token + ':0')
        self.processes = []
        self.addCleanup(self.stop_processes)

    def stop_processes(self):
        (self.root / 'stop').write_text(self.token)
        for process in self.processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def launch(self, mode='normal', duration=0.5, lease_timeout=1.2):
        process = subprocess.Popen([
            sys.executable, str(HERE / 'emulator.py'), str(self.root), self.token,
            mode, '--duration', str(duration), '--lease-timeout', str(lease_timeout),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(process)
        return process

    def await_file(self, name, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (self.root / name).exists():
                return (self.root / name).read_text()
            time.sleep(0.01)
        self.fail(f'Helper did not create {name}')

    def test_synthetic_axes_include_deflection_and_a_center_hold_interval(self):
        self.assertEqual(self.emulator.sample_at(0.25), (0.0, 0.0, 25.0, 0.0, 0))
        self.assertEqual(self.emulator.sample_at(1.25), (0.75, -0.5, 60.0, 0.5, 1))
        self.assertEqual(self.emulator.sample_at(2.25), (0.0, 0.0, 60.0, 0.0, 0))
        self.assertEqual(self.emulator.sample_at(3.25), (-0.75, 0.5, 80.0, -0.5, 2))

    def test_included_helper_produces_samples_and_finishes_without_stop(self):
        process = self.launch()
        ready = self.await_file('ready').split('\t')
        self.assertEqual(ready[:2], ['FS_DIAGNOSTIC_1', self.token])
        sample = self.await_file('sample').split('\t')
        self.assertEqual(sample[0], self.token)
        process.wait(timeout=3)
        result = json.loads(self.await_file('result.json'))
        self.assertEqual(result['reason'], 'completed')
        self.assertGreaterEqual(result['samples'], 10)
        self.assertEqual(process.returncode, 0)

    def test_explicit_stop_terminates_only_the_owned_helper(self):
        process = self.launch(duration=5)
        self.await_file('ready')
        (self.root / 'stop').write_text('wrong-owner')
        time.sleep(0.08)
        self.assertIsNone(process.poll())
        (self.root / 'stop').write_text(self.token)
        process.wait(timeout=2)
        self.assertEqual(json.loads(self.await_file('result.json'))['reason'], 'requested_stop')

    def test_lost_lease_exits_without_waiting_for_full_test_duration(self):
        process = self.launch(duration=5, lease_timeout=0.25)
        process.wait(timeout=2)
        result = json.loads(self.await_file('result.json'))
        self.assertEqual(result['reason'], 'lease_expired')
        self.assertLess(result['elapsed'], 1.5)

    def test_injected_failure_is_recorded_and_returns_nonzero(self):
        process = self.launch(mode='fault', duration=2)
        process.wait(timeout=3)
        result = json.loads(self.await_file('result.json'))
        self.assertEqual(result['reason'], 'injected_fault')
        self.assertNotEqual(process.returncode, 0)

    def test_duplicate_cannot_replace_active_readers_result(self):
        first = self.launch(duration=5)
        self.await_file('ready')
        second = self.launch()
        second.wait(timeout=2)
        self.assertEqual(second.returncode, 73)
        self.assertIsNone(first.poll())
        self.assertFalse((self.root / 'result.json').exists())


class PackageTests(unittest.TestCase):
    def test_single_xml_executes_its_embedded_payload_without_source_files(self):
        self.assertTrue((HERE / 'build.py').is_file(), 'Package builder has not been implemented')
        lua = shutil.which('lua5.5') or shutil.which('lua')
        if not lua:
            self.skipTest('A local Lua interpreter is unavailable; MA execution is still manual')
        with tempfile.TemporaryDirectory(prefix="MA embedded ' package ") as temp:
            root = Path(temp)
            package = root / 'diagnostic.xml'
            subprocess.run([sys.executable, str(HERE / 'build.py'), '--output', str(package)],
                           check=True, capture_output=True, text=True)
            shipped = HERE / 'FollowspotDiagnostic.xml'
            self.assertEqual(shipped.read_bytes(), package.read_bytes(),
                             'Rebuild FollowspotDiagnostic.xml before distributing it')
            tree = ET.parse(shipped)
            blocks = tree.findall('./UserPlugin/ComponentLua/FileContent/Block')
            self.assertTrue(blocks, 'Single-file plugin contains no embedded Lua')
            source = b''.join(base64.b64decode(b.attrib['Base64']) for b in blocks)
            extracted = root / 'embedded.lua'
            extracted.write_bytes(source)
            # Only MA's display/platform boundary is doubled; extraction, Python
            # launch, samples and process exit are real. No MA runtime claim.
            runner = root / 'run.lua'
            runner.write_text('''
function HostType() return 'onPC' end
function HostOS() return 'Mac_arm64' end
function Printf(fmt, ...) print(string.format(fmt, ...)) end
local calls = 0
function MessageBox(options)
    calls = calls + 1
    if calls == 1 then
        return {success=true, result=1, inputs={['Python executable']=arg[2]}}
    end
    print('SUMMARY ' .. options.message)
    return {success=true, result=0}
end
local main = assert(loadfile(arg[1]))()
local thread = coroutine.create(function() main() end)
while coroutine.status(thread) ~= 'dead' do
    local ok, delay = coroutine.resume(thread)
    assert(ok, delay)
    if coroutine.status(thread) ~= 'dead' then
        assert(os.execute('/bin/sleep ' .. string.format('%.6f', delay or 0.033)))
    end
end
''')
            env = dict(os.environ, FOLLOWSPOT_DIAGNOSTIC_REPORTS=str(root / 'reports'))
            outcome = subprocess.run([lua, str(runner), str(extracted), sys.executable],
                                     cwd=root, env=env, text=True, capture_output=True, timeout=20)
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            reports = list((root / 'reports').glob('run.*/report.txt'))
            self.assertEqual(len(reports), 1, outcome.stdout + outcome.stderr)
            self.assertIn('PASS', reports[0].read_text())
            self.assertIn('reason=completed', reports[0].read_text())
            self.assertIn(' X=', outcome.stdout)
            results = json.loads((reports[0].parent / 'result.json').read_text())
            self.assertEqual(results['reason'], 'completed')
            self.assertGreaterEqual(results['samples'], 90)


if __name__ == '__main__':
    unittest.main()
