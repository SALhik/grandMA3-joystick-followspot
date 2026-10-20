import base64
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from followspot_core import Settings

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'Packaged macOS launcher requires POSIX shell tools')
class PluginPackageTests(unittest.TestCase):
    def test_imported_xml_runs_native_panel_and_real_helper_without_a_joystick(self):
        self.run_package('direct')

    def test_packaged_psn_stream_holds_on_stop_and_requires_confirmed_release(self):
        self.run_package('psn')

    def test_panel_startup_error_can_be_corrected_and_reopened(self):
        self.run_package('startup_failure')

    def run_package(self,mode):
        self.assertTrue((ROOT/'ma_plugin/build.py').exists(),'Plugin builder not implemented')
        lua=shutil.which('lua5.5') or shutil.which('lua')
        if not lua: self.skipTest('Local Lua unavailable')
        with tempfile.TemporaryDirectory(prefix="MA full ' plugin ") as folder:
            root=Path(folder)
            settings=root/'settings.json'; settings.write_text(json.dumps(Settings(test_period=2).to_dict()))
            before=settings.read_bytes()
            package=root/'plugin.xml'
            result=subprocess.run([sys.executable,str(ROOT/'ma_plugin/build.py'),'--settings',str(settings),
                '--output',str(package)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(settings.read_bytes(),before)
            tree=ET.parse(package)
            self.assertEqual(tree.find('./UserPlugin').get('Name'),'Joystick Followspot')
            blocks=tree.findall('./UserPlugin/ComponentLua/FileContent/Block')
            source=root/'plugin.lua'; source.write_bytes(b''.join(base64.b64decode(b.get('Base64')) for b in blocks))
            runner=root/'runner.lua'; runner.write_text(RUNNER)
            python=sys.executable
            if mode=='psn':
                driver=root/'network_boundary.py';driver.write_text(NETWORK_BOUNDARY)
                wrapper=root/'python-boundary'
                wrapper.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(driver))+' "$@"\n')
                wrapper.chmod(0o700);python=str(wrapper)
            outcome=subprocess.run([lua,str(runner),str(source),python,mode],
                env=dict(os.environ,FOLLOWSPOT_PLUGIN_HOME=str(root/'plugin-home'),
                         PLUGIN_PACKET_LOG=str(root/'packets.jsonl')),
                capture_output=True,text=True,timeout=20)
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


NETWORK_BOUNDARY='''import json, os, runpy, sys
from unittest.mock import patch
class Socket:
    def __init__(self,*a): pass
    def settimeout(self,*a): pass
    def setsockopt(self,*a): pass
    def sendto(self,packet,destination):
        with open(os.environ['PLUGIN_PACKET_LOG'],'a') as f:
            f.write(json.dumps(dict(packet=packet.hex(),destination=destination))+'\\n')
        return len(packet)
    def close(self):
        with open(os.environ['PLUGIN_PACKET_LOG'],'a') as f:f.write(json.dumps(dict(closed=True))+'\\n')
sys.argv=sys.argv[1:]
sys.path.insert(0,os.path.dirname(sys.argv[0]))
with patch('socket.socket',Socket):runpy.run_path(sys.argv[0],run_name='__main__')
'''


RUNNER=r'''
local signals, widgets, vars={}, {}, {}
local now,writes,stage,edit_at,stopped_writes=0,0,0,0,0
local mode=arg[3]
local function widget(class)
 local w={class=class,valid=true,children={}}
 local definition=setmetatable({}, {__index=function(t,k) local v={};rawset(t,k,v);return v end})
 setmetatable(w,{__index=function(t,k)
  if type(k)=='number' then return definition end
 end})
 function w:Append(kind) local child=widget(kind);self.children[#self.children+1]=child;return child end
 function w:close() self.valid=false end
 widgets[#widgets+1]=w
 return w
end
local overlay=widget('Overlay')
function GetFocusDisplay() return {ScreenOverlay=overlay} end
function IsObjectValid(w) return w and w.valid~=false end
function HostType() return 'onPC' end
function HostOS() return 'Mac' end
function Version() return '2.5.test' end
function Time() return now end
function Printf(fmt,...) print(string.format(fmt,...)) end
function UserVars() return vars end
function SetVar(v,k,value) v[k]=value;return true end
function GetVar(v,k) return v[k] end
local marker={SubfixtureIndex=7}
local sequence={level=0,count=0}
function sequence:SetFader(t) self.level=t.value;self.count=self.count+1 end
function sequence:GetFader() return self.level end
local executor={GetAssignedObj=function() return sequence end}
function ObjectList(query)
 if query=='MArker 1' then return {marker} end
 if query=='Page 1.201' then return {executor} end
 error('Unexpected query: '..query)
end
function GetAttributeIndex(name) return ({XYZ_X=0,XYZ_Y=1,XYZ_Z=2})[name] end
function GetUIChannelIndex(sf,a) return a end
function SetProgPhaser(channel,p)
 assert(channel>=0 and channel<=2); assert(p[1].absolute>=0 and p[1].absolute<=100)
 writes=writes+1
end
function Cmd(command) error('Unexpected console command: '..command) end
function MessageBox(o) error('Runtime must not open blocking dialogs') end
local function find(name)
 for i=#widgets,1,-1 do local w=widgets[i];if w.Name==name then return w end end
end
local function click(name)
 local w=assert(find(name),'Missing widget '..name)
 assert(w.Enabled~=false and w.Enabled~='No','Disabled widget '..name)
 assert(signals[w.Clicked],'No callback for '..name);signals[w.Clicked](w)
end
-- Override the initial executable suggestion through a real computer-local preference.
assert(os.execute('/bin/mkdir -p "'..os.getenv('FOLLOWSPOT_PLUGIN_HOME')..'"'))
local pref=assert(io.open(os.getenv('FOLLOWSPOT_PLUGIN_HOME')..'/python.txt','w'));pref:write(arg[2]);pref:close()
local main,cleanup=assert(loadfile(arg[1]))('Joystick Followspot','Followspot',signals,{})
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
  click('Tab_Joystick');find('field_axis_x').Content='1.';stage=5;edit_at=now
 end
 if stage==5 and now-edit_at>.15 then
  assert(find('field_axis_x').Content=='1.','Live refresh overwrote a half-typed number')
  find('field_axis_x').Content='0'
  if mode=='psn' then click('Tab_Target');click('field_output_mode') end
  click('Tab_Live');click('Test');stage=1;edit_at=now
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
  else click('Tab_Target');local edit=assert(find('field_z'));edit.Content='1.7';click('Save');stage=3 end
 end
 if stage==6 and now-edit_at>.15 then
  assert(find('Release').Enabled==true,'First Release click ended stream')
  click('Release');stage=7
 end
 if stage==7 and find('Release').Enabled==false then
  click('Tab_Target');find('field_z').Content='1.7';click('Save');stage=3
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
