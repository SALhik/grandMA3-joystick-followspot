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
from followspot_core import Settings, setting_types


def literal(text):
    equals='===='
    while ']'+equals+']' in text: equals+='='
    return '['+equals+'['+text+']'+equals+']'


def schema():
    pages={name:[] for name in ('Joystick','Target','Levels','Diagnostics')}
    types=setting_types()
    def field(page,key,label,**extra):
        pages[page].append(dict(key=key,label=label,kind=types[key].__name__,**extra))
    for key,label in [('axis_x','X / pan axis'),('axis_y','Y / tilt axis'),('axis_slider','Brightness axis')]:
        field('Joystick',key,label,learn=True)
    for key,label in [('invert_x','Invert X / pan'),('invert_y','Invert Y / tilt'),('invert_slider','Invert brightness')]:
        field('Joystick',key,label)
    field('Joystick','dead_zone','Stick dead zone (%)',scale=100)
    field('Joystick','max_speed','Maximum speed (m/s)',mode='marker')
    field('Joystick','pan_tilt_speed','Maximum speed (% points/s)',mode='pan_tilt')
    field('Joystick','centre_x','X centre offset');field('Joystick','centre_y','Y centre offset')
    pages['Target'] += [dict(key='control_mode',label='Control',kind='choice',choices=['marker','pan_tilt']),
                        dict(key='output_mode',label='MArker position output',kind='choice',choices=['direct','psn'],root=True,mode='marker')]
    marker=[('marker_id','MArker CID'),('z','Fixed height Z (m)'),('initial_x','Initial / reset X (m)'),
        ('initial_y','Initial / reset Y (m)'),('x_min','Operating X minimum (m)'),('x_max','Operating X maximum (m)'),
        ('y_min','Operating Y minimum (m)'),('y_max','Operating Y maximum (m)')]
    for key,label in marker: field('Target',key,label,mode='marker')
    for axis in 'xyz':
        for end in ('min','max'): field('Target',f'space_{axis}_{end}',f'Movement Space {axis.upper()} {end} (m)',mode='marker',output='direct')
        field('Target','attribute_'+axis,'Attribute '+axis.upper(),mode='marker',output='direct')
    for key,label in [('psn_tracker_id','PSN tracker ID'),('psn_group','PSN multicast group'),
        ('psn_port','PSN port'),('psn_interface','PSN sender interface IPv4')]:
        field('Target',key,label,mode='marker',output='psn')
    for key,label in [('fixture_group','Fixture group'),('pan_min','Pan minimum (%)'),('pan_max','Pan maximum (%)'),
        ('tilt_min','Tilt minimum (%)'),('tilt_max','Tilt maximum (%)'),('initial_pan','Initial / reset pan (%)'),
        ('initial_tilt','Initial / reset tilt (%)'),('attribute_pan','Pan attribute'),('attribute_tilt','Tilt attribute')]:
        field('Target',key,label,mode='pan_tilt')
    for key,label in [('executor_page','Brightness page'),('executor_number','Brightness executor (Master)'),
        ('zoom_enabled','Enable zoom / iris')]: field('Levels',key,label)
    for key,label in [('axis_zoom','Zoom / iris axis'),('invert_zoom','Invert zoom / iris'),
        ('centre_zoom','Zoom / iris centre offset'),('zoom_speed','Zoom / iris speed (% points/s)'),
        ('initial_zoom','Initial / reset zoom / iris (%)'),('zoom_executor_page','Zoom / iris page'),
        ('zoom_executor_number','Zoom / iris executor (Temp)')]:
        field('Levels',key,label,zoom=True,learn=key=='axis_zoom')
    field('Levels','zoom_dead_zone','Zoom / iris dead zone (%)',zoom=True,scale=100)
    for key,label in [('test_period','Test cycle duration (s)'),('test_brightness','Test brightness (%)'),
        ('test_size','Test half-width (m)'),('test_pan_tilt_size','Test pan half-swing (%)'),
        ('reset_locked','Lock reset while running')]:
        field('Diagnostics',key,label,**({'mode':'marker'} if key=='test_size' else {'mode':'pan_tilt'} if key=='test_pan_tilt_size' else {}))
    return pages


def build(destination,settings_path):
    destination,settings_path=Path(destination),Path(settings_path)
    if not settings_path.is_file(): raise ValueError('Saved settings file not found: '+str(settings_path))
    if destination.resolve()==settings_path.resolve() or (destination.exists() and destination.samefile(settings_path)):
        raise ValueError('Plugin output must not overwrite the input settings.')
    settings=Settings.load(settings_path)
    config=dict(output_mode='psn' if settings.control_mode=='marker' and settings.position_output=='psn' else 'direct',
        settings={k:v for k,v in settings.to_dict().items() if k not in ('host','port','prefix','position_output')})
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
