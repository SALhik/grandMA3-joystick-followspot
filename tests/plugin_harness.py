"""Shared offline harness: build the plugin XML and run its Lua against MA doubles."""
import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from followspot_core import Settings

ROOT = Path(__file__).resolve().parents[1]


def lua_executable():
    return shutil.which('lua5.5') or shutil.which('lua')


def build_source(root, **settings):
    """Build the package from a temporary settings file and return (package, decoded Lua)."""
    settings_path = root/'settings.json'
    settings_path.write_text(json.dumps(Settings(**settings).to_dict()))
    before = settings_path.read_bytes()
    package = root/'plugin.xml'
    result = subprocess.run([sys.executable, str(ROOT/'ma_plugin/build.py'), '--settings', str(settings_path),
                             '--output', str(package)], capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    if settings_path.read_bytes() != before:
        raise AssertionError('Builder modified its input settings.')
    if ET.parse(package).find('./UserPlugin').get('Name') != 'Joystick Followspot':
        raise AssertionError('Unexpected plugin name.')
    blocks = ET.parse(package).findall('./UserPlugin/ComponentLua/FileContent/Block')
    source = root/'plugin.lua'
    source.write_bytes(b''.join(base64.b64decode(b.get('Base64')) for b in blocks))
    return package, source


def psn_python(root):
    """Return a Python wrapper whose sockets log PSN packets instead of sending them."""
    driver = root/'network_boundary.py'
    driver.write_text(NETWORK_BOUNDARY)
    wrapper = root/'python-boundary'
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(driver)) + ' "$@"\n')
    wrapper.chmod(0o700)
    return str(wrapper)


def run_lua(root, source, scenario, python=sys.executable, mode='direct', timeout=30, env=None):
    """Run PRELUDE + scenario with the packaged plugin; returns the completed process."""
    runner = root/'runner.lua'
    runner.write_text(PRELUDE + '\n' + scenario)
    return subprocess.run([lua_executable(), str(runner), str(source), python, mode],
                          env=dict(os.environ, FOLLOWSPOT_PLUGIN_HOME=str(root/'plugin-home'),
                                   PLUGIN_PACKET_LOG=str(root/'packets.jsonl'), **(env or {})),
                          capture_output=True, text=True, timeout=timeout)


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


# MA widget doubles. `click` only reaches a widget that is enabled and visible
# together with every parent, as an operator could.
WIDGETS = r'''
local signals, widgets={}, {}
local function widget(class)
 local w={class=class,valid=true,children={}}
 local definition=setmetatable({}, {__index=function(t,k) local v={};rawset(t,k,v);return v end})
 setmetatable(w,{__index=function(t,k)
  if type(k)=='number' then return definition end
 end})
 function w:Append(kind)
  local child=widget(kind)
  child.parent=self
  self.children[#self.children+1]=child
  return child
 end
 function w:close() self.valid=false end
 widgets[#widgets+1]=w
 return w
end
local overlay=widget('Overlay')
function GetFocusDisplay() return {ScreenOverlay=overlay} end
function IsObjectValid(w) return w and w.valid~=false end
local function shown(w)
 while w do
  if w.Visible==false or w.Visible=='No' then return false end
  w=w.parent
 end
 return true
end
local function find(name)
 for i=#widgets,1,-1 do local w=widgets[i];if w.Name==name then return w end end
end
local function click(name)
 local w=assert(find(name),'Missing widget '..name)
 assert(shown(w),'Hidden widget '..name)
 assert(w.Enabled~=false and w.Enabled~='No','Disabled widget '..name)
 assert(signals[w.Clicked],'No callback for '..name);signals[w.Clicked](w)
end
'''

# MA API doubles and the loaded plugin entry points. Scenarios drive `main` as a
# coroutine; `step(n, real)` resumes it n times, advancing the simulated MA clock
# by the requested delay (and really sleeping when `real`, so the embedded Python
# helper can make progress).
PRELUDE = WIDGETS + r'''
local vars={}
local now,writes,stage,edit_at,stopped_writes=0,0,0,0,0
local mode=arg[3]
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
-- Override the initial executable suggestion through a real computer-local preference.
assert(os.execute('/bin/mkdir -p "'..os.getenv('FOLLOWSPOT_PLUGIN_HOME')..'"'))
local pref=assert(io.open(os.getenv('FOLLOWSPOT_PLUGIN_HOME')..'/python.txt','w'));pref:write(arg[2]);pref:close()
local main,cleanup=assert(loadfile(arg[1]))('Joystick Followspot','Followspot',signals,{})
local thread
local function step(count,real)
 for _=1,count or 1 do
  if not thread or coroutine.status(thread)=='dead' then return end
  local ok,delay=coroutine.resume(thread);assert(ok,delay)
  local seconds=type(delay)=='number' and delay or 1/30
  if real~=false then assert(os.execute('/bin/sleep '..string.format('%.6f',seconds))) end
  now=now+seconds
 end
end
local function run_until(predicate,limit)
 for _=1,limit or 300 do
  if predicate() then return true end
  step(1)
 end
 return predicate()
end
'''
