"""Window behaviour tested without requiring macOS WindowServer access."""
import unittest
import tempfile
import time
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import followspot
from followspot_core import ButtonEdges, Controller, Settings


class Value:
    def __init__(self, value=''):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Widget:
    def __init__(self):
        self.state = 'normal'
    def configure(self, **options):
        self.state = options.get('state', self.state)


class Sender:
    def __init__(self, messages):
        self.messages = messages
        self.closed = False
        self.fail = False
    def send(self, address, value):
        if self.fail:
            raise OSError('send failed')
        self.messages.append((address, value))
    def close(self):
        self.closed = True


class FakeStreamer:
    def __init__(self, settings, xyz):
        self.positions = [tuple(xyz)]
        self.closed = False
        self.error = None

    @property
    def position(self):
        return self.positions[-1]

    def set_position(self, xyz):
        self.positions.append(tuple(xyz))

    def poll_error(self):
        error, self.error = self.error, None
        return error

    def close(self):
        self.closed = True


class WindowTests(unittest.TestCase):
    def app(self, **changes):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        app = followspot.App.__new__(followspot.App)
        app.settings_path = Path(folder.name) / 'settings.json'
        app.settings = Settings.from_dict(dict(Settings().to_dict(), **changes))
        app.settings.save(app.settings_path)
        app.values = {key: Value(followspot.display_value(key, value)) for key, value in app.settings.to_dict().items() if key != 'buttons'}
        app.draft_buttons = dict(app.settings.buttons)
        app.axes, app.buttons = [0, 0, 0], [False] * 3
        app.button_edges = ButtonEdges()
        app.button_edges.seed(app.buttons)
        app.sender = None
        app.streamer = None
        messages = []
        app.controller = Controller(app.settings, app.send, app.send_position)
        for name in ('status', 'output_label', 'position_label', 'brightness_label', 'zoom_label',
                     'axes_label', 'buttons_label', 'device_label', 'button_id',
                     'press_command', 'release_command', 'fault_label'):
            setattr(app, name, Value())
        app.button_action = Value('MA command')
        app.faults = {}
        for name in ('start_button', 'test_button', 'reset_button', 'save_button', 'press_entry', 'release_entry'):
            setattr(app, name, Widget())
        app.setting_tabs = ['controls', 'target', 'network', 'mappings']
        app.notebook = SimpleNamespace(tab=lambda *args, **kwargs: None, select=lambda *args: None)
        app.button_table = SimpleNamespace(delete=lambda *args: None, get_children=lambda: (),
                                           insert=lambda *args, **kwargs: None,
                                           selection=lambda: ('0',))
        app.joystick = SimpleNamespace(handle=True, read=lambda: (list(app.axes), list(app.buttons)))
        app.joystick.close = lambda: setattr(app.joystick, 'handle', False)
        app.learning = None
        app.last_tick = time.monotonic()
        app.last_ui = 0
        app.root = SimpleNamespace(after=lambda *args: None)
        def set_running(running):
            for name in ('start_button', 'test_button', 'save_button'):
                getattr(app, name).configure(state='disabled' if running else 'normal')
            app.reset_button.configure(state='disabled' if running and app.settings.reset_locked else 'normal')
        app.view = SimpleNamespace(refresh=lambda: None, set_running=set_running,
                                   show_error=lambda exc: None, clear_errors=lambda: None,
                                   mapping_pending=lambda: False, editor_loaded=lambda: None,
                                   set_feedback=lambda *args: None, restore_selection=lambda: None)
        app.errors = []
        app.confirm = True
        app.messagebox = SimpleNamespace(showerror=lambda *args: app.errors.append(args),
                                         askokcancel=lambda *args: app.confirm)
        def new_sender(*args):
            self.sender = Sender(messages)
            return self.sender
        sender_patch = patch.object(followspot, 'OscSender', side_effect=new_sender)
        sender_patch.start()
        self.addCleanup(sender_patch.stop)
        self.streamers = []
        def new_streamer(settings, xyz):
            streamer = FakeStreamer(settings, xyz)
            self.streamers.append(streamer)
            return streamer
        streamer_patch = patch.object(followspot, 'PsnStreamer', side_effect=new_streamer)
        streamer_patch.start()
        self.addCleanup(streamer_patch.stop)
        return app, messages

    def test_zoom_level_survives_apply_stop_and_restart(self):
        app, messages = self.app(zoom_enabled=True)
        app.axes.append(0)
        app.controller.motion.zoom_level = 65
        app.values['initial_zoom'].set('20')
        app.start_output()
        self.assertTrue(app.controller.active)
        self.assertEqual(messages[-1], ('/Page1/Fader202', 65))
        app.stop_output()
        app.apply_settings()
        app.start_output()
        self.assertEqual(messages[-1], ('/Page1/Fader202', 65))
        self.assertIn('65.0%', app.zoom_label.get())

    def test_zoom_centre_calibration_uses_selected_axis(self):
        app, _ = self.app(zoom_enabled=True)
        app.axes.append(0.15)
        app.calibrate_zoom()
        self.assertAlmostEqual(float(app.values['centre_zoom'].get()), 0.15)
        app.values['axis_zoom'].set('8')
        app.calibrate_zoom()
        self.assertAlmostEqual(float(app.values['centre_zoom'].get()), 0.15)
        self.assertIn('valid', app.status.get())

    def test_zoom_axis_learning_does_not_change_tracked_level(self):
        app, messages = self.app(zoom_enabled=True)
        app.axes.append(0)
        app.begin_learn('axis_zoom')
        app.axes[3] = 0.7
        app.poll()
        self.assertEqual(app.values['axis_zoom'].get(), '3')
        self.assertIsNone(app.learning)
        self.assertEqual(app.controller.motion.zoom_level, 50)
        self.assertEqual(messages, [])

    def test_mapped_live_reset_resets_zoom_without_moving_in_same_sample(self):
        app, messages = self.app(zoom_enabled=True, initial_zoom=25, reset_locked=False,
                                 buttons={'0': {'action': 'reset'}})
        app.axes.append(0)
        app.start_output()
        app.controller.motion.zoom_level = 80
        app.values['initial_zoom'].set('90')
        app.axes[3] = 1
        app.buttons[0] = True
        app.process_input(0.1)
        self.assertEqual(app.controller.motion.zoom_level, 25)
        self.assertEqual(messages[-1], ('/Page1/Fader202', 25))
        self.assertIn('25.0%', app.zoom_label.get())
        app.process_input(0.1)
        self.assertEqual(messages[-1], ('/Page1/Fader202', 30))

    def test_window_stopped_reset_applies_zoom_initial_draft(self):
        app, messages = self.app(zoom_enabled=True)
        app.axes.append(0)
        app.controller.motion.zoom_level = 80
        app.values['initial_zoom'].set('35')
        app.reset_target()
        self.assertEqual(app.controller.motion.zoom_level, 35)
        self.assertEqual(Settings.load(app.settings_path).initial_zoom, 35)
        self.assertEqual(messages, [])

    def test_zoom_failure_during_live_reset_keeps_device_and_closes_sender(self):
        app, messages = self.app(zoom_enabled=True, reset_locked=False,
                                 buttons={'0': {'press': 'Down', 'release': 'Up'}})
        app.axes.append(0)
        app.start_output()
        app.buttons[0] = True
        app.process_input(0.1)
        def fail_zoom(a, v):
            if a == '/Page1/Fader202':
                raise OSError('zoom failed')
            messages.append((a, v))
        self.sender.send = fail_zoom
        app.reset_target()
        self.assertFalse(app.controller.active)
        self.assertEqual(messages[-1], ('/cmd', 'Up'))
        self.assertTrue(app.joystick.handle)
        self.assertTrue(self.sender.closed)
        self.assertIn('zoom failed', app.status.get())

    def test_settings_parse_rejects_invalid_numeric_input(self):
        s = Settings()
        values = {key: Value(value) for key, value in s.to_dict().items() if key != 'buttons'}
        values['axis_x'].set('not a number')
        with self.assertRaises(ValueError):
            followspot.settings_from_values(values, {})
        values['axis_x'].set('0')
        self.assertEqual(followspot.settings_from_values(values, {}).axis_x, 0)

    def test_dead_zone_percentages_are_saved_as_fractions(self):
        app, _ = self.app()
        app.values['dead_zone'].set('12.5')
        app.values['zoom_dead_zone'].set('20')
        self.assertTrue(app.apply_settings())
        saved = Settings.load(app.settings_path)
        self.assertEqual((saved.dead_zone, saved.zoom_dead_zone), (0.125, 0.2))

    def test_opening_and_saving_preserves_dead_zone_precision(self):
        app, _ = self.app(dead_zone=0.123456789, zoom_dead_zone=0.234567891)
        self.assertTrue(app.apply_settings())
        saved = Settings.load(app.settings_path)
        self.assertEqual((saved.dead_zone, saved.zoom_dead_zone), (0.123456789, 0.234567891))

    def test_oversized_percentage_reports_a_field_error(self):
        app, _ = self.app()
        app.values['dead_zone'].set('1e100000000')
        with self.assertRaises(ValueError) as error:
            followspot.settings_from_values(app.values, {})
        self.assertIn('dead_zone', error.exception.fields)

    def test_invalid_field_identifies_the_setting_without_saving(self):
        app, _ = self.app()
        app.values['port'].set('70000')
        try:
            followspot.settings_from_values(app.values, {})
        except ValueError as exc:
            self.assertIn('port', getattr(exc, 'fields', ()))
        else:
            self.fail('Invalid port was accepted')
        self.assertEqual(Settings.load(app.settings_path).port, 8000)

    def test_disconnect_stops_controller_and_closes_sender(self):
        app, messages = self.app(buttons={'0': {'press': 'Down', 'release': 'Up'}})
        app.start_output()
        app.buttons[0] = True
        app.poll()
        def disconnected():
            raise ConnectionError('Joystick disconnected')
        app.joystick.read = disconnected
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.sender)
        self.assertEqual(messages[-1], ('/cmd', 'Up'))
        self.assertTrue(self.sender.closed)
        self.assertEqual(app.output_label.get(), 'OUTPUT STOPPED')
        self.assertFalse(app.joystick.handle)
        self.assertIn('disconnected', app.device_label.get())

    def test_test_mode_needs_no_joystick_and_ignores_it(self):
        app, messages = self.app(test_period=10)
        app.joystick = None
        app.start_output(test=True)
        self.assertTrue(app.controller.active and app.controller.test)
        self.assertEqual(app.errors, [])
        self.assertIn('TEST', app.output_label.get())
        app.last_tick -= 0.2
        app.poll()
        self.assertNotEqual(app.controller.motion.xyz[:2], [0, 0])
        app.stop_output()
        self.assertFalse(app.controller.active)
        self.assertEqual(app.output_label.get(), 'OUTPUT STOPPED')
        self.assertTrue(self.sender.closed)

    def test_test_mode_send_failure_stops_output(self):
        app, _ = self.app()
        app.start_output(test=True)
        self.sender.fail = True
        app.last_tick -= 0.2
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertEqual(app.status.get(), 'send failed')

    def test_output_failure_stops_output_but_keeps_joystick_open(self):
        app, _ = self.app()
        app.start_output()
        self.sender.fail = True
        app.axes[2] = 0.5
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.sender)
        self.assertEqual(app.status.get(), 'send failed')
        self.assertTrue(app.joystick.handle)
        self.assertEqual(app.device_label.get(), '')
        app.start_output()
        self.assertTrue(app.controller.active)
        self.assertEqual(app.errors, [])

    def test_unexpected_error_still_stops_window_output(self):
        app, _ = self.app()
        app.start_output()
        def broken(*args):
            raise TypeError('unexpected')
        app.controller.motion.step = broken
        with self.assertRaises(TypeError):
            app.poll()
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.sender)
        self.assertEqual(app.output_label.get(), 'OUTPUT STOPPED')
        self.assertEqual(app.start_button.state, 'normal')

    def test_mapped_reset_while_stopped_does_not_save_drafts(self):
        app, _ = self.app(initial_x=1, buttons={'0': {'action': 'reset'}})
        app.controller.motion.xyz = [4, 5, 1.5]
        app.values['initial_x'].set('2')
        app.values['max_speed'].set('5')
        app.buttons[0] = True
        app.poll()
        self.assertEqual(app.controller.motion.xyz, [1, 0, 1.5])
        saved = Settings.load(app.settings_path)
        self.assertEqual((saved.initial_x, saved.max_speed), (1, 1))
        self.assertEqual(app.errors, [])

    def test_window_reset_while_stopped_applies_drafts(self):
        app, _ = self.app(initial_x=1)
        app.values['initial_x'].set('2')
        app.reset_target()
        self.assertEqual(app.controller.motion.xyz, [2, 0, 1.5])
        self.assertEqual(Settings.load(app.settings_path).initial_x, 2)

    def test_apply_saves_settings_even_if_joystick_read_fails(self):
        app, _ = self.app()
        app.values['max_speed'].set('3')
        def disconnected():
            raise ConnectionError('Joystick disconnected')
        app.joystick.read = disconnected
        self.assertTrue(app.apply_settings())
        self.assertEqual(Settings.load(app.settings_path).max_speed, 3)
        self.assertEqual(app.settings.max_speed, 3)
        self.assertIn('could not be read: Joystick disconnected', app.status.get())
        self.assertFalse(app.joystick.handle)

    def test_start_without_selected_joystick_explains_selection(self):
        app, messages = self.app()
        app.joystick.handle = None
        app.start_output()
        self.assertFalse(app.controller.active)
        self.assertEqual(messages, [])
        self.assertIn('Select a joystick in Setup', app.errors[-1][1])

    def test_mapped_start_and_toggle_work_once_per_press_while_stopped(self):
        app, messages = self.app(buttons={'0': {'action': 'start'}, '1': {'action': 'toggle'}})
        app.buttons[0] = True
        app.poll()
        self.assertTrue(app.controller.active)
        self.assertEqual(len(messages), 2)
        app.poll()
        self.assertEqual(len(messages), 2)
        app.buttons[0] = False
        app.poll()
        app.buttons[1] = True
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertTrue(self.sender.closed)
        app.poll()
        self.assertFalse(app.controller.active)
        app.buttons[1] = False
        app.poll()
        app.buttons[1] = True
        app.poll()
        self.assertTrue(app.controller.active)
        self.assertEqual(app.errors, [])

    def test_mapped_stop_releases_owned_ma_buttons(self):
        app, messages = self.app(buttons={'0': {'press': 'Down', 'release': 'Up'},
                                         '1': {'action': 'stop'}})
        app.start_output()
        app.buttons[0] = True
        app.poll()
        self.assertEqual(messages[-1], ('/cmd', 'Down'))
        app.buttons[1] = True
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertEqual(messages[-1], ('/cmd', 'Up'))
        self.assertTrue(self.sender.closed)

    def test_live_lock_toggle_is_saved_without_applying_draft_settings(self):
        app, messages = self.app()
        app.start_output()
        app.values['host'].set('draft.example')
        app.values['reset_locked'].set(False)
        app.set_reset_lock()
        saved = Settings.load(app.settings_path)
        self.assertFalse(saved.reset_locked)
        self.assertEqual(saved.host, '127.0.0.1')
        self.assertTrue(app.controller.active)
        self.assertEqual(app.reset_button.state, 'normal')
        self.assertEqual(app.save_button.state, 'disabled')
        self.assertEqual(len(messages), 2)
        app.values['reset_locked'].set(True)
        app.set_reset_lock()
        self.assertEqual(app.reset_button.state, 'disabled')

    def test_failed_lock_save_preserves_running_settings(self):
        app, _ = self.app()
        app.start_output()
        app.values['reset_locked'].set(False)
        app.settings_path = app.settings_path / 'missing' / 'settings.json'
        app.set_reset_lock()
        self.assertTrue(app.settings.reset_locked)
        self.assertTrue(app.values['reset_locked'].get())
        self.assertTrue(app.controller.active)
        self.assertEqual(app.reset_button.state, 'disabled')
        self.assertTrue(app.errors)

    def test_mapped_live_reset_obeys_lock_and_does_not_move_in_same_sample(self):
        app, messages = self.app(buttons={'0': {'action': 'reset'}})
        app.start_output()
        app.controller.motion.xyz = [4, 5, 1.5]
        app.buttons[0] = True
        app.poll()
        self.assertEqual(app.controller.motion.xyz, [4, 5, 1.5])
        app.values['reset_locked'].set(False)
        app.set_reset_lock()
        app.buttons[0] = False
        app.poll()
        before = len(messages)
        app.axes[0] = 1
        app.buttons[0] = True
        app.poll()
        self.assertEqual(app.controller.motion.xyz, [0, 0, 1.5])
        self.assertEqual(len(messages), before + 1)
        self.assertEqual(messages[-1][0], '/cmd')
        self.assertTrue(app.controller.active)

    def test_window_live_reset_failure_closes_sender(self):
        app, _ = self.app(reset_locked=False)
        app.start_output()
        self.sender.fail = True
        app.reset_target()
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.sender)
        self.assertTrue(self.sender.closed)
        self.assertIn('send failed', app.status.get())

    def test_learning_completion_does_not_start_output(self):
        app, messages = self.app(buttons={'0': {'action': 'start'}})
        app.learning = ('button', list(app.axes), list(app.buttons), time.monotonic() + 8)
        app.buttons[0] = True
        app.poll()
        self.assertIsNone(app.learning)
        self.assertEqual(app.button_id.get(), '0')
        self.assertFalse(app.controller.active)
        self.assertEqual(messages, [])
        app.poll()
        self.assertFalse(app.controller.active)
        app.buttons[0] = False
        app.poll()
        app.buttons[0] = True
        app.poll()
        self.assertTrue(app.controller.active)

    def test_local_mapping_editor_clears_ma_commands_and_persists_action(self):
        app, _ = self.app(buttons={'0': {'press': 'Go', 'release': 'Off'}})
        app.load_button()
        self.assertEqual(app.button_action.get(), 'MA command')
        app.button_action.set('Start output')
        app.set_button()
        app.apply_settings()
        self.assertEqual(Settings.load(app.settings_path).buttons['0'], {'action': 'start'})

    def test_stop_wins_over_simultaneous_start(self):
        app, messages = self.app(buttons={'0': {'action': 'start'}, '1': {'action': 'stop'}})
        app.buttons = [True, True, False]
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertEqual(messages, [])

    def test_reset_sample_still_processes_ma_button_edges(self):
        app, messages = self.app(reset_locked=False,
                                buttons={'0': {'press': 'Down', 'release': 'Up'},
                                         '1': {'action': 'reset'}})
        app.start_output()
        app.buttons = [True, True, False]
        app.poll()
        self.assertEqual(messages[-1], ('/cmd', 'Down'))
        app.buttons[1] = False
        app.poll()
        app.buttons = [False, True, False]
        app.poll()
        self.assertEqual(messages[-1], ('/cmd', 'Up'))

    def test_locked_reset_press_keeps_normal_motion_running(self):
        app, _ = self.app(buttons={'0': {'action': 'reset'}})
        app.start_output()
        app.axes[0] = 1
        app.buttons[0] = True
        app.process_input(0.1)
        self.assertAlmostEqual(app.controller.motion.xyz[0], 0.1)

    def test_apply_suppresses_buttons_held_since_last_poll(self):
        app, messages = self.app(buttons={'0': {'action': 'start'}})
        app.joystick.read = lambda: ([0, 0, 0], [True, False, False])
        app.apply_settings()
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertEqual(messages, [])

    def test_failed_start_does_not_resume_from_its_held_button_snapshot(self):
        app, messages = self.app(buttons={'0': {'action': 'start'}})
        states = iter(([False, False, False], [True, False, False]))
        app.joystick.read = lambda: ([0, 0, 0], next(states, [True, False, False]))
        failing = Sender(messages)
        failing.fail = True
        succeeding = Sender(messages)
        with patch.object(followspot, 'OscSender', side_effect=[failing, succeeding]):
            app.start_output()
            self.assertFalse(app.controller.active)
            self.assertIn('send failed', app.status.get())
            app.poll()
            self.assertFalse(app.controller.active)
            self.assertIsNone(app.sender)
            self.assertEqual(messages, [])


class PsnWindowTests(unittest.TestCase):
    app = WindowTests.app

    def test_psn_mode_sends_no_marker_commands_stop_holds_release_closes(self):
        app, messages = self.app(position_output='psn')
        app.start_output()
        self.assertTrue(app.controller.active)
        self.assertEqual(len(self.streamers), 1)
        self.assertFalse([m for m in messages if m[0] == '/cmd'])
        self.assertTrue([m for m in messages if m[0].startswith('/Page1/Fader')])
        app.controller.tick([1.0, 0, 0], 0.1)
        self.assertGreater(self.streamers[0].position[0], 0)
        app.stop_output()
        self.assertFalse(app.controller.active)
        self.assertIs(app.streamer, self.streamers[0])
        self.assertFalse(self.streamers[0].closed)
        self.assertIn('Release marker', app.status.get())
        self.assertTrue(app.release_marker())
        self.assertTrue(self.streamers[0].closed)
        self.assertIsNone(app.streamer)
        self.assertIn('0, 0, 0', app.status.get())

    def test_osc_mode_never_creates_a_streamer(self):
        app, messages = self.app()
        app.start_output()
        self.assertEqual(self.streamers, [])
        self.assertTrue([m for m in messages if m[0] == '/cmd'])
        self.assertFalse(app.release_marker())
        self.assertIn('No PSN stream', app.status.get())

    def test_restart_reuses_the_held_stream(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.stop_output()
        app.start_output()
        self.assertEqual(len(self.streamers), 1)

    def test_streamer_error_with_no_joystick_stops_output_and_records_a_fault(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.joystick = None
        self.streamers[0].error = OSError('network down')
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.streamer)
        self.assertTrue(self.streamers[0].closed)
        self.assertIn('network down', app.faults['psn'])

    def test_held_stream_error_while_stopped_is_reported(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.stop_output()
        app.joystick = None
        self.streamers[0].error = OSError('network down')
        app.poll()
        self.assertIsNone(app.streamer)
        self.assertIn('psn', app.faults)

    def test_failed_start_closes_only_a_stream_it_created(self):
        app, messages = self.app(position_output='psn')
        failing = Sender(messages)
        failing.fail = True
        with patch.object(followspot, 'OscSender', return_value=failing):
            app.start_output()
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.streamer)
        self.assertTrue(self.streamers[0].closed)
        app.start_output()
        app.stop_output()
        with patch.object(followspot, 'OscSender', return_value=failing):
            app.start_output()
        self.assertIsNotNone(app.streamer)
        self.assertFalse(self.streamers[1].closed)

    def test_psn_settings_cannot_change_while_a_stream_is_open(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.stop_output()
        app.values['psn_port'].set('56570')
        self.assertFalse(app.apply_settings())
        self.assertEqual(app.settings.psn_port, 56565)
        app.release_marker()
        self.assertTrue(app.apply_settings())
        self.assertEqual(app.settings.psn_port, 56570)

    def test_joystick_loss_holds_the_stream_and_says_so(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        def unplugged():
            raise OSError('unplugged')
        app.joystick.read = unplugged
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertIsNotNone(app.streamer)
        self.assertFalse(self.streamers[0].closed)
        self.assertIn('Release marker', app.faults['input'])

    def test_release_marker_button_ranks_after_stop_and_before_start(self):
        app, _ = self.app(position_output='psn',
                          buttons={'0': {'action': 'release_marker'}, '1': {'action': 'start'}, '2': {'action': 'stop'}})
        app.start_output()
        app.stop_output()
        app.buttons = [True, True, False]
        app.process_input(0.033)
        self.assertIsNone(app.streamer)
        self.assertFalse(app.controller.active)
        app.start_output()
        app.buttons = [False, False, False]
        app.button_edges.seed(app.buttons)
        app.buttons = [True, False, True]
        app.process_input(0.033)
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.streamer)

    def test_osc_failure_stops_output_but_holds_the_stream(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        self.sender.fail = True
        app.axes[2] = 1.0
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertIs(app.streamer, self.streamers[0])
        self.assertFalse(self.streamers[0].closed)

    def test_release_marker_button_without_a_stream_does_not_skip_the_sample(self):
        app, messages = self.app(buttons={'0': {'action': 'release_marker'}, '1': {'press': 'Down', 'release': 'Up'}})
        app.start_output()
        app.buttons = [False, True, False]
        app.process_input(0.033)
        self.assertEqual(messages[-1], ('/cmd', 'Down'))
        app.buttons = [True, False, False]
        app.process_input(0.033)
        self.assertTrue(app.controller.active)
        self.assertEqual(messages[-1], ('/cmd', 'Up'))
        self.assertNotIn('stopped', app.status.get().lower())

    def test_close_streamer_forgets_the_stream_even_if_close_raises(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.stop_output()
        def broken():
            raise OSError('close failed')
        self.streamers[0].close = broken
        with self.assertRaises(OSError):
            app.close_streamer()
        self.assertIsNone(app.streamer)

    def test_position_label_shows_the_held_position_while_stopped(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.controller.tick([1.0, 0, 0], 0.1)
        app.stop_output()
        self.assertIn('Held at', app.position_label.get())
        app.release_marker()
        self.assertNotIn('Held at', app.position_label.get())

    def test_position_label_has_no_held_text_while_running(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.update_position()
        self.assertNotIn('Held at', app.position_label.get())

    def test_stopped_reset_keeps_showing_the_streamers_held_position(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.controller.tick([1.0, 0, 0], 0.1)
        app.stop_output()
        hx, hy, hz = self.streamers[0].position
        self.assertTrue(app.reset_target())
        target = app.controller.motion.xyz
        self.assertNotEqual((hx, hy, hz), tuple(target))
        lines = app.position_label.get().split('\n')
        self.assertEqual(lines[0], f'X {target[0]:+.3f} m   Y {target[1]:+.3f} m   Z {target[2]:.3f} m')
        self.assertEqual(lines[1], f'Held at  X {hx:+.3f} m   Y {hy:+.3f} m   Z {hz:.3f} m')
        self.assertEqual(self.streamers[0].position, (hx, hy, hz))

    def test_stream_error_fault_persists_in_the_fault_text_until_start(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.stop_output()
        self.streamers[0].error = OSError('network down')
        app.poll()
        self.assertIn('network down', app.fault_label.get())
        app.poll()
        self.assertIn('network down', app.fault_label.get())
        app.start_output()
        self.assertNotIn('network down', app.fault_label.get())

    def test_close_asks_before_dropping_a_held_stream(self):
        app, _ = self.app(position_output='psn')
        destroyed = []
        app.root.destroy = lambda: destroyed.append(True)
        app.joystick.shutdown = lambda: None
        app.start_output()
        app.confirm = False
        app.close()
        self.assertEqual(destroyed, [])
        self.assertTrue(app.controller.active)
        app.confirm = True
        app.close()
        self.assertEqual(destroyed, [True])
        self.assertTrue(self.streamers[0].closed)


class FakeJoystick:
    def __init__(self):
        self.handle = None
    def devices(self):
        return [(0, 'PXN-2113 Pro')]
    def open(self, index):
        self.handle = True
    def read(self):
        if not self.handle:
            raise ConnectionError('Select and open a joystick first.')
        return [0, 0, 0], [False, False]
    def close(self):
        self.handle = None
    def shutdown(self):
        self.close()


class RealWindowTests(unittest.TestCase):
    """Run the real __init__/build_window wiring when Tk can open a window."""
    def open_root(self):
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f'Tk unavailable: {exc}')
        try:
            return tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk window unavailable: {exc}')

    def open_app(self, **changes):
        root = self.open_root()
        root.withdraw()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'settings.json'
        Settings(**changes).save(path)
        joystick_patch = patch.object(followspot, 'Joystick', FakeJoystick)
        sender_patch = patch.object(followspot, 'OscSender', side_effect=lambda *args: Sender([]))
        joystick_patch.start()
        sender_patch.start()
        self.addCleanup(joystick_patch.stop)
        self.addCleanup(sender_patch.stop)
        app = followspot.App(root, path)
        self.addCleanup(app.close)
        return app

    def test_visible_window_with_real_backend_starts_and_polls_without_aborting(self):
        # A child process is necessary: a native Tk/SDL abort kills the interpreter.
        # No output is started and only temporary settings are used.
        try:
            import tkinter
        except ImportError as exc:
            self.skipTest(f'Tk unavailable: {exc}')
        program = '''
import tempfile
from pathlib import Path
import tkinter as tk
import sys
from followspot import App
with tempfile.TemporaryDirectory() as folder:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(exc, file=sys.stderr)
        sys.exit(77)
    errors = []
    root.report_callback_exception = lambda *args: errors.append(str(args))
    app = App(root, Path(folder) / 'settings.json')
    def check_paint():
        root.update_idletasks()
        assert app.start_button.winfo_ismapped()
        assert app.view.stage.winfo_ismapped()
        assert app.view.stage.winfo_width() > 160
        assert app.view.stage.winfo_height() > 130
    root.after(100, check_paint)
    root.after(500, app.close)
    root.mainloop()
    assert not errors, errors
'''
        result = subprocess.run([sys.executable, '-c', program], cwd=Path(followspot.__file__).parent,
                                capture_output=True, text=True, timeout=45)
        if result.returncode == 77:
            self.skipTest(f'Tk window unavailable: {result.stderr.strip()}')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_window_psn_controls_and_held_marker(self):
        streamers = []
        def new_streamer(settings, xyz):
            streamers.append(FakeStreamer(settings, xyz))
            return streamers[-1]
        with patch.object(followspot, 'PsnStreamer', side_effect=new_streamer):
            app = self.open_app(position_output='psn')
            self.assertIn('position_output', app.view.fields)
            for key in ('psn_tracker_id', 'psn_group', 'psn_port', 'psn_interface'):
                self.assertIn(key, app.view.fields)
            app.view.refresh()
            self.assertEqual(str(app.release_button.cget('state')), 'disabled')
            app.start_output()
            app.view.refresh()
            self.assertEqual(str(app.release_button.cget('state')), 'normal')
            app.stop_output()
            app.root.update_idletasks()
            app.view.draw_stage()
            self.assertTrue(app.view.stage.find_withtag('held'))
            app.release_button.invoke()
            self.assertIsNone(app.streamer)
            app.view.draw_stage()
            self.assertFalse(app.view.stage.find_withtag('held'))
            self.assertIn('PSN', app.view.summary.get())

    def test_real_window_release_button_is_hidden_in_osc_mode(self):
        app = self.open_app()
        app.view.refresh()
        self.assertFalse(app.release_button.winfo_manager())
        self.assertNotIn('PSN', app.view.summary.get())

    def test_setup_is_readable_but_cannot_be_edited_while_running(self):
        app = self.open_app()
        app.start_output()
        app.notebook.select(1)
        self.assertEqual(str(app.notebook.tab(1, 'state')), 'normal')
        self.assertEqual(str(app.view.fields['host']['state']), 'disabled')
        self.assertEqual(str(app.stop_button['state']), 'normal')
        app.stop_output()
        self.assertEqual(str(app.view.fields['host']['state']), 'normal')

    def test_readiness_disables_start_without_blocking_joystick_free_test(self):
        app = self.open_app()
        app.joystick.close()
        app.view.refresh()
        self.assertEqual(str(app.start_button['state']), 'disabled')
        self.assertIn('joystick', app.view.readiness.get().lower())
        self.assertEqual(str(app.test_button['state']), 'normal')
        app.test_button.invoke()
        self.assertTrue(app.controller.active and app.controller.test)

    def test_readiness_uses_the_draft_that_start_will_apply(self):
        app = self.open_app(axis_slider=7)
        self.assertEqual(str(app.start_button['state']), 'disabled')
        app.values['axis_slider'].set('2')
        self.assertEqual(str(app.start_button['state']), 'normal')
        app.values['port'].set('invalid')
        self.assertEqual(str(app.start_button['state']), 'disabled')
        app.values['port'].set('8000')
        app.press_command.set('Go+ Sequence 10')
        self.assertEqual(str(app.start_button['state']), 'disabled')

    def test_rejected_mapping_selection_restores_the_edited_row(self):
        app = self.open_app(buttons={'0': {'press': 'First'}, '1': {'press': 'Second'}})
        app.button_table.selection_set('0')
        app.load_button()
        app.press_command.set('Edited first')
        app.button_table.selection_set('1')
        app.load_button()
        self.assertEqual(app.button_table.selection(), ('0',))
        self.assertEqual(app.press_command.get(), 'Edited first')
        app.view.discard_editor()
        self.assertEqual(app.press_command.get(), 'First')
        self.assertEqual(app.button_table.selection(), ('0',))

    def test_successful_reset_lock_retry_clears_its_own_fault(self):
        app = self.open_app()
        app.values['reset_locked'].set(False)
        path = app.settings_path
        app.settings_path = path / 'missing'
        with patch('tkinter.messagebox.showerror'):
            app.set_reset_lock()
        self.assertIn('Reset lock', app.fault_label.get())
        app.settings_path = path
        app.values['reset_locked'].set(False)
        app.set_reset_lock()
        self.assertEqual(app.fault_label.get(), '')

    def test_unsaved_changes_and_field_error_survive_a_failed_save(self):
        app = self.open_app()
        app.values['port'].set('invalid')
        self.assertIn('Unsaved', app.view.save_state.get())
        self.assertFalse(app.apply_settings())
        self.assertTrue(app.view.fields['port'].instate(['invalid']))
        self.assertEqual(app.notebook.index(app.notebook.select()), 1)
        self.assertEqual(Settings.load(app.settings_path).port, 8000)
        app.values['port'].set('9000')
        self.assertTrue(app.apply_settings())
        self.assertFalse(app.view.fields['port'].instate(['invalid']))
        self.assertEqual(app.view.save_state.get(), 'Settings saved')

    def test_fault_persists_through_routine_status_and_stop(self):
        app = self.open_app()
        app.start_output()
        app.sender.fail = True
        app.axes = [0, 0, 1]
        app.joystick.read = lambda: (app.axes, [False, False])
        app.poll()
        self.assertIn('send failed', app.fault_label.get())
        app.stop_output()
        app.status.set('Centre captured')
        self.assertIn('send failed', app.fault_label.get())
        app.start_output()
        self.assertEqual(app.fault_label.get(), '')

    def test_mapping_editor_cannot_silently_discard_pending_commands(self):
        app = self.open_app()
        app.press_command.set('Go+ Sequence 10')
        self.assertFalse(app.apply_settings())
        self.assertIn('mapping', app.view.mapping_state.get().lower())
        self.assertEqual(Settings.load(app.settings_path).buttons, {})
        app.set_button()
        self.assertTrue(app.apply_settings())
        self.assertEqual(Settings.load(app.settings_path).buttons['0']['press'], 'Go+ Sequence 10')

    def test_stage_preview_uses_applied_limits_and_never_moves_target(self):
        app = self.open_app(x_min=-4, x_max=8, y_min=-2, y_max=6)
        app.controller.motion.xyz = [8, 6, 1.5]
        app.update_position()
        app.root.update_idletasks()
        app.view.draw_stage()
        before = list(app.controller.motion.xyz)
        app.values['x_max'].set('20')
        app.view.stage.event_generate('<Button-1>', x=100, y=100)
        self.assertEqual(app.controller.motion.xyz, before)
        point = app.view.stage.coords('target')
        limits = app.view.stage.coords('limits')
        self.assertAlmostEqual((point[0] + point[2]) / 2, limits[2])
        self.assertAlmostEqual((point[1] + point[3]) / 2, limits[1])

    def test_real_window_zoom_tab_learns_calibrates_and_resets(self):
        root = self.open_root()
        root.withdraw()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'settings.json'
        Settings(zoom_enabled=True, reset_locked=False, initial_zoom=25).save(path)
        class ZoomJoystick(FakeJoystick):
            def read(self):
                axes, buttons = super().read()
                return axes + [0.2], buttons
        messages, errors = [], []
        with patch.object(followspot, 'Joystick', ZoomJoystick), \
             patch.object(followspot, 'OscSender', side_effect=lambda *args: Sender(messages)), \
             patch('tkinter.messagebox.showerror', side_effect=lambda *args: errors.append(args)):
            app = followspot.App(root, path)
            try:
                self.assertIn('Brightness / zoom', [app.view.setup_tabs.tab(tab, 'text') for tab in app.view.setup_tabs.tabs()])
                app.calibrate_zoom()
                app.start_output()
                self.assertEqual(errors, [])
                self.assertTrue(app.controller.active)
                self.assertEqual(messages[-1], ('/Page1/Fader202', 25))
                app.controller.motion.zoom_level = 60
                app.reset_button.invoke()
                self.assertEqual(messages[-1], ('/Page1/Fader202', 25))
                self.assertIn('25.0%', app.zoom_label.get())
            finally:
                app.close()

    def test_real_window_selects_saved_device_and_runs_output(self):
        root = self.open_root()
        root.withdraw()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        messages, errors = [], []
        with patch.object(followspot, 'Joystick', FakeJoystick), \
             patch.object(followspot, 'OscSender', side_effect=lambda *args: Sender(messages)), \
             patch('tkinter.messagebox.showerror', side_effect=lambda *args: errors.append(args)):
            app = followspot.App(root, Path(folder.name) / 'settings.json')
            try:
                self.assertEqual(app.device_label.get(), 'PXN-2113 Pro · 3 axes · 2 buttons')
                app.start_output()
                self.assertEqual(errors, [])
                self.assertTrue(app.controller.active)
                self.assertEqual(len(messages), 2)
                self.assertEqual(str(app.start_button['state']), 'disabled')
                self.assertEqual(str(app.notebook.tab(1, 'state')), 'normal')
                self.assertEqual(str(app.view.fields['host']['state']), 'disabled')
                app.poll()
                app.stop_output()
                self.assertEqual(str(app.start_button['state']), 'normal')
                self.assertEqual(str(app.notebook.tab(1, 'state')), 'normal')
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main()
