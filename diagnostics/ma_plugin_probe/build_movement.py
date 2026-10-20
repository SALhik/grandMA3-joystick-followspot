"""Build a personal, single-file MA movement test from a read-only settings snapshot."""
import argparse
import base64
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
sys.path.insert(0, str(PROJECT))
from movement import load_settings


def literal(text):
    equals = '===='
    while ']' + equals + ']' in text:
        equals += '='
    return '[' + equals + '[' + text + ']' + equals + ']'


def build(destination, settings_path):
    destination, settings_path = Path(destination), Path(settings_path)
    if destination.resolve() == settings_path.resolve() or (
            destination.exists() and destination.samefile(settings_path)):
        raise ValueError('The output package must not overwrite the input settings file.')
    settings = load_settings(settings_path)
    # Exclude device identity, button commands and unrelated personal mappings.
    names = ('control_mode', 'position_output', 'marker_id', 'attribute_x', 'attribute_y',
             'attribute_z', 'initial_x', 'initial_y', 'z', 'x_min', 'x_max', 'y_min', 'y_max',
             'space_x_min', 'space_x_max', 'space_y_min', 'space_y_max', 'space_z_min',
             'space_z_max', 'test_size', 'test_period', 'test_brightness', 'executor_page',
             'executor_number', 'host', 'port', 'prefix')
    snapshot = {name: getattr(settings, name) for name in names}
    s = settings
    preview = (f'REAL OSC OUTPUT — one {s.test_period:g}-second figure eight.\n'
               f'MArker {s.marker_id}; X {max(s.x_min, s.initial_x - s.test_size):g} to '
               f'{min(s.x_max, s.initial_x + s.test_size):g} m; '
               f'Y {max(s.y_min, s.initial_y - s.test_size / 2):g} to '
               f'{min(s.y_max, s.initial_y + s.test_size / 2):g} m; Z {s.z:g} m.\n'
               f'OSC {s.host}:{s.port}; prefix {s.prefix or "(none)"}.\n'
               f'Brightness {s.test_brightness:g}% on Page {s.executor_page} / Fader {s.executor_number}.\n'
               'No joystick needed. Stop the followspot app output first.\n'
               'On completion or cancellation, MA retains the last target and brightness.\n'
               'Watch 3D and System Monitor. Sending does not prove MA reception.')
    source = (HERE / 'movement.lua').read_text(encoding='utf-8')
    payloads = {}
    for name, payload in (
        ('__MOVEMENT_SOURCE__', (HERE / 'movement.py').read_text(encoding='utf-8')),
        ('__CORE_SOURCE__', (PROJECT / 'followspot_core.py').read_text(encoding='utf-8')),
        ('__SETTINGS_JSON__', json.dumps(snapshot, indent=2, allow_nan=False)),
        ('__PREVIEW__', preview),
        ('__DURATION__', str(s.test_period)),
    ):
        payloads[name] = literal(payload) if name != '__DURATION__' else payload
    source = re.sub('|'.join(map(re.escape, payloads)),
                    lambda match: payloads[match.group()], source)
    document = ET.Element('GMA3', DataVersion='2.5.0.3')
    plugin = ET.SubElement(document, 'UserPlugin', Name='Followspot Movement Test',
                           Author='Joystick Followspot', Version='0.2.0.0')
    component = ET.SubElement(plugin, 'ComponentLua', Name='Finite OSC MArker test',
                              InStream='Yes', Installed='No')
    data = source.encode('utf-8')
    blocks = [data[index:index + 1024] for index in range(0, len(data), 1024)]
    content = ET.SubElement(component, 'FileContent', Size=str(len(blocks)))
    for block in blocks:
        ET.SubElement(content, 'Block', Base64=base64.b64encode(block).decode('ascii'))
    ET.indent(document)
    ET.ElementTree(document).write(destination, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=HERE / 'FollowspotMovementTest.xml')
    args = parser.parse_args()
    build(args.output, args.settings)
    print(f'Built {args.output} ({args.output.stat().st_size} bytes); settings were only read.')
