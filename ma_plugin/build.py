"""Build the single-file grandMA3 Joystick Followspot plugin."""
import argparse
import base64
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parent
sys.path.insert(0,str(PROJECT))
from followspot_core import BUTTON_ACTIONS, Settings, setting_types


def literal(text):
    equals='===='
    while ']'+equals+']' in text: equals+='='
    return '['+equals+'['+text+']'+equals+']'


def schema():
    """Setup pages for the native panel: ordered fields grouped into sections, with choice labels."""
    pages={name:[] for name in ('Joystick','Target','Levels','Buttons','Diagnostics')}
    types=setting_types()
    def group(page,section,entries,**common):
        for key,label,*extra in entries:
            field=dict(key=key,label=label,section=section)
            field.update(common)
            field.update(extra[0] if extra else {})
            field.setdefault('kind',types[key].__name__ if key in types else 'str')
            pages[page].append(field)
    group('Joystick','Axes',[('axis_x','X / pan axis'),('axis_y','Y / tilt axis'),('axis_slider','Brightness axis')],learn=True)
    group('Joystick','Inversion',[('invert_x','Invert X / pan'),('invert_y','Invert Y / tilt'),('invert_slider','Invert brightness')])
    group('Joystick','Response',[('dead_zone','Stick dead zone (%)',dict(scale=100)),
        ('max_speed','Maximum speed (m/s)',dict(mode='marker')),
        ('pan_tilt_speed','Maximum speed (% points/s)',dict(mode='pan_tilt')),
        ('centre_x','X centre offset'),('centre_y','Y centre offset')])
    group('Target','Control',[
        ('control_mode','Control mode',dict(kind='choice',choices=['marker','pan_tilt'],
            labels={'marker':'MArker','pan_tilt':'Pan / tilt'})),
        ('output_mode','MArker position output',dict(kind='choice',choices=['direct','psn'],root=True,mode='marker',
            labels={'direct':'Direct (programmer)','psn':'PSN stream'}))])
    group('Target','MArker',[('marker_id','MArker CID'),('z','Fixed height Z (m)'),('initial_x','Initial / reset X (m)'),
        ('initial_y','Initial / reset Y (m)')],mode='marker')
    group('Target','Operating limits',[('x_min','Operating X minimum (m)'),('x_max','Operating X maximum (m)'),
        ('y_min','Operating Y minimum (m)'),('y_max','Operating Y maximum (m)')],mode='marker')
    group('Target','Attributes',[('attribute_'+axis,'Attribute '+axis.upper()) for axis in 'xyz'],mode='marker',output='direct')
    group('Target','Movement Space',[(f'space_{axis}_{end}',f'Movement Space {axis.upper()} {end} (m)')
        for axis in 'xyz' for end in ('min','max')],mode='marker',output='direct')
    group('Target','PSN',[('psn_tracker_id','PSN tracker ID'),('psn_group','PSN multicast group'),
        ('psn_port','PSN port'),('psn_interface','PSN sender interface IPv4')],mode='marker',output='psn')
    group('Target','Pan / tilt group',[('fixture_group','Fixture group'),('initial_pan','Initial / reset pan (%)'),
        ('initial_tilt','Initial / reset tilt (%)'),('attribute_pan','Pan attribute'),('attribute_tilt','Tilt attribute')],mode='pan_tilt')
    group('Target','Pan / tilt limits',[('pan_min','Pan minimum (%)'),('pan_max','Pan maximum (%)'),
        ('tilt_min','Tilt minimum (%)'),('tilt_max','Tilt maximum (%)')],mode='pan_tilt')
    group('Levels','Brightness',[('executor_page','Brightness page'),('executor_number','Brightness executor (Master)')])
    group('Levels','Zoom / iris',[('zoom_enabled','Enable zoom / iris',dict(zoom=False)),('initial_zoom','Initial / reset zoom / iris (%)'),
        ('zoom_executor_page','Zoom / iris page'),('zoom_executor_number','Zoom / iris executor (Temp)')],zoom=True)
    group('Levels','Zoom / iris axis',[('axis_zoom','Zoom / iris axis',dict(learn=True)),('invert_zoom','Invert zoom / iris'),
        ('centre_zoom','Zoom / iris centre offset'),('zoom_dead_zone','Zoom / iris dead zone (%)',dict(scale=100)),
        ('zoom_speed','Zoom / iris speed (% points/s)')],zoom=True)
    group('Buttons','Button editor',[('id','Button index (starts at 0)',dict(learn='button')),
        ('action','Action on press',dict(kind='choice',choices=list(BUTTON_ACTIONS),labels=dict(BUTTON_ACTIONS))),
        ('press','MA command on press',dict(command_only=True)),
        ('release','MA command on release',dict(command_only=True))],button=True)
    group('Diagnostics','Helper',[('python','Python 3.10+ executable (this Mac)',dict(python=True)),
        ('reset_locked','Lock reset while running')])
    group('Diagnostics','Test figure eight',[('test_period','Test cycle duration (s)'),('test_brightness','Test brightness (%)'),
        ('test_size','Test half-width (m)',dict(mode='marker')),
        ('test_pan_tilt_size','Test pan half-swing (%)',dict(mode='pan_tilt'))])
    return pages


def plugin_config(settings):
    """The plugin's {settings, output_mode} shape; OSC transport settings are not part of it."""
    return dict(output_mode='psn' if settings.control_mode=='marker' and settings.position_output=='psn' else 'direct',
        settings={k:v for k,v in settings.to_dict().items() if k not in ('host','port','prefix','position_output')})


def build(destination,settings_path):
    destination,settings_path=Path(destination),Path(settings_path)
    if not settings_path.is_file(): raise ValueError('Saved settings file not found: '+str(settings_path))
    if destination.resolve()==settings_path.resolve() or (destination.exists() and destination.samefile(settings_path)):
        raise ValueError('Plugin output must not overwrite the input settings.')
    config=plugin_config(Settings.load(settings_path))
    modules={'__JSON__':(HERE/'json.lua').read_text(),'__OUTPUT__':(HERE/'output.lua').read_text(),
             '__UI__':(HERE/'ui.lua').read_text()}
    payloads={name:(HERE/name).read_text() for name in ('worker.py','runtime.py')}
    payloads.update({name:(PROJECT/name).read_text() for name in ('followspot_core.py','joystick.py')})
    values=dict(modules)
    values['__DEFAULTS__']=literal(json.dumps(config,ensure_ascii=False,allow_nan=False))
    values['__SCHEMA__']=literal(json.dumps(schema(),ensure_ascii=False))
    values['__PAYLOADS__']='{'+',\n'.join('['+json.dumps(name)+']='+literal(source) for name,source in payloads.items())+'}'
    source=(HERE/'main.lua').read_text()
    source=re.sub('|'.join(map(re.escape,values)),lambda match:values[match.group()],source)
    document=ET.Element('GMA3',DataVersion='2.5.0.3')
    plugin=ET.SubElement(document,'UserPlugin',Name='Joystick Followspot',Author='Joystick Followspot',Version='1.0.0.0')
    component=ET.SubElement(plugin,'ComponentLua',Name='Followspot',InStream='Yes',Installed='No')
    data=source.encode('utf-8');blocks=[data[i:i+1024] for i in range(0,len(data),1024)]
    content=ET.SubElement(component,'FileContent',Size=str(len(blocks)))
    for block in blocks: ET.SubElement(content,'Block',Base64=base64.b64encode(block).decode())
    ET.indent(document);ET.ElementTree(document).write(destination,encoding='utf-8',xml_declaration=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',type=Path,default=PROJECT/'settings.example.json')
    parser.add_argument('--output',type=Path,default=HERE/'JoystickFollowspot.xml')
    args=parser.parse_args();build(args.output,args.settings)
    print(f'Built {args.output} ({args.output.stat().st_size} bytes); source settings unchanged.')
