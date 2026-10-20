from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'ma_plugin'


class PluginLuaTests(unittest.TestCase):
    def execute(self, body):
        lua = shutil.which('lua5.5') or shutil.which('lua')
        if not lua: self.skipTest('Local Lua unavailable')
        with tempfile.TemporaryDirectory() as folder:
            runner = Path(folder)/'run.lua'; runner.write_text(body)
            out = subprocess.run([lua,str(runner),str(ROOT)],capture_output=True,text=True,timeout=10)
            self.assertEqual(out.returncode,0,out.stdout+out.stderr)

    def test_json_roundtrips_commands_unicode_and_rejects_executable_or_invalid_input(self):
        self.execute(r'''
local json = dofile(arg[1]..'/json.lua')
local value = {name="PXN ' 雪\n",buttons={['0']={press='Go+ Sequence "A"',release=''}}}
local out = json.decode(json.encode(value))
assert(out.name == value.name and out.buttons['0'].press == value.buttons['0'].press)
assert(json.decode('"\\uD83D\\uDE00"') == '😀')
assert(not pcall(json.decode, '{"a":1} trailing'))
assert(not pcall(json.decode, 'return os.execute("bad")'))
assert(not pcall(json.encode, {value=0/0}))
''')

    def test_native_output_preserves_selection_and_does_not_assert_synchronous_faders(self):
        self.execute(BOUNDARY + r'''
local Output = dofile(arg[1]..'/output.lua')
local output = Output.new(config)
output:apply({seq=1,target={kind='marker',percent={51,52,50.75}},brightness=37,zoom=55})
assert(#writes==3 and writes[1][1]==0 and writes[1][2]==51)
assert(master.requested==37 and master.level==0)
assert(temp.requested==55 and temp.token=='FaderTemp')
output:apply({seq=2,target={kind='marker',percent={51,52,50.75}},brightness=37,zoom=55})
assert(#writes==3 and master.count==1)
master.level=37
assert(output:feedback().brightness==37)
output:apply({target={kind='marker',percent={51,52,50.75}},brightness=37,zoom=55,force_position=9})
assert(#writes==6 and master.count==1,'Reset must resend position without retaking faders')
marker.SubfixtureIndex=99
assert(not pcall(function() output:apply({target={kind='marker',percent={52,52,50.75}}}) end))
''')

    def test_failed_command_is_not_acknowledged_and_cleanup_releases_only_executed_presses(self):
        self.execute(BOUNDARY + r'''
local Output = dofile(arg[1]..'/output.lua')
local output=Output.new(config)
output:command({id=1,command='Flash On Exec 1.202',owner='1:0',release_command='Flash Off Exec 1.202'})
assert(commands[1]=='Flash On Exec 1.202')
output:cleanup()
assert(commands[2]=='Flash Off Exec 1.202')
assert(not pcall(function() output:command({id=2,command='invalid',owner='1:1'}) end))
assert(output.last_event==1)
''')

    def test_cancelled_press_does_not_release_another_buttons_owned_action(self):
        self.execute(BOUNDARY + r'''
local Output=dofile(arg[1]..'/output.lua')
local output=Output.new(config)
output:command({id=1,command='Flash On Exec 1.202',owner='1:0',release_command='Flash Off Exec 1.202'})
-- Button 1's press was cancelled by Stop; button 0 still owns the same release text.
output:command({id=3,command='Flash Off Exec 1.202',owner='1:1',release=true,paired=true})
assert(#commands==1,'Cancelled press released another owned action')
output:command({id=4,command='Flash Off Exec 1.202',owner='1:0',release=true,paired=true})
assert(#commands==2)
output:command({id=5,command='Go Sequence 2',owner='1:2',release=true,paired=false})
assert(#commands==3,'Release-only mapping must still execute')
''')


BOUNDARY = r'''
local writes, commands = {}, {}
local marker={SubfixtureIndex=7}
local function fader()
 local f={level=0,count=0}
 function f:SetFader(t) self.requested=t.value;self.token=t.token;self.count=self.count+1 end
 function f:GetFader(t) return self.level end
 return f
end
local master,temp=fader(),fader()
local ex1={GetAssignedObj=function() return master end}
local ex2={GetAssignedObj=function() return temp end}
function ObjectList(query)
 if query=='MArker 1' then return {marker} end
 if query=='Page 1.201' then return {ex1} end
 if query=='Page 1.202' then return {ex2} end
 error('Unexpected query: '..query)
end
function GetAttributeIndex(name) return ({XYZ_X=0,XYZ_Y=1,XYZ_Z=2})[name] end
function GetUIChannelIndex(sf,attr) return attr end
function SetProgPhaser(channel,data) writes[#writes+1]={channel,data[1].absolute} end
function IsObjectValid(h) return h~=nil end
function Cmd(command)
 assert(not command:find('ClearSelection',1,true),'Marker output took the selection')
 commands[#commands+1]=command
 return command=='invalid' and 'Illegal Command' or 'OK'
end
local config={output_mode='direct',settings={control_mode='marker',marker_id=1,
attribute_x='XYZ_X',attribute_y='XYZ_Y',attribute_z='XYZ_Z',executor_page=1,
executor_number=201,zoom_enabled=true,zoom_executor_page=1,zoom_executor_number=202}}
'''
