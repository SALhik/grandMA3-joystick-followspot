import math
import tempfile
import unittest
from pathlib import Path

import followspot_core as core


class Rig(core.Controller):
    """Drive the controller from raw button snapshots, as the window does."""
    def __init__(self, settings, send):
        super().__init__(settings, send)
        self.edges = core.ButtonEdges()

    def start(self, axes, buttons):
        self.edges.seed(buttons)
        super().start(axes)

    def tick(self, axes, buttons, dt):
        presses, releases = self.edges.sample(buttons)
        super().tick(axes, dt, presses, releases)


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

    def test_long_gap_moves_at_most_one_capped_step_and_limits_hold(self):
        m = core.Motion(self.settings(initial_x=0.99, x_max=1))
        m.step([1, 0, -1], 0.1)
        self.assertEqual(m.xyz[0], 1)
        # A throttled or stalled poll keeps moving, but never jumps by the whole gap.
        m.step([-1, 0, -1], 2)
        self.assertAlmostEqual(m.xyz[0], 1 - core.MAX_STEP)

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

    def test_marker_selects_before_setting_space_percent_attributes(self):
        s = self.settings(marker_id=7, space_x_min=-10, space_x_max=10)
        commands = core.marker_commands(s, (2, 0, 1.5))
        # Selection and attribute assignment are separate MA commands. Clear only
        # selection so values are not applied to other fixtures in the programmer.
        self.assertEqual(commands, [
            'ClearSelection',
            'MArker 7',
            'Attribute "XYZ_X" At Absolute Percent 60.000000',
            'Attribute "XYZ_Y" At Absolute Percent 50.000000',
            'Attribute "XYZ_Z" At Absolute Percent 50.750000',
        ])

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
        c = Rig(s, lambda address, value: emitted.append((address, value)))
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
        c = Rig(s, lambda a, v: emitted.append((a, v)))
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
        c = Rig(s, send)
        c.start([0, 0, -1], [False])
        c.tick([0, 0, -1], [True], 0.03)
        with self.assertRaises(OSError):
            c.tick([0, 0, 1], [True], 0.03)
        self.assertFalse(c.active)
        self.assertIn(('/cmd', 'Up'), emitted)

    def test_release_only_mapping_fires_after_a_press(self):
        emitted = []
        s = self.settings(buttons={'0': {'press': '', 'release': 'Go+ Sequence 1'}})
        c = Rig(s, lambda a, v: emitted.append((a, v)))
        c.start([0, 0, -1], [False])
        emitted.clear()
        c.tick([0, 0, -1], [True], 0.03)
        c.tick([0, 0, -1], [False], 0.03)
        self.assertEqual(emitted, [('/cmd', 'Go+ Sequence 1')])

    def test_transport_error_reports_failed_cleanup_release(self):
        def send(a, v):
            if a.endswith('Fader201') and v == 100:
                raise OSError('fader transmission failed')
            if v == 'Up':
                raise OSError('release transmission failed')
        c = Rig(self.settings(buttons={'0': {'press': 'Down', 'release': 'Up'}}), send)
        c.start([0, 0, -1], [False])
        c.tick([0, 0, -1], [True], 0.03)
        with self.assertRaisesRegex(RuntimeError, 'Release send failed: release transmission failed'):
            c.tick([0, 0, 1], [True], 0.03)
        self.assertFalse(c.active)

    def test_old_settings_keep_reset_locked_and_accept_command_mappings(self):
        s = self.settings(buttons={'0': {'press': 'Go+ Sequence 1'}})
        self.assertTrue(getattr(s, 'reset_locked', False))

    def test_local_action_settings_roundtrip_and_validation(self):
        s = self.settings(reset_locked=False, buttons={'0': {'action': 'toggle'}})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            s.save(path)
            self.assertEqual(core.Settings.load(path).to_dict(), s.to_dict())
        for mapping in ({'action': 'unknown'}, {'action': []},
                        {'action': 'stop', 'press': 'Go'},
                        {'action': 'reset', 'release': 'Off'}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                self.settings(buttons={'0': mapping})

    def test_reset_while_stopped_is_local(self):
        emitted = []
        c = Rig(self.settings(initial_x=2, initial_y=-3),
                            lambda a, v: emitted.append((a, v)))
        c.motion.xyz = [5, 6, 1.5]
        self.assertTrue(c.reset_target())
        self.assertEqual(c.motion.xyz, [2, -3, 1.5])
        self.assertEqual(emitted, [])

    def test_live_reset_obeys_lock_and_only_sends_position(self):
        emitted = []
        c = Rig(self.settings(initial_x=2),
                            lambda a, v: emitted.append((a, v)))
        c.start([0, 0, 0], [False])
        c.motion.xyz = [5, 6, 1.5]
        emitted.clear()
        self.assertFalse(c.reset_target())
        self.assertEqual(c.motion.xyz, [5, 6, 1.5])
        self.assertEqual(emitted, [])
        c.settings.reset_locked = False
        self.assertTrue(c.reset_target())
        self.assertTrue(c.active)
        self.assertEqual(c.motion.xyz, [2, 0, 1.5])
        self.assertEqual(emitted, [('/cmd', 'ClearSelection; MArker 1; '
                         'Attribute "XYZ_X" At Absolute Percent 51.000000; '
                         'Attribute "XYZ_Y" At Absolute Percent 50.000000; '
                         'Attribute "XYZ_Z" At Absolute Percent 50.750000')])
        self.assertEqual(c.last_brightness, 50)

    def test_live_reset_send_failure_stops_and_releases(self):
        emitted = []
        def send(a, v):
            if v.startswith('ClearSelection') and fail[0]:
                raise OSError('reset failed')
            emitted.append((a, v))
        fail = [False]
        c = Rig(self.settings(reset_locked=False,
                            buttons={'0': {'press': 'Down', 'release': 'Up'}}),
                            lambda a, v: send(a, v) if isinstance(v, str) else None)
        c.start([0, 0, -1], [False])
        c.tick([0, 0, -1], [True], 0.03)
        fail[0] = True
        with self.assertRaisesRegex(OSError, 'reset failed'):
            c.reset_target()
        self.assertFalse(c.active)
        self.assertEqual(emitted[-1], ('/cmd', 'Up'))

    def test_local_buttons_ignore_held_inputs_and_learning(self):
        edges = core.ButtonEdges()
        mappings = {'0': {'action': 'start'}}
        def actions(buttons):
            return core.local_actions(edges.sample(buttons)[0], mappings)
        self.assertEqual(actions([True]), [])
        self.assertEqual(actions([False]), [])
        edges.seed([True])  # A learning sample is observed without acting.
        self.assertEqual(actions([True]), [])
        self.assertEqual(actions([False]), [])
        self.assertEqual(actions([True]), ['start'])
        self.assertEqual(actions([True]), [])
        self.assertEqual(actions([False, True]), [])

    def test_ma_commands_keep_button_order_within_a_sample(self):
        emitted = []
        c = Rig(self.settings(buttons={'0': {'press': 'On 0', 'release': 'Off 0'},
                                       '1': {'press': 'On 1', 'release': 'Off 1'}}),
                lambda a, v: emitted.append(v))
        c.start([0, 0, -1], [False, False])
        c.tick([0, 0, -1], [True, False], 0.03)
        emitted.clear()
        c.tick([0, 0, -1], [False, True], 0.03)
        self.assertEqual(emitted, ['Off 0', 'On 1'])

    def test_local_buttons_do_not_emit_ma_commands(self):
        emitted = []
        c = Rig(self.settings(buttons={'0': {'action': 'stop'}}),
                            lambda a, v: emitted.append((a, v)))
        c.start([0, 0, -1], [False])
        emitted.clear()
        c.tick([0, 0, -1], [True], 0.03)
        c.stop()
        self.assertEqual(emitted, [])


if __name__ == '__main__':
    unittest.main()
