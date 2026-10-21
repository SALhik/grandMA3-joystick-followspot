"""Packaged-plugin lifecycle: helper failure recovery, confirmations, notices and arguments."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from plugin_harness import build_source, lua_executable, psn_python, run_lua

READY = r"""
local function ready() local t=find('Test') return t and t.Enabled~=false end
local function state_text() local w=find('State') or find('Status') return w and tostring(w.Text) or '' end
local function running() return state_text():find('RUNNING',1,true)~=nil end
"""


@unittest.skipUnless(os.name == 'posix', 'Packaged macOS launcher requires POSIX shell tools')
class PluginLifecycleTests(unittest.TestCase):
    def scenario(self, body, python=None, psn=False, **settings):
        if not lua_executable():
            self.skipTest('Local Lua unavailable')
        folder = tempfile.TemporaryDirectory(prefix='MA lifecycle ')
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        settings.setdefault('test_period', 30)
        _, source = build_source(root, **settings)
        if python == 'SILENT':
            # A helper that dies without writing a status file or any log output.
            silent = root/'silent-python'
            silent.write_text('#!/bin/sh\nexit 0\n')
            silent.chmod(0o700)
            python = str(silent)
        elif python is None:
            python = psn_python(root) if psn else sys.executable
        outcome = run_lua(root, source, READY + body + "\nprint('LIFECYCLE_OK')\n", python=python,
                          mode='psn' if psn else 'direct', env=dict(GOOD_PYTHON=sys.executable))
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
        self.assertIn('LIFECYCLE_OK', outcome.stdout)
        return root

    def test_close_ends_the_panel_when_the_helper_never_started(self):
        self.scenario(r'''
thread=coroutine.create(main)
step(200,false)
click('Close')
step(10,false)
assert(coroutine.status(thread)=='dead','Close did not end the panel after the helper never started')
''', python='/nonexistent/python3')

    def test_unresponsive_helper_is_handled_once(self):
        root = self.scenario(r'''
thread=coroutine.create(main)
step(400,false)
assert(find('Status').TextColor=='Global.ErrorText','Unresponsive helper is not shown as an error')
cleanup()
''', python='/nonexistent/python3')
        urgent = json.loads(next((root/'plugin-home').glob('run.*/urgent.json')).read_text())
        self.assertLessEqual(urgent['id'], 2, 'Shutdown was re-sent every tick')

    def test_reconnect_relaunches_after_the_helper_never_started(self):
        root = self.scenario(r'''
thread=coroutine.create(main)
step(200,false)
click('Setup')
click('Tab_Diagnostics')
find('field_python').Content=os.getenv('GOOD_PYTHON')
click('Reconnect')
assert(run_until(ready,300),'Reconnected helper never became ready')
click('Close')
step(60)
assert(coroutine.status(thread)=='dead','Plugin did not terminate after Close')
''', python='/nonexistent/python3')
        self.assertEqual(len(list((root/'plugin-home').glob('run.*'))), 2)

    def test_release_confirmation_expires_and_is_cleared_by_other_actions(self):
        self.scenario(r'''
thread=coroutine.create(main)
assert(run_until(ready))
click('Test')
assert(run_until(running),'Test did not start')
click('Stop')
assert(run_until(function() return find('Release').Enabled==true end),'Stop did not hold PSN')
click('Release');step(1)
assert(find('Release').Text=='CONFIRM release','Missing release confirmation')
now=now+4;step(2)
assert(find('Release').Text~='CONFIRM release','Release confirmation did not expire')
click('Release');step(10)
assert(find('Release').Enabled==true,'An expired confirmation released the stream')
click('Reset');step(1)
assert(find('Release').Text~='CONFIRM release','Another action did not clear the confirmation')
click('Release');step(10)
assert(find('Release').Enabled==true,'A cleared confirmation released the stream')
click('Release')
assert(run_until(function() return find('Release').Enabled==false end),'Confirmed release did not end the stream')
click('Close')
step(60)
assert(coroutine.status(thread)=='dead')
''', psn=True, position_output='psn')

    def test_informational_notices_are_not_shown_as_errors(self):
        self.scenario(r'''
thread=coroutine.create(main)
assert(run_until(ready))
click('Setup')
click('Tab_Buttons')
find('field_id').Content='3'
click('AddMapping');step(2)
local status=find('Status')
assert(status.Text:find('Mapping added',1,true),'Notice missing: '..tostring(status.Text))
assert(status.TextColor~='Global.ErrorText','Informational notice shown as an error')
click('Close');step(60)
''')

    def test_reset_is_disabled_while_locked_and_running(self):
        self.scenario(r'''
thread=coroutine.create(main)
assert(run_until(ready))
click('Test')
assert(run_until(running),'Test did not start')
assert(find('Reset').Enabled==false,'Reset enabled while locked and running')
click('ResetLock')
assert(run_until(function() return find('Reset').Enabled==true end),'Unlocked Reset stayed disabled while running')
click('Stop')
assert(run_until(function() return not running() end))
click('Close');step(60)
''')

    def test_plugin_arguments_drive_an_open_panel(self):
        self.scenario(r'''
local quiet=coroutine.create(main)
assert(coroutine.resume(quiet,nil,'stop'))
assert(coroutine.status(quiet)=='dead' and not find('JoystickFollowspotPanel'),'Argument opened a closed panel')
thread=coroutine.create(main)
assert(run_until(ready))
assert(coroutine.resume(coroutine.create(main),nil,' Test '))
assert(run_until(running),'Argument "test" did not start output')
assert(coroutine.resume(coroutine.create(main),nil,'stop'))
assert(run_until(function() return not running() end),'Argument "stop" did not stop output')
assert(run_until(function() return find('Release').Enabled==true end),'Stop did not hold PSN')
assert(coroutine.resume(coroutine.create(main),nil,'release'))
assert(run_until(function() return find('Release').Enabled==false end),'Argument "release" was not immediate')
assert(coroutine.resume(coroutine.create(main),nil,'bogus'))
step(1)
assert(find('Status').Text:find('bogus',1,true),'Unknown argument was not reported')
click('Close');step(60)
assert(coroutine.status(thread)=='dead')
''', psn=True, position_output='psn')

    def test_settings_are_written_only_when_changed_and_read_back(self):
        self.scenario(r'''
local stored=0
local original=SetVar
SetVar=function(v,k,value) stored=stored+1;return original(v,k,value) end
thread=coroutine.create(main)
assert(run_until(ready))
click('Setup')
click('Save')
assert(run_until(function() return stored==1 end),'First save did not store settings')
click('Save');step(20)
assert(stored==1,'Unchanged settings were rewritten')
SetVar=function() stored=stored+1;return true end
click('Tab_Target');find('field_z').Content='1.9';click('Save')
assert(run_until(function() return find('Status').Text:find('did not store',1,true) end),'Readback mismatch was not reported')
SetVar=original
click('Close');step(60)
''')

    def test_close_while_waiting_for_a_silent_helper_ends_the_panel(self):
        self.scenario(r'''
thread=coroutine.create(main)
step(30,false)
click('Close')
step(300,false)
assert(coroutine.status(thread)=='dead','Close never ended the panel for a helper with an empty log')
''', python='SILENT')

    def test_close_wins_over_a_later_reconnect(self):
        root = self.scenario(r'''
thread=coroutine.create(main)
step(30,false)
click('Close')
click('Setup');click('Tab_Diagnostics')
if find('Reconnect').Enabled~=false then click('Reconnect') end
step(300,false)
assert(coroutine.status(thread)=='dead','Reconnect cancelled a pending Close')
''', python='SILENT')
        self.assertEqual(len(list((root/'plugin-home').glob('run.*'))), 1)

    def test_killed_helper_clears_stale_state_and_allows_reconnect(self):
        root = self.scenario(r'''
thread=coroutine.create(main)
assert(run_until(ready))
click('Test')
assert(run_until(running),'Test did not start')
local folder=io.popen('ls -d "'..os.getenv('FOLLOWSPOT_PLUGIN_HOME')..'"/run.*'):read('l')
local f=assert(io.open(folder..'/status.json'));local pid=f:read('a'):match('"pid": *(%d+)');f:close()
assert(pid and os.execute('kill -9 '..pid))
step(200,false)
assert(not running(),'Badge still shows output from a dead helper: '..state_text())
assert(state_text():find('NO HELPER',1,true),state_text())
click('Setup');click('Tab_Diagnostics');click('Reconnect')
assert(run_until(ready,300),'Reconnected helper never became ready')
click('Close');step(60)
assert(coroutine.status(thread)=='dead')
''')
        self.assertEqual(len(list((root/'plugin-home').glob('run.*'))), 2)

    def test_reset_lock_toggle_inverts_the_applied_lock(self):
        self.scenario(r'''
thread=coroutine.create(main)
assert(run_until(ready))
click('Setup');click('Tab_Diagnostics')
while not find('field_reset_locked') or not shown(find('field_reset_locked')) do click('NextPage') end
click('field_reset_locked')
click('ResetLock')
assert(run_until(function() for _,v in pairs(vars) do if v:find('"reset_locked":false',1,true) then return true end end end),
       'Reset lock toggle did not invert the applied lock')
click('Close');step(60)
''')

    def test_plugin_arguments_capture_typed_edits(self):
        self.scenario(r'''
thread=coroutine.create(main)
assert(run_until(ready))
click('Setup');click('Tab_Target')
find('field_z').Content='1.8'
assert(coroutine.resume(coroutine.create(main),nil,'test'))
assert(run_until(function() for _,v in pairs(vars) do if v:find('"z":1.8',1,true) then return true end end end),
       'Argument Start ignored a typed edit')
assert(coroutine.resume(coroutine.create(main),nil,'stop'))
click('Close');step(60)
''')

    def test_confirmation_expiry_keeps_other_notices(self):
        self.scenario(r'''
thread=coroutine.create(main)
assert(run_until(ready))
click('Test')
assert(run_until(running),'Test did not start')
click('Stop')
assert(run_until(function() return find('Release').Enabled==true and not running() end),'Stop did not hold PSN')
click('Release');step(1)
assert(coroutine.resume(coroutine.create(main),nil,'bogus'))
now=now+4;step(2)
assert(find('Status').Text:find('bogus',1,true),'Confirmation expiry wiped another notice: '..find('Status').Text)
click('Release');step(1);click('Release')
assert(run_until(function() return find('Release').Enabled==false end))
click('Close');step(60)
''', psn=True, position_output='psn')


if __name__ == '__main__':
    unittest.main()
