"""Build the experimental single-file MA plugin; no app or MA state is touched."""
import argparse
import base64
from pathlib import Path
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent


def build(destination):
    helper = (HERE / 'emulator.py').read_text(encoding='utf-8')
    equals = '===='
    while ']' + equals + ']' in helper:
        equals += '='
    literal = '[' + equals + '[' + helper + ']' + equals + ']'
    lua = (HERE / 'diagnostic.lua').read_text(encoding='utf-8')
    lua = lua.replace('__EMULATOR_SOURCE__', literal).encode('utf-8')
    document = ET.Element('GMA3', DataVersion='2.5.0.3')
    plugin = ET.SubElement(document, 'UserPlugin', Name='Followspot Diagnostic',
                           Author='Joystick Followspot', Version='0.1.0.0')
    component = ET.SubElement(plugin, 'ComponentLua', Name='Synthetic input diagnostic',
                              InStream='Yes', Installed='No')
    blocks = [lua[index:index + 1024] for index in range(0, len(lua), 1024)]
    content = ET.SubElement(component, 'FileContent', Size=str(len(blocks)))
    for block in blocks:
        ET.SubElement(content, 'Block', Base64=base64.b64encode(block).decode('ascii'))
    ET.indent(document)
    ET.ElementTree(document).write(destination, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE / 'FollowspotDiagnostic.xml')
    args = parser.parse_args()
    build(args.output)
    print(f'Built {args.output} ({args.output.stat().st_size} bytes)')
