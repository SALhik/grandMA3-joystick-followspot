import math
import tempfile
import unittest
from pathlib import Path

import followspot_core as core


class CoreTests(unittest.TestCase):
    def settings(self, **changes):
        data = core.Settings().to_dict()
        data.update(changes)
        return core.Settings.from_dict(data)

    def test_deflection_sets_speed_and_centre_holds(self):
        s = self.settings(dead_zone=0.1, max_speed=1.0)
        slow = core.Motion(s)
        fast = core.Motion(s)
        slow.step([0.55, 0, -1], 0.1)
        fast.step([1, 0, -1], 0.1)
        self.assertAlmostEqual(slow.xyz[0], 0.05)
        self.assertAlmostEqual(fast.xyz[0], 0.1)
        slow.step([0.05, 0, -1], 0.1)
        self.assertAlmostEqual(slow.xyz[0], 0.05)

    def test_diagonal_speed_is_capped(self):
        m = core.Motion(self.settings(dead_zone=0, invert_y=False))
        m.step([1, 1, -1], 0.1)
        self.assertAlmostEqual(math.hypot(*m.xyz[:2]), 0.1)

    def test_centre_calibration_and_inversion(self):
        m = core.Motion(self.settings(centre_x=0.2, invert_x=True))
        m.step([0.2, 0, -1], 0.1)
        self.assertEqual(m.xyz[0], 0)
        m.step([1, 0, -1], 0.1)
        self.assertAlmostEqual(m.xyz[0], -0.1)

    def test_stall_and_limits(self):
        m = core.Motion(self.settings(initial_x=0.99, x_max=1))
        m.step([1, 0, -1], 0.1)
        self.assertEqual(m.xyz[0], 1)
        m.step([-1, 0, -1], 2)
        self.assertEqual(m.xyz[0], 1)

    def test_slider_endpoints_and_inversion(self):
        m = core.Motion(self.settings())
        self.assertEqual(m.brightness([0, 0, -1]), 0)
        self.assertEqual(m.brightness([0, 0, 1]), 100)
        m = core.Motion(self.settings(invert_slider=True))
        self.assertEqual(m.brightness([0, 0, -1]), 100)

    def test_invalid_settings_rejected(self):
        for changes in [{"max_speed": float("nan")}, {"dead_zone": 1},
                        {"x_min": 10}, {"marker_id": 0}, {"port": 70000},
                        {"axis_x": 1}, {"buttons": {"0": {"press": "bad\0"}}},
                        {"invert_x": "false"}, {"initial_x": float("inf")},
                        {"x_min": -500}]:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.settings(**changes)

    def test_settings_roundtrip_and_failed_save_preserves_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            s = self.settings(buttons={"0": {"press": "Go+ Sequence 1", "release": ""}})
            s.save(path)
            self.assertEqual(core.Settings.load(path).to_dict(), s.to_dict())
            s.max_speed = float("nan")
            with self.assertRaises(ValueError):
                s.save(path)
            self.assertEqual(core.Settings.load(path).max_speed, 1)

    def test_marker_uses_space_bounds_and_explicit_percent(self):
        s = self.settings(marker_id=7, space_x_min=-10, space_x_max=10)
        commands = core.marker_commands(s, (2, 0, 1.5))
        self.assertEqual(commands[0], 'MArker 7 Attribute "XYZ_X" At Absolute Percent 60.000000')

    def test_osc_encoding_against_literal_packet(self):
        self.assertEqual(core.osc_packet('/cmd', 'Go'),
                         b'/cmd\0\0\0\0,s\0\0Go\0\0')
        self.assertEqual(core.osc_packet('/x', 50.0),
                         b'/x\0\0,f\0\0\x42\x48\x00\x00')

    def test_axis_learning_ignores_small_noise(self):
        self.assertIsNone(core.learn_axis([0, 0, -1], [0.05, 0.01, -1]))
        self.assertEqual(core.learn_axis([0, 0, -1], [0.02, 0.7, -1]), 1)

    def test_buttons_emit_edges_and_stop_releases(self):
        emitted = []
        s = self.settings(buttons={"0": {"press": "Flash On Executor 201", "release": "Flash Off Executor 201"}})
        c = core.Controller(s, lambda address, value: emitted.append((address, value)))
        c.start([0, 0, -1], [False])
        emitted.clear()
        c.tick([0, 0, -1], [True], 0.03)
        c.tick([0, 0, -1], [True], 0.03)
        self.assertEqual(emitted, [('/cmd', 'Flash On Executor 201')])
        c.stop()
        self.assertEqual(emitted[-1], ('/cmd', 'Flash Off Executor 201'))
        c.tick([1, 0, 1], [False], 0.03)
        self.assertFalse(c.active)
        self.assertEqual(len(emitted), 2)

    def test_held_button_at_start_does_not_press_or_release(self):
        emitted = []
        s = self.settings(buttons={"0": {"press": "Go+ Sequence 1", "release": "Off Sequence 1"}})
        c = core.Controller(s, lambda a, v: emitted.append((a, v)))
        c.start([0, 0, -1], [True])
        emitted.clear()
        c.tick([0, 0, -1], [False], 0.03)
        c.stop()
        self.assertEqual(emitted, [])

    def test_failure_disables_output_and_attempts_releases(self):
        emitted = []
        def send(a, v):
            if a.endswith('Fader201') and v == 100:
                raise OSError('transport failure')
            emitted.append((a, v))
        s = self.settings(buttons={"0": {"press": "Down", "release": "Up"}})
        c = core.Controller(s, send)
        c.start([0, 0, -1], [False])
        c.tick([0, 0, -1], [True], 0.03)
        with self.assertRaises(OSError):
            c.tick([0, 0, 1], [True], 0.03)
        self.assertFalse(c.active)
        self.assertIn(('/cmd', 'Up'), emitted)


if __name__ == '__main__':
    unittest.main()
