"""Native panel behaviour: the UI module driven with synthetic helper status and MA widget doubles."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from followspot_core import Settings
from plugin_harness import WIDGETS, lua_executable

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    spec = importlib.util.spec_from_file_location('followspot_plugin_build', ROOT/'ma_plugin/build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Loads ui.lua with the generated schema and default configuration. `status(extra)`
# builds a helper snapshot whose applied config is the defaults unless overridden.
LOADER = r'''
local json=dofile(arg[1]..'/json.lua')
local function load(path) local f=assert(io.open(path));local v=f:read('a');f:close();return json.decode(v) end
local schema,defaults=load(arg[2]),load(arg[3])
local UI=assert(loadfile(arg[1]..'/ui.lua'))(json,schema)
local actions={}
local function last() return actions[#actions] or {} end
local function copy(v) return json.decode(json.encode(v)) end
local function new_ui(config)
 return UI.new(signals,'Followspot',copy(config or defaults),'/usr/bin/python3',function(name,payload)
  actions[#actions+1]={name=name,payload=payload}
 end,{})
end
local function status(extra)
 local s={ready=true,running=false,test=false,holding=false,device_open=false,devices={},
  axes={0,0,0,0},buttons={},fault='',warning='',message='Settings applied.',config=copy(defaults)}
 for k,v in pairs(extra or {}) do s[k]=v end
 return s
end
local function enabled(name) local w=find(name);return w~=nil and w.Enabled~=false and w.Enabled~='No' end
local function visible(name) local w=find(name);return w~=nil and shown(w) end
local function visible_text(text)
 for _,w in ipairs(widgets) do if w.Text==text and shown(w) then return true end end
 return false
end
'''


class PluginUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        builder = load_builder()
        cls.schema = builder.schema()
        cls.defaults = builder.plugin_config(Settings())

    def run_ui(self, body):
        lua = lua_executable()
        if not lua:
            self.skipTest('Local Lua unavailable')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'schema.json').write_text(json.dumps(self.schema))
            (root/'defaults.json').write_text(json.dumps(self.defaults))
            runner = root/'run.lua'
            runner.write_text(WIDGETS + LOADER + body + "\nprint('UI_OK')\n")
            out = subprocess.run([lua, str(runner), str(ROOT/'ma_plugin'), str(root/'schema.json'),
                                  str(root/'defaults.json')], capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn('UI_OK', out.stdout)

    def test_schema_carries_sections_choice_labels_and_buttons_fields(self):
        fields = {f['key']: f for page in self.schema.values() for f in page}
        self.assertEqual(set(self.schema), {'Joystick', 'Target', 'Levels', 'Buttons', 'Diagnostics'})
        self.assertTrue(all(f.get('section') for f in fields.values()))
        self.assertEqual(fields['control_mode']['labels'], {'marker': 'MArker', 'pan_tilt': 'Pan / tilt'})
        self.assertEqual(fields['output_mode']['labels'], {'direct': 'Direct (programmer)', 'psn': 'PSN stream'})
        self.assertEqual(fields['action']['choices'][0], 'command')
        self.assertEqual(fields['action']['labels']['release_marker'], 'Release PSN marker')
        self.assertEqual([f['key'] for f in self.schema['Buttons']], ['id', 'action', 'press', 'release'])
        self.assertTrue(fields['python']['python'])

    def test_panel_opens_compact_and_expands_to_setup(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status(),false)
assert(find('State').Text=='STOPPED')
assert(visible('State') and visible('Start') and visible('Stop') and visible('Reset') and visible('Release'))
assert(visible('Test') and visible('Status') and visible('Close'))
assert(visible('Setup') and not visible('Collapse'))
for _,tab in ipairs({'Joystick','Target','Levels','Buttons','Diagnostics'}) do
 assert(not visible('Tab_'..tab),'Tab visible in the compact view: '..tab)
end
assert(not visible('Save'),'Save visible in the compact view')
local compact=ui.root.H
assert(not pcall(click,'Tab_Target'),'A hidden tab was clickable')
click('Setup')
assert(ui.root.H>compact,'Setup did not enlarge the panel')
assert(visible('Tab_Target') and visible('Save') and visible('Collapse') and not visible('Setup'))
assert(visible('State') and visible('Start'),'Live strip hidden in the setup view')
click('Collapse')
assert(ui.root.H==compact and not visible('Tab_Target') and visible('Setup'))
''')

    def test_active_tab_is_highlighted(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status(),false)
click('Setup')
assert(find('Tab_Joystick').TextColor=='Global.Selected')
assert(find('Tab_Target').TextColor~='Global.Selected')
click('Tab_Target')
assert(find('Tab_Target').TextColor=='Global.Selected')
assert(find('Tab_Joystick').TextColor~='Global.Selected')
''')

    def test_pages_have_section_headings_and_previous_next(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status(),false)
click('Setup')
click('Tab_Target')
assert(find('PageLabel').Text=='Page 1 of 3',find('PageLabel').Text)
assert(not enabled('PreviousPage') and enabled('NextPage'))
assert(visible_text('Control') and visible('field_z'))
click('NextPage')
assert(find('PageLabel').Text=='Page 2 of 3')
assert(visible_text('Operating limits') and visible('field_x_min'))
assert(not visible('field_z'),'Previous page field still shown')
click('NextPage')
assert(find('PageLabel').Text=='Page 3 of 3' and not enabled('NextPage'))
assert(visible_text('Movement Space') and visible('field_space_x_min'))
click('PreviousPage')
assert(find('PageLabel').Text=='Page 2 of 3')
click('Tab_Levels')
assert(find('PageLabel').Text=='Page 1 of 2' and visible_text('Brightness'))
''')

    def test_choice_toggles_show_labels_while_the_draft_stores_raw_values(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status(),false)
click('Setup')
click('Tab_Target')
assert(find('field_control_mode').Text=='MArker')
assert(find('field_output_mode').Text=='Direct (programmer)')
click('field_output_mode')
assert(ui.draft.output_mode=='psn' and find('field_output_mode').Text=='PSN stream')
click('field_control_mode')
assert(ui.draft.settings.control_mode=='pan_tilt' and find('field_control_mode').Text=='Pan / tilt')
assert(ui.draft.output_mode=='direct')
click('Tab_Joystick')
click('NextPage')
assert(find('field_invert_x').Text=='Off')
click('field_invert_x')
assert(ui.draft.settings.invert_x==true and find('field_invert_x').Text=='On')
click('Tab_Buttons')
assert(find('field_action').Text=='MA command')
click('field_action')
assert(ui.button_edit.action=='start' and find('field_action').Text=='Start output')
assert(find('field_press').Enabled==false,'Press command editable for a local action')
assert(find('ResetLock').Text=='Reset lock: On')
''')

    def test_device_rows_select_and_open(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status({devices={{index=0,name='PXN-2113 Pro'},{index=3,name='Gamepad'}}}),false)
click('Setup')
assert(find('Device1').Text:find('PXN-2113 Pro',1,true))
assert(find('Device2').Text:find('Gamepad',1,true))
assert(not enabled('OpenDevice'),'Open enabled before a device was chosen')
click('Device2')
assert(find('Device2').TextColor=='Global.Selected')
assert(find('Device1').TextColor~='Global.Selected')
click('OpenDevice')
assert(last().name=='select' and last().payload.index==3 and last().payload.name=='Gamepad')
''')

    def test_mapping_table_rows_load_the_editor(self):
        self.run_ui(r'''
local config=copy(defaults)
config.settings.buttons={['3']={action='start'},['5']={press='Go+ Exec 1.202',release='Go- Exec 1.202'}}
local ui=new_ui(config)
ui:refresh(status({config=config}),false)
click('Setup')
click('Tab_Buttons')
assert(visible_text('Press') and visible_text('Release'),'Mapping table header missing')
assert(find('Mapping_3_action').Text=='Start output')
assert(find('Mapping_5_press').Text=='Go+ Exec 1.202')
click('Mapping_5')
assert(ui.button_edit.id=='5' and find('field_id').Content=='5')
assert(find('field_press').Content=='Go+ Exec 1.202' and find('field_action').Text=='MA command')
assert(ui.mapping_saved==json.encode(ui.button_edit))
click('Mapping_3')
assert(find('field_action').Text=='Start output' and find('field_press').Enabled==false)
''')

    def test_unsaved_indicator_follows_the_applied_config(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status(),false)
click('Setup')
click('Tab_Target')
assert(find('Draft').Text=='No unsaved changes',find('Draft').Text)
find('field_z').Content='1.7'
ui:refresh(status(),false)
assert(find('Draft').Text=='Unsaved changes',find('Draft').Text)
assert(find('Save').Text=='Save changes')
local applied=copy(defaults)
applied.settings.z=1.7
ui:refresh(status({config=applied}),false)
assert(find('Draft').Text=='No unsaved changes','Applied draft still shown as unsaved')
applied.settings.device_name='Another pad'
ui:refresh(status({config=applied}),false)
assert(find('Draft').Text=='No unsaved changes','Helper-selected device shown as unsaved')
click('Tab_Buttons')
find('field_press').Content='Go+ Exec 1.202'
ui:refresh(status({config=applied}),false)
assert(find('Draft').Text:find('Add / update',1,true),'Pending button editor not shown')
''')

    def test_untouched_editors_keep_exact_values_across_redraws(self):
        self.run_ui(r'''
local config=copy(defaults)
config.settings.dead_zone=0.07
config.settings.centre_x=-0.003921568627450966
local ui=new_ui(config)
ui:refresh(status({config=config}),false)
click('Setup')
click('NextPage')
assert(find('field_dead_zone').Content=='7',find('field_dead_zone').Content)
ui:refresh(status({config=config,device_open=true}),false)
ui:refresh(status({config=config}),false)
assert(ui.draft.settings.dead_zone==0.07 and ui.draft.settings.centre_x==-0.003921568627450966)
assert(find('Draft').Text=='No unsaved changes',find('Draft').Text)
find('field_dead_zone').Content='12'
ui:refresh(status({config=config,device_open=true}),false)
assert(ui.draft.settings.dead_zone==0.12)
click('Tab_Levels')
assert(find('field_executor_number').Content=='201',find('field_executor_number').Content)
ui:refresh(status({config=config}),false)
assert(find('field_executor_number').Content=='201' and math.type(ui.draft.settings.executor_number)=='integer')
''')

    def test_cancel_confirmation_and_acknowledge_only_when_needed(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status({holding=true}),false)
assert(not visible('CancelConfirm') and not visible('AckWarning'))
ui.confirm='release'
ui:render()
assert(visible('CancelConfirm') and find('Release').Text=='CONFIRM release')
click('CancelConfirm')
assert(last().name=='cancel_confirm')
ui.confirm=nil
ui:render()
assert(not visible('CancelConfirm') and find('Release').Text=='Release PSN')
ui.confirm='close'
ui:render()
assert(find('Close').Text=='CONFIRM close / release')
ui:refresh(status({warning='Release commands failed: Flash Off'}),false)
assert(visible('AckWarning'))
click('AckWarning')
assert(last().name=='ack_warning')
''')

    def test_ready_hint_warns_that_start_applies_unsaved_changes(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status({device_open=true}),false)
assert(find('Hint').Text:find('Ready to start',1,true),find('Hint').Text)
click('Setup')
click('Tab_Target')
click('field_control_mode')
ui:refresh(status({device_open=true}),false)
local hint=find('Hint').Text
assert(hint:find('unsaved',1,true) and hint:find('pan / tilt',1,true),hint)
''')

    def test_state_badge_and_start_reason(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status({ready=false}),false)
assert(find('State').Text=='STOPPED')
assert(find('Hint').Text:find('Helper not ready',1,true),find('Hint').Text)
assert(not enabled('Start'))
ui:refresh(status(),false)
assert(find('Hint').Text:find('Start needs an open joystick',1,true),find('Hint').Text)
assert(find('Status').TextColor=='Global.Text','Routine status not neutral')
ui:refresh(status({device_open=true}),true)
assert(find('Hint').Text:find('Waiting for the helper',1,true) and not enabled('Start'))
ui:refresh(status({device_open=true,learning='axis_x'}),false)
assert(find('Hint').Text:find('Finish learning first',1,true) and not enabled('Start'))
ui:refresh(status({device_open=true}),false)
assert(enabled('Start'))
local stopped=find('State').TextColor
ui:refresh(status({device_open=true,running=true}),false)
assert(find('State').Text=='RUNNING' and find('State').TextColor~=stopped)
assert(find('Hint').Text:find('Stop output to edit',1,true))
ui:refresh(status({running=true,test=true}),false)
assert(find('State').Text=='TEST RUNNING')
ui:refresh(status({holding=true,held_xyz={1,2,1.5}}),false)
assert(find('State').Text=='PSN HOLDING')
''')

    def test_each_action_decides_its_own_enabled_state(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status({device_open=true,running=true}),false)
assert(find('ResetLock').Text=='Reset lock: On' and enabled('ResetLock'))
assert(not enabled('Reset') and not enabled('Test') and enabled('Stop') and not enabled('Start'))
local unlocked=copy(defaults)
unlocked.settings.reset_locked=false
ui.draft.settings.reset_locked=false
ui:refresh(status({device_open=true,running=true,config=unlocked}),false)
assert(enabled('Reset') and find('ResetLock').Text=='Reset lock: Off')
click('Setup')
click('Tab_Levels')
assert(find('field_executor_page').Enabled==false,'Editor enabled while running')
ui:refresh(status({device_open=true,config=unlocked}),false)
assert(find('field_executor_page').Enabled==true)
assert(find('field_zoom_executor_page').Enabled==false,'Zoom editor enabled while zoom is off')
click('field_zoom_enabled')
assert(find('field_zoom_enabled').Text=='On' and find('field_zoom_executor_page').Enabled==true)
''')

    def test_field_errors_navigate_to_the_field_and_mark_its_label(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status(),false)
ui:notify('dead_zone must be a finite number.','info',{})
assert(not visible('Tab_Joystick'),'An informational notice navigated')
ui:notify('space_y_max must be a finite number.','error',{})
assert(visible('Tab_Target') and find('Tab_Target').TextColor=='Global.Selected','Error did not open its tab')
assert(find('PageLabel').Text=='Page 3 of 3',find('PageLabel').Text)
assert(visible('field_space_y_max'))
assert(find('label_space_y_max').TextColor=='Global.ErrorText')
ui:notify(nil)
assert(find('label_space_y_max').TextColor~='Global.ErrorText','Mark not cleared')
ui.draft.settings.control_mode='pan_tilt'
click('Tab_Joystick')
ui:notify('Fixture group must be positive.','error',{})
assert(find('Tab_Target').TextColor=='Global.Selected' and visible('field_fixture_group'))
assert(find('label_fixture_group').TextColor=='Global.ErrorText')
''')

    def test_field_errors_use_the_fields_reported_by_the_helper(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status(),false)
ui:notify('IDs must be positive.','error',{'marker_id'})
assert(visible('Tab_Target') and find('Tab_Target').TextColor=='Global.Selected','Reported field did not open its tab')
assert(visible('field_marker_id') and find('label_marker_id').TextColor=='Global.ErrorText')
''')

    def test_runtime_faults_do_not_open_setup(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status({running=true}),false)
ui:notify('brightness executor assignment changed; restart output','error')
assert(not visible('Tab_Levels'),'A runtime fault expanded Setup during output')
''')

    def test_errors_in_hidden_fields_name_the_selector_to_switch(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status(),false)
ui:notify('psn_port must be a whole number.','error',{'psn_port'})
ui:refresh(status(),false)
assert(find('Status').Text:find('Switch MArker position output to PSN stream (Setup > Target)',1,true),find('Status').Text)
''')

    def test_confirmation_prompt_outranks_a_persistent_fault(self):
        self.run_ui(r'''
local ui=new_ui()
ui:notify('Press again within 3 s to end PSN streaming.','confirm')
ui:refresh(status({holding=true,fault='Joystick disconnected.'}),false)
assert(find('Status').Text:find('Press again',1,true),find('Status').Text)
assert(find('Status').TextColor=='Global.WarningText')
''')

    def test_reset_lock_label_shows_the_applied_lock(self):
        self.run_ui(r'''
local ui=new_ui()
ui.draft.settings.reset_locked=false
ui:refresh(status(),false)
assert(find('ResetLock').Text=='Reset lock: On',find('ResetLock').Text)
''')

    def test_learned_values_apply_again_after_a_helper_restart(self):
        self.run_ui(r'''
local ui=new_ui()
ui:refresh(status({learned={id=1,values={axis_x=3}}}),false)
assert(ui.draft.settings.axis_x==3)
ui:helper_restarted()
ui:refresh(status({learned={id=1,values={axis_x=5}}}),false)
assert(ui.draft.settings.axis_x==5,'Learned value from a new helper was ignored')
''')


if __name__ == '__main__':
    unittest.main()
