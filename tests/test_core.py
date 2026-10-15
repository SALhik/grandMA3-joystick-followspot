import json
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


class ZoomTests(unittest.TestCase):
    def settings(self, **changes):
        return core.Settings.from_dict(dict(core.Settings().to_dict(), zoom_enabled=True, **changes))

    def test_old_settings_need_no_fourth_axis_or_extra_output(self):
        s = core.Settings.from_dict({'axis_slider': 3})
        self.assertFalse(s.zoom_enabled)
        emitted = []
        c = core.Controller(s, lambda a, v: emitted.append((a, v)))
        c.start([0, 0, 0, -1])
        c.tick([0, 0, 0, -1], 0.1)
        self.assertEqual(len(emitted), 2)

    def test_deflection_controls_zoom_speed_and_centre_holds(self):
        m = core.Motion(self.settings())
        m.step([0, 0, -1, 0.55], 0.2)
        self.assertAlmostEqual(m.zoom_level, 55)
        m.step([0, 0, -1, 0.05], 0.2)
        self.assertAlmostEqual(m.zoom_level, 55)
        m.step([0, 0, -1, -1], 0.2)
        self.assertAlmostEqual(m.zoom_level, 45)

    def test_zoom_calibration_inversion_limits_and_capped_gap(self):
        m = core.Motion(self.settings(centre_zoom=0.2, invert_zoom=True, initial_zoom=5))
        m.step([0, 0, -1, 0.2], 0.1)
        self.assertEqual(m.zoom_level, 5)
        m.step([0, 0, -1, 1], 0.2)
        self.assertEqual(m.zoom_level, 0)
        m.step([0, 0, -1, -1], 10)
        self.assertAlmostEqual(m.zoom_level, 12.5)
        m.zoom_level = 99
        m.step([0, 0, -1, -1], 0.2)
        self.assertEqual(m.zoom_level, 100)

    def test_zoom_configuration_validation_and_roundtrip(self):
        for changes in ({'axis_zoom': 2}, {'axis_zoom': -1}, {'centre_zoom': 1},
                        {'zoom_dead_zone': 0.9}, {'zoom_dead_zone': -0.1},
                        {'zoom_speed': 0}, {'zoom_speed': float('nan')},
                        {'initial_zoom': 101}, {'initial_zoom': -1},
                        {'zoom_executor_page': 0}, {'zoom_executor_number': 0},
                        {'zoom_executor_number': 201}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.settings(**changes)
        s = self.settings(axis_zoom=4, initial_zoom=20, zoom_executor_page=2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            s.save(path)
            self.assertEqual(core.Settings.load(path).to_dict(), s.to_dict())
        c = core.Controller(s, lambda *args: None)
        with self.assertRaisesRegex(ValueError, 'axis range'):
            c.start([0, 0, 0, 0])
        self.assertFalse(c.active)

    def test_zoom_sends_tracked_level_suppresses_idle_and_retains_on_restart(self):
        emitted = []
        c = core.Controller(self.settings(zoom_executor_page=2, zoom_executor_number=205),
                            lambda a, v: emitted.append((a, v)))
        c.start([0, 0, -1, 1])
        self.assertEqual(emitted[-1], ('/Page2/Fader205', 50))
        emitted.clear()
        c.tick([0, 0, -1, 1], 0.1)
        c.tick([0, 0, -1, 0], 0.1)
        self.assertEqual(emitted, [('/Page2/Fader205', 55)])
        c.stop()
        c.tick([0, 0, -1, 1], 0.1)
        c.start([0, 0, -1, 0])
        self.assertEqual(emitted[-1], ('/Page2/Fader205', 55))

    def test_reset_restores_zoom_locally_and_live_obeying_lock(self):
        emitted = []
        c = core.Controller(self.settings(initial_zoom=30), lambda a, v: emitted.append((a, v)))
        c.motion.zoom_level = 70
        self.assertTrue(c.reset_target())
        self.assertEqual(c.motion.zoom_level, 30)
        self.assertEqual(emitted, [])
        c.start([0, 0, -1, 0])
        c.motion.zoom_level = 70
        emitted.clear()
        self.assertFalse(c.reset_target())
        self.assertEqual(c.motion.zoom_level, 70)
        self.assertEqual(emitted, [])
        c.settings.reset_locked = False
        self.assertTrue(c.reset_target())
        self.assertEqual(c.motion.zoom_level, 30)
        self.assertEqual([a for a, v in emitted], ['/cmd', '/Page1/Fader202'])
        self.assertEqual(emitted[-1][1], 30)
        self.assertTrue(c.active)
        emitted.clear()
        c.reset_target()  # Explicit Reset resends even an unchanged level.
        self.assertEqual(emitted[-1], ('/Page1/Fader202', 30))

    def test_zoom_send_failure_stops_and_releases_buttons(self):
        emitted = []
        def send(a, v):
            if a == '/Page1/Fader202' and v != 50:
                raise OSError('zoom send failed')
            emitted.append((a, v))
        c = core.Controller(self.settings(buttons={'0': {'press': 'Down', 'release': 'Up'}}), send)
        c.start([0, 0, -1, 0])
        c.tick([0, 0, -1, 0], 0.1, presses=[0])
        with self.assertRaisesRegex(OSError, 'zoom send failed'):
            c.tick([0, 0, -1, 1], 0.1)
        self.assertFalse(c.active)
        self.assertEqual(emitted[-1], ('/cmd', 'Up'))


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

    def test_figure_eight_is_centred_closed_and_inside_limits(self):
        s = self.settings(initial_x=1, initial_y=-1, test_size=2, test_period=10, x_max=2)
        self.assertEqual(core.figure_eight(s, 0), [1, -1, s.z])
        self.assertAlmostEqual(core.figure_eight(s, 10)[1], -1)
        points = [core.figure_eight(s, t / 10) for t in range(100)]
        self.assertTrue(all(p[0] <= 2 for p in points))
        self.assertGreater(max(p[1] for p in points), -1)
        self.assertLess(min(p[1] for p in points), -1)

    def test_test_mode_runs_without_axes_and_holds_test_brightness(self):
        sent = []
        c = core.Controller(self.settings(test_brightness=60, test_period=10),
                            lambda address, value: sent.append((address, value)))
        c.start(test=True)
        self.assertEqual(sent[-1], ('/Page1/Fader201', 60.0))
        self.assertEqual(c.motion.xyz[:2], [0, 0])
        c.tick((), core.MAX_STEP)
        self.assertNotEqual(c.motion.xyz[:2], [0, 0])
        self.assertTrue(any(a == '/cmd' for a, _ in sent[2:]))
        self.assertEqual(sum(1 for a, _ in sent if a.startswith('/Page')), 1)

    def test_test_settings_are_validated_and_old_files_still_load(self):
        for bad in ({'test_size': 0}, {'test_period': 1}, {'test_brightness': 101}):
            with self.assertRaises(ValueError):
                self.settings(**bad)
        legacy = {k: v for k, v in core.Settings().to_dict().items() if not k.startswith('test_')}
        self.assertEqual(core.Settings.from_dict(legacy).test_period, 20.0)

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
        data = core.Settings().to_dict()
        del data['reset_locked']
        data['buttons'] = {'0': {'press': 'Go+ Sequence 1', 'release': ''}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            s = core.Settings.load(path)
        self.assertIs(s.reset_locked, True)
        self.assertEqual(core.button_action(s.buttons, 0), 'command')

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


class PsnSettingsTests(unittest.TestCase):
    def test_old_settings_default_to_osc_position_output(self):
        s = core.Settings.from_dict({'port': 8001})
        self.assertEqual((s.position_output, s.psn_tracker_id, s.psn_group, s.psn_port, s.psn_interface),
                         ('osc', 1, '236.10.10.10', 56565, '127.0.0.1'))

    def test_example_file_equals_defaults(self):
        example = core.Settings.load(Path(__file__).resolve().parent.parent / 'settings.example.json')
        self.assertEqual(example.to_dict(), core.Settings().to_dict())

    def test_invalid_psn_values_name_their_field(self):
        cases = (({'position_output': 'sacn'}, 'position_output'),
                 ({'psn_tracker_id': 0}, 'psn_tracker_id'),
                 ({'psn_tracker_id': 65536}, 'psn_tracker_id'),
                 ({'psn_port': 0}, 'psn_port'),
                 ({'psn_port': 70000}, 'psn_port'),
                 ({'psn_group': '10.0.0.5'}, 'psn_group'),
                 ({'psn_group': 'not-an-ip'}, 'psn_group'),
                 ({'psn_interface': 'localhost'}, 'psn_interface'),
                 ({'psn_interface': '::1'}, 'psn_interface'))
        for changes, field in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(core.SettingsError) as caught:
                    core.Settings.from_dict(dict(core.Settings().to_dict(), **changes))
                self.assertIn(field, caught.exception.fields)

    def test_release_marker_is_a_local_action_without_ma_commands(self):
        s = core.Settings.from_dict(dict(core.Settings().to_dict(), buttons={'4': {'action': 'release_marker'}}))
        self.assertEqual(core.local_actions([4], s.buttons), ['release_marker'])
        with self.assertRaises(core.SettingsError):
            core.Settings.from_dict(dict(core.Settings().to_dict(),
                                         buttons={'4': {'action': 'release_marker', 'press': 'Go+'}}))


class PsnControllerTests(unittest.TestCase):
    def psn(self, **changes):
        settings = core.Settings.from_dict(dict(core.Settings().to_dict(), position_output='psn', **changes))
        sent, positions = [], []
        controller = core.Controller(settings, lambda a, v: sent.append((a, v)), positions.append)
        return controller, sent, positions

    def test_psn_mode_requires_a_position_callback(self):
        settings = core.Settings.from_dict(dict(core.Settings().to_dict(), position_output='psn'))
        with self.assertRaises(ValueError):
            core.Controller(settings, lambda a, v: None)

    def test_psn_mode_sends_positions_not_marker_commands(self):
        controller, sent, positions = self.psn()
        controller.start([0, 0, -1])
        controller.tick([1, 0, -1], 0.1)
        self.assertEqual(positions[0], (0.0, 0.0, 1.5))
        self.assertGreater(positions[-1][0], 0.0)
        self.assertFalse([a for a, _ in sent if a == '/cmd'])

    def test_psn_mode_keeps_brightness_zoom_and_button_commands_on_osc(self):
        controller, sent, _ = self.psn(zoom_enabled=True, buttons={'0': {'press': 'Go+ Sequence 10', 'release': 'Off'}})
        edges = core.ButtonEdges()
        edges.seed([False])
        controller.start([0, 0, -1, 0])
        presses, releases = edges.sample([True])
        controller.tick([0, 0, -1, 0], 0.03, presses, releases)
        self.assertIn(('/Page1/Fader201', 0.0), sent)
        self.assertIn(('/Page1/Fader202', 50.0), sent)
        self.assertIn(('/cmd', 'Go+ Sequence 10'), sent)

    def test_psn_mode_resends_position_every_tick_even_when_idle(self):
        controller, _, positions = self.psn()
        controller.start([0, 0, -1])
        controller.tick([0, 0, -1], 0.03)
        controller.tick([0, 0, -1], 0.03)
        self.assertEqual(len(positions), 3)

    def test_live_reset_in_psn_mode_sends_the_initial_position(self):
        controller, _, positions = self.psn(reset_locked=False, initial_x=1.0)
        controller.start([0, 0, -1])
        controller.motion.xyz = [5.0, 5.0, 1.5]
        controller.reset_target()
        self.assertEqual(positions[-1], (1.0, 0.0, 1.5))

    def test_osc_mode_is_unchanged(self):
        sent = []
        controller = core.Controller(core.Settings(), lambda a, v: sent.append((a, v)))
        controller.start([0, 0, -1])
        self.assertTrue(sent[0][1].startswith('ClearSelection; MArker 1;'))


class PanTiltSettingsTests(unittest.TestCase):
    def test_old_settings_default_to_marker_control(self):
        s = core.Settings.from_dict({'port': 8001})
        self.assertEqual((s.control_mode, s.fixture_group, s.attribute_pan, s.attribute_tilt),
                         ('marker', 1, 'Pan', 'Tilt'))
        self.assertEqual((s.pan_tilt_speed, s.pan_min, s.pan_max, s.tilt_min, s.tilt_max),
                         (25.0, 0.0, 100.0, 0.0, 100.0))
        self.assertEqual((s.initial_pan, s.initial_tilt, s.test_pan_tilt_size), (50.0, 50.0, 10.0))

    def test_invalid_pan_tilt_values_name_their_field(self):
        cases = (({'control_mode': 'zoom'}, 'control_mode'),
                 ({'fixture_group': 0}, 'fixture_group'),
                 ({'fixture_group': 1.5}, 'fixture_group'),
                 ({'attribute_pan': 'Pan Tilt'}, 'attribute_pan'),
                 ({'attribute_tilt': ''}, 'attribute_tilt'),
                 ({'pan_tilt_speed': 0}, 'pan_tilt_speed'),
                 ({'pan_tilt_speed': 1001}, 'pan_tilt_speed'),
                 ({'pan_min': -1}, 'pan_min'),
                 ({'pan_max': 101}, 'pan_max'),
                 ({'pan_min': 60, 'pan_max': 60}, 'pan_min'),
                 ({'pan_min': 60}, 'initial_pan'),
                 ({'tilt_max': 40}, 'initial_tilt'),
                 ({'test_pan_tilt_size': 0}, 'test_pan_tilt_size'),
                 ({'test_pan_tilt_size': 51}, 'test_pan_tilt_size'))
        for changes, field in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(core.SettingsError) as caught:
                    core.Settings.from_dict(dict(core.Settings().to_dict(), **changes))
                self.assertIn(field, caught.exception.fields)

    def test_pan_tilt_values_are_validated_even_in_marker_mode(self):
        with self.assertRaises(core.SettingsError):
            core.Settings.from_dict(dict(core.Settings().to_dict(), control_mode='marker', pan_min=60))

    def test_pan_tilt_settings_roundtrip(self):
        s = core.Settings.from_dict(dict(core.Settings().to_dict(), control_mode='pan_tilt', fixture_group=4,
                                         attribute_pan='Pan2', pan_min=10, pan_max=90, initial_pan=20))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            s.save(path)
            self.assertEqual(core.Settings.load(path).to_dict(), s.to_dict())

    def test_control_mode_is_guarded_while_a_psn_stream_is_held(self):
        self.assertIn('control_mode', core.PSN_FIELDS)


if __name__ == '__main__':
    unittest.main()
