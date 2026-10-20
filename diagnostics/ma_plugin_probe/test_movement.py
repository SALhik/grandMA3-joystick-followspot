"""Movement-stage checks; every network send is intercepted, never sent to MA."""
import base64
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from followspot_core import Settings


HERE = Path(__file__).resolve().parent


class MovementTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / 'movement.py').is_file(), 'Movement helper is not implemented')
        spec = importlib.util.spec_from_file_location('movement_probe', HERE / 'movement.py')
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.token = 'test-owner'
        self.settings = Settings(marker_id=9, initial_x=2, z=3, test_size=4,
                                 test_period=2, test_brightness=37, executor_number=205)
        (self.root / 'settings.json').write_text(json.dumps(self.settings.to_dict()))
        (self.root / 'lease').write_text(self.token + ':0')
        self.now, self.sends, self.closed = 0.0, [], False

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 1 / 300)
        (self.root / 'lease').write_text(self.token + ':' + str(self.now))

    def sender(self, host, port, prefix):
        owner = self
        class Transport:
            def send(self, address, value):
                owner.sends.append((address, value))
            def close(self):
                owner.closed = True
        return Transport()

    def run_helper(self, **kwargs):
        code = self.helper.run(self.root, self.token, sender_factory=self.sender,
                               clock=self.clock, sleep=self.sleep, **kwargs)
        return code, json.loads((self.root / 'result.json').read_text())

    def test_one_cycle_uses_configured_marker_and_fader_and_returns_to_initial_target(self):
        code, result = self.run_helper()
        self.assertEqual(code, 0)
        self.assertEqual(result['reason'], 'completed')
        self.assertEqual(self.sends[0], ('/cmd', 'ClearSelection; MArker 9; Attribute "XYZ_X" At Absolute Percent 51.000000; Attribute "XYZ_Y" At Absolute Percent 50.000000; Attribute "XYZ_Z" At Absolute Percent 51.500000'))
        self.assertEqual([entry for entry in self.sends if entry[0] != '/cmd'],
                         [('/Page1/Fader205', 37)])
        self.assertTrue(any('Percent 53.000000;' in value for addr, value in self.sends if addr == '/cmd'))
        self.assertEqual(self.sends[-1], self.sends[0])
        self.assertTrue(self.closed)
        self.assertEqual(result['messages_sent'], len(self.sends))
        self.assertEqual(result['last_xyz'], [2.0, 0.0, 3])
        self.assertEqual(result['reception_verified'], False)
        log = [json.loads(line) for line in (self.root / 'sent.jsonl').read_text().splitlines()]
        self.assertEqual(log[0]['value'], self.sends[0][1])

    def test_owned_stop_prevents_even_the_initial_position_and_brightness(self):
        (self.root / 'stop').write_text(self.token)
        _, result = self.run_helper()
        self.assertEqual(result['reason'], 'requested_stop')
        self.assertEqual(self.sends, [])

    def test_lost_lease_stops_output_before_the_full_cycle(self):
        def expire_after_start(seconds):
            self.now += max(seconds, 1 / 300)
            if self.now <= 1 / 30:
                (self.root / 'lease').write_text(self.token + ':1')
        self.sleep = expire_after_start
        _, result = self.run_helper(lease_timeout=0.2)
        self.assertEqual(result['reason'], 'lease_expired')
        self.assertLess(result['elapsed'], 0.3)
        self.assertTrue(self.closed)

    def test_initial_lease_without_a_new_heartbeat_cannot_start_lighting_output(self):
        os.utime(self.root / 'lease', (0, 0))
        self.sleep = lambda seconds: setattr(self, 'now', self.now + max(seconds, 1 / 300))
        _, result = self.run_helper(lease_timeout=0.2)
        self.assertEqual(result['reason'], 'lease_expired')
        self.assertEqual(self.sends, [])

    def test_delayed_transport_setup_requires_another_heartbeat_before_start(self):
        original = self.sender
        setup_done = False
        def before_setup_sleep(seconds):
            self.now += max(seconds, 1 / 300)
            if not setup_done:
                (self.root / 'lease').write_text(self.token + ':before-setup')
        self.sleep = before_setup_sleep
        def delayed_sender(*args):
            nonlocal setup_done
            (self.root / 'lease').write_text(self.token + ':during-setup')
            self.now += 5
            setup_done = True
            return original(*args)
        self.sender = delayed_sender
        _, result = self.run_helper(lease_timeout=0.2)
        self.assertEqual(self.sends, [])
        self.assertEqual(result['reason'], 'lease_expired')

    def test_stop_during_motion_holds_the_last_target_and_ignores_another_owner(self):
        normal_sleep = self.sleep
        def stopping_sleep(seconds):
            normal_sleep(seconds)
            (self.root / 'stop').write_text(self.token if self.now >= 0.3 else 'another-owner')
        self.sleep = stopping_sleep
        _, result = self.run_helper()
        self.assertEqual(result['reason'], 'requested_stop')
        self.assertGreaterEqual(result['elapsed'], 0.3)
        self.assertLess(result['elapsed'], 0.4)
        self.assertNotEqual(result['last_xyz'], [2, 0, 3])
        self.assertNotEqual(self.sends[-1], self.sends[0])
        self.assertEqual([value for address, value in self.sends if address != '/cmd'], [37])

    def test_duplicate_cannot_send_or_overwrite_the_owned_result(self):
        (self.root / 'result.json').write_text('owned result')
        with (self.root / 'reader.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code = self.helper.run(self.root, self.token, sender_factory=self.sender,
                                   clock=self.clock, sleep=self.sleep)
        self.assertEqual(code, 73)
        self.assertEqual(self.sends, [])
        self.assertEqual((self.root / 'result.json').read_text(), 'owned result')

    def test_send_failure_stops_without_attempting_more_motion(self):
        # Keep only the external transport failure fake; the controller stays real.
        original = self.sender
        def factory(*args):
            sender = original(*args)
            def send(address, value):
                self.sends.append((address, value))
                if len(self.sends) == 3:
                    raise OSError('injected UDP failure')
            sender.send = send
            return sender
        self.sender = factory
        code, result = self.run_helper()
        self.assertNotEqual(code, 0)
        self.assertEqual(result['reason'], 'output_error')
        self.assertIn('injected UDP failure', result['detail'])
        self.assertEqual(len(self.sends), 3)
        self.assertEqual(result['messages_sent'], 2)
        self.assertTrue(self.closed)

    def test_non_osc_marker_config_is_rejected_before_output(self):
        self.settings.position_output = 'psn'
        (self.root / 'settings.json').write_text(json.dumps(self.settings.to_dict()))
        code, result = self.run_helper()
        self.assertNotEqual(code, 0)
        self.assertEqual(result['reason'], 'output_error')
        self.assertIn('OSC', result['detail'])
        self.assertEqual(self.sends, [])


class MovementPackageTests(unittest.TestCase):
    def test_builder_cannot_overwrite_the_settings_input(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / 'settings.json'
            settings.write_text(json.dumps(Settings().to_dict()))
            before = settings.read_bytes()
            outcome = subprocess.run([sys.executable, str(HERE / 'build_movement.py'),
                '--settings', str(settings), '--output', str(settings)], capture_output=True)
            self.assertNotEqual(outcome.returncode, 0)
            self.assertEqual(settings.read_bytes(), before)

    def test_xml_runs_embedded_core_and_helper_and_sends_configured_osc_packets(self):
        self.assertTrue((HERE / 'build_movement.py').is_file(), 'Movement builder is not implemented')
        lua = shutil.which('lua5.5') or shutil.which('lua')
        if not lua:
            self.skipTest('Local Lua unavailable; real MA execution remains manual')
        with tempfile.TemporaryDirectory(prefix="MA motion ' package ") as folder:
            root = Path(folder)
            settings = root / 'operator-settings.json'
            settings.write_text(json.dumps(Settings(marker_id=9, prefix='__DURATION__', port=9001,
                test_period=2, test_brightness=37, executor_number=205).to_dict()))
            before = settings.read_bytes()
            package = root / 'movement.xml'
            subprocess.run([sys.executable, str(HERE / 'build_movement.py'), '--settings',
                            str(settings), '--output', str(package)], check=True, capture_output=True)
            self.assertEqual(settings.read_bytes(), before)
            blocks = ET.parse(package).findall('./UserPlugin/ComponentLua/FileContent/Block')
            extracted = root / 'embedded.lua'
            extracted.write_bytes(b''.join(base64.b64decode(b.attrib['Base64']) for b in blocks))
            # Real Lua -> shell -> Python -> core OSC encoder. Intercept only the
            # socket boundary so this cannot reach the operator's console.
            driver = root / 'intercept.py'
            driver.write_text('''import json, os, runpy, sys
from unittest.mock import patch
class Sink:
    def __init__(self, *args): pass
    def setblocking(self, value): pass
    def sendto(self, data, destination):
        with open(os.environ['PACKET_LOG'], 'a') as file:
            file.write(json.dumps([data.hex(), destination]) + '\\n')
        return len(data)
    def close(self): pass
sys.path.insert(0, os.path.dirname(sys.argv[1]))
sys.argv = sys.argv[1:]
with patch('socket.socket', Sink), patch('socket.gethostbyname', return_value='127.0.0.1'):
    runpy.run_path(sys.argv[0], run_name='__main__')
''')
            python = root / 'intercept-python'
            python.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' +
                              shlex.quote(str(driver)) + ' "$@"\n')
            python.chmod(0o700)
            runner = root / 'run.lua'
            runner.write_text('''
function HostType() return 'onPC' end
function HostOS() return 'Mac' end
function Printf(fmt, ...) print(string.format(fmt, ...)) end
local calls = 0
function MessageBox(options)
    calls = calls + 1
    if calls == 1 then
        assert(options.message:find('MArker 9', 1, true))
        assert(options.message:find('9001', 1, true))
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
            env = dict(os.environ, FOLLOWSPOT_MOVEMENT_REPORTS=str(root / 'reports'),
                       PACKET_LOG=str(root / 'packets.jsonl'))
            outcome = subprocess.run([lua, str(runner), str(extracted), str(python)],
                                     cwd=root, env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            self.assertIn('SENT', outcome.stdout)
            reports = list((root / 'reports').glob('run.*/result.json'))
            self.assertEqual(len(reports), 1, outcome.stdout + outcome.stderr)
            result = json.loads(reports[0].read_text())
            self.assertEqual(result['reason'], 'completed')
            packets = [json.loads(line) for line in (root / 'packets.jsonl').read_text().splitlines()]
            self.assertEqual(len(packets), result['messages_sent'])
            self.assertGreater(len(packets), 40)
            first = bytes.fromhex(packets[0][0])
            self.assertTrue(first.startswith(b'/__DURATION__/cmd\0'))
            self.assertIn(b'ClearSelection; MArker 9;', first)
            self.assertEqual(packets[0][1], ['127.0.0.1', 9001])
            self.assertTrue(bytes.fromhex(packets[1][0]).startswith(b'/__DURATION__/Page1/Fader205\0'))
            self.assertFalse(result['reception_verified'])


if __name__ == '__main__':
    unittest.main()
