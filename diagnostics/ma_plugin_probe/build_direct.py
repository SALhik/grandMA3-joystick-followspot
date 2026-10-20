"""Build a finite native-Lua MArker test from the saved app settings (read only)."""
import argparse
import base64
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
sys.path.insert(0, str(PROJECT))
from followspot_core import Settings, clamp, figure_eight


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
    if not settings_path.is_file():
        raise ValueError(f'The saved settings file does not exist: {settings_path}')
    s = Settings.load(settings_path)
    if s.control_mode != 'marker':
        raise ValueError('This native-channel probe requires MArker control mode.')
    if s.test_period > 30:
        raise ValueError('This finite probe requires a test period of 2–30 seconds.')
    # Only this in-memory diagnostic snapshot changes. No network transport is used.
    s.position_output = 'osc'
    s.validate_marker()
    preview = (f'REAL DIRECT OUTPUT — one {s.test_period:g}-second figure eight.\n'
               f'MArker {s.marker_id}; X {max(s.x_min, s.initial_x - s.test_size):g} to '
               f'{min(s.x_max, s.initial_x + s.test_size):g} m; '
               f'Y {max(s.y_min, s.initial_y - s.test_size / 2):g} to '
               f'{min(s.y_max, s.initial_y + s.test_size / 2):g} m; Z {s.z:g} m.\n'
               f'Optional brightness: {s.test_brightness:g}% on Page {s.executor_page} / '
               f'Executor {s.executor_number} (Master).\n'
               'No joystick, Python process, OSC or PSN at runtime.\n'
               'Stop the followspot app/PSN stream; disable OSC input for this test.\n'
               'Use a test show, Blind/Preview off and Program Time off.\n'
               'Select an unrelated fixture and encoder feature before running.\n'
               'Do not change selection or encoders during the cycle.\n'
               'The last XYZ and optional brightness remain in MA on Stop/completion.')
    fields = [f'marker_id={s.marker_id}', f'period={s.test_period!r}',
              f'page={s.executor_page}', f'executor={s.executor_number}',
              f'brightness={s.test_brightness!r}', 'preview=' + literal(preview),
              'attributes={' + ','.join(literal(getattr(s, f'attribute_{a}')) for a in 'xyz') + '}']
    rows = []
    for index in range(math.ceil(s.test_period * 30) + 1):
        at = min(index / 30, s.test_period)
        xyz = figure_eight(s, at)
        percent = []
        for axis, value in zip('xyz', xyz):
            lo, hi = getattr(s, f'space_{axis}_min'), getattr(s, f'space_{axis}_max')
            percent.append(clamp((value - lo) / (hi - lo) * 100, 0, 100))
        rows.append('{' + ','.join(format(v, '.12g') for v in (at, *xyz, *percent)) + '}')
    fields.append('frames={\n' + ',\n'.join(rows) + '\n}')
    source = (HERE / 'direct.lua').read_text(encoding='utf-8')
    source = source.replace('__CONFIG__', '{' + ',\n'.join(fields) + '}')
    document = ET.Element('GMA3', DataVersion='2.5.0.3')
    plugin = ET.SubElement(document, 'UserPlugin', Name='Followspot Direct Test',
                           Author='Joystick Followspot', Version='0.3.1.0')
    component = ET.SubElement(plugin, 'ComponentLua', Name='Finite native channel test',
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
    parser.add_argument('--output', type=Path, default=HERE / 'FollowspotDirectTest.xml')
    args = parser.parse_args()
    build(args.output, args.settings)
    print(f'Built {args.output} ({args.output.stat().st_size} bytes); settings were only read.')
