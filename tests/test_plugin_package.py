import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from plugin_harness import build_source, lua_executable, psn_python, run_lua


@unittest.skipUnless(os.name == 'posix', 'Packaged macOS launcher requires POSIX shell tools')
class PluginPackageTests(unittest.TestCase):
    def test_imported_xml_runs_native_panel_and_real_helper_without_a_joystick(self):
        self.run_package('direct')

    def test_packaged_psn_stream_holds_on_stop_and_requires_confirmed_release(self):
        self.run_package('psn')

    def test_panel_startup_error_can_be_corrected_and_reopened(self):
        self.run_package('startup_failure')

    def run_package(self,mode):
        if not lua_executable(): self.skipTest('Local Lua unavailable')
        with tempfile.TemporaryDirectory(prefix="MA full ' plugin ") as folder:
            root=Path(folder)
            _,source=build_source(root,test_period=2)
            python=psn_python(root) if mode=='psn' else sys.executable
            outcome=run_lua(root,source,SCENARIO,python=python,mode=mode,timeout=20)
            self.assertEqual(outcome.returncode,0,outcome.stdout+outcome.stderr)
            self.assertIn('PACKAGE_OK',outcome.stdout)
            reports=list((root/'plugin-home').glob('run.*/status.json'))
            self.assertEqual(len(reports),1)
            status=json.loads(reports[0].read_text())
            self.assertEqual(status['exit_reason'],'shutdown')
            self.assertFalse(status['running'])
            self.assertFalse(status['device_open'])
            if mode=='psn':
                packets=[json.loads(line) for line in (root/'packets.jsonl').read_text().splitlines()]
                data=[p for p in packets if p.get('packet')]
                self.assertGreater(len(data),8)
                self.assertEqual(data[0]['destination'],['236.10.10.10',56565])
                self.assertTrue(any(bytes.fromhex(p['packet'])[:2]==b'\x55\x67' for p in data))
                self.assertEqual(sum(p.get('closed',False) for p in packets),1)





SCENARIO=r'''
if mode=='startup_failure' then
 local original=GetFocusDisplay
 GetFocusDisplay=function() return {ScreenOverlay={Append=function(_,kind)
  local broken=overlay:Append(kind)
  broken.Append=function() error('Injected panel initialization failure') end
  return broken
 end}} end
 local failed=coroutine.create(main);local ok,why=coroutine.resume(failed)
 assert(not ok and tostring(why):find('Injected panel initialization failure',1,true))
 assert(find('JoystickFollowspotPanel').valid==false,'Partial panel was not closed after initialization error')
 GetFocusDisplay=original
end
local thread=coroutine.create(main)
for tick=1,450 do
 if coroutine.status(thread)=='dead' then break end
 local ok,delay=coroutine.resume(thread);assert(ok,delay)
 local test=find('Test')
 if stage==0 and test and test.Enabled~=false and test.Enabled~='No' then
  click('Setup');click('Tab_Joystick');find('field_axis_x').Content='1.';stage=5;edit_at=now
 end
 if stage==5 and now-edit_at>.15 then
  assert(find('field_axis_x').Content=='1.','Live refresh overwrote a half-typed number')
  find('field_axis_x').Content='0'
  if mode=='psn' then click('Tab_Target');click('field_output_mode') end
  click('Collapse');click('Test');stage=1;edit_at=now
 end
 if stage==1 and (writes>15 or mode=='psn' and sequence.count>0 and now-edit_at>.4) then
  click('Stop');stopped_writes=writes;stage=2
 end
 local stop=find('Stop')
 if stage==2 and stop and (stop.Enabled==false or stop.Enabled=='No') then
  assert(writes==stopped_writes,'A stale motion frame was applied after Stop')
  if mode=='psn' then
   assert(find('Release').Enabled==true,'Stop did not preserve PSN hold')
   click('Release');assert(find('Release').Text=='CONFIRM release','Missing release confirmation')
   stage=6;edit_at=now
  else click('Setup');click('Tab_Target');local edit=assert(find('field_z'));edit.Content='1.7';click('Save');stage=3 end
 end
 if stage==6 and now-edit_at>.15 then
  assert(find('Release').Enabled==true,'First Release click ended stream')
  click('Release');stage=7
 end
 if stage==7 and find('Release').Enabled==false then
  click('Setup');click('Tab_Target');find('field_z').Content='1.7';click('Save');stage=3
 end
 if stage==3 then
  for _,value in pairs(vars) do
   if value:find('"z":1.7',1,true) then click('Close');stage=4;break end
  end
 end
 if coroutine.status(thread)~='dead' then
  local seconds=type(delay)=='number' and delay or 1/30
  assert(os.execute('/bin/sleep '..string.format('%.6f',seconds)));now=now+seconds
 end
end
assert(stage==4,'Did not exercise test/Stop/config/save/Close; stage='..stage)
assert(coroutine.status(thread)=='dead','Plugin did not terminate after Close')
assert(writes>15 or mode=='psn' and writes==0,'Incorrect native position output')
print('PACKAGE_OK')
'''
