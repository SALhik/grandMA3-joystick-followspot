"""Execute both launchers' Python eligibility probes with controlled runtimes."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import builtins
import types


ROOT = Path(__file__).resolve().parents[1]


class LauncherProbeTests(unittest.TestCase):
    def probes(self):
        mac = (ROOT / 'Launch Followspot.command').read_text()
        windows = (ROOT / 'Launch Followspot.bat').read_text()
        return [re.search(r" -c '([^']+)'", mac).group(1),
                re.search(r' -c "([^"]+)"', windows).group(1)]

    def eligible(self, probe, version, tk):
        real_import = builtins.__import__
        def runtime_import(name, *args, **kwargs):
            if name == 'sys':
                return types.SimpleNamespace(version_info=version, exit=sys.exit)
            if name in ('tkinter', '_tkinter'):
                if not tk:
                    raise ImportError('Tk unavailable')
                return types.SimpleNamespace()
            return real_import(name, *args, **kwargs)
        try:
            with patch.object(builtins, '__import__', side_effect=runtime_import):
                exec(compile(ast.parse(probe), '<launcher probe>', 'exec'), {})
        except SystemExit as error:
            return error.code in (None, 0)
        except ImportError:
            return False
        return True

    def test_python_39_with_tk_is_rejected(self):
        for probe in self.probes():
            with self.subTest(probe=probe):
                self.assertFalse(self.eligible(probe, (3, 9, 20), True))

    def test_supported_python_with_tk_is_accepted(self):
        for probe in self.probes():
            for version in ((3, 10, 0), (3, 14, 0)):
                with self.subTest(probe=probe, version=version):
                    self.assertTrue(self.eligible(probe, version, True))

    def test_supported_python_without_tk_is_rejected(self):
        for probe in self.probes():
            with self.subTest(probe=probe):
                self.assertFalse(self.eligible(probe, (3, 12, 0), False))


@unittest.skipUnless(sys.platform == 'win32', 'Actual batch launcher requires Windows cmd.exe')
class WindowsLauncherTests(unittest.TestCase):
    def test_batch_uses_local_venv_and_forwards_arguments_and_sibling_sdl(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project with spaces'
            project.mkdir()
            launcher = project / 'Launch Followspot.bat'
            shutil.copyfile(ROOT / launcher.name, launcher)
            local_venv = project / '.venv'
            created = subprocess.run(
                [sys.executable, '-m', 'venv', '--without-pip', str(local_venv)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)

            # This script records launcher behavior; it imports no application code
            # and never loads the placeholder SDL DLL or creates a Tk window.
            (project / 'followspot.py').write_text(
                'import json, os, sys\n'
                'from pathlib import Path\n'
                'record = {"executable": sys.executable, "prefix": sys.prefix,\n'
                '          "argv": sys.argv[1:], "cwd": os.getcwd(),\n'
                '          "sdl": os.environ.get("FOLLOWSPOT_SDL2")}\n'
                'Path(__file__).with_name("launch-record.json").write_text(json.dumps(record))\n',
                encoding='utf-8')
            settings = project / 'operator settings.json'
            settings.write_text('{}', encoding='utf-8')
            sibling_sdl = project / 'SDL2.dll'
            sibling_sdl.write_bytes(b'Placeholder; the harmless script does not load SDL.')
            environment = os.environ.copy()
            environment.pop('FOLLOWSPOT_SDL2', None)

            # CALL keeps the quoted batch path and quoted argument intact when
            # cmd.exe processes /c; /d suppresses machine-specific AutoRun hooks.
            launched = subprocess.run(
                [environment.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'call',
                 str(launcher), '--settings', str(settings)],
                cwd=directory, env=environment, input='\n',
                capture_output=True, text=True, timeout=30)
            self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            record = json.loads((project / 'launch-record.json').read_text(encoding='utf-8'))
            self.assertTrue(Path(record['executable']).samefile(local_venv / 'Scripts' / 'python.exe'))
            self.assertTrue(Path(record['prefix']).samefile(local_venv))
            self.assertEqual(record['argv'], ['--settings', str(settings)])
            self.assertTrue(Path(record['cwd']).samefile(project))
            self.assertTrue(Path(record['sdl']).samefile(sibling_sdl))


if __name__ == '__main__':
    unittest.main()
