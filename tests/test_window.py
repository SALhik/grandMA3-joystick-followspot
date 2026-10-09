"""Window behaviour tested without requiring macOS WindowServer access."""
import unittest
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import followspot
from followspot_core import ButtonActions, Controller, Settings


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


class WindowTests(unittest.TestCase):
    def app(self, **changes):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        app = followspot.App.__new__(followspot.App)
        app.settings_path = Path(folder.name) / 'settings.json'
        app.settings = Settings.from_dict(dict(Settings().to_dict(), **changes))
        app.settings.save(app.settings_path)
        app.values = {key: Value(value) for key, value in app.settings.to_dict().items() if key != 'buttons'}
        app.draft_buttons = dict(app.settings.buttons)
        app.axes, app.buttons = [0, 0, 0], [False] * 3
        app.button_actions = ButtonActions()
        app.button_actions.seed(app.buttons)
        app.sender = None
        messages = []
        app.controller = Controller(app.settings, app.send)
        for name in ('status', 'output_label', 'position_label', 'brightness_label',
                     'axes_label', 'buttons_label', 'device_label', 'button_id',
                     'press_command', 'release_command'):
            setattr(app, name, Value())
        app.button_action = Value('MA command')
        for name in ('start_button', 'reset_button', 'save_button', 'press_entry', 'release_entry'):
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
        app.errors = []
        app.messagebox = SimpleNamespace(showerror=lambda *args: app.errors.append(args))
        def new_sender(*args):
            self.sender = Sender(messages)
            return self.sender
        sender_patch = patch.object(followspot, 'OscSender', side_effect=new_sender)
        sender_patch.start()
        self.addCleanup(sender_patch.stop)
        return app, messages

    def test_settings_parse_rejects_invalid_numeric_input(self):
        s = Settings()
        values = {key: Value(value) for key, value in s.to_dict().items() if key != 'buttons'}
        values['axis_x'].set('not a number')
        with self.assertRaises(ValueError):
            followspot.settings_from_values(values, {})
        values['axis_x'].set('0')
        self.assertEqual(followspot.settings_from_values(values, {}).axis_x, 0)

    def test_disconnect_stops_controller_and_closes_sender(self):
        app = followspot.App.__new__(followspot.App)
        messages = []
        app.controller = Controller(Settings(buttons={'0': {'press': 'Down', 'release': 'Up'}}),
                                    lambda a, v: messages.append(v))
        app.controller.start([0, 0, -1], [False])
        app.controller.tick([0, 0, -1], [True], 0.03)
        closed = []
        app.sender = SimpleNamespace(close=lambda: closed.append(True))
        app.status = Value()
        app.learning = None
        app.output_label = Value()
        app.stop_output('Joystick disconnected')
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.sender)
        self.assertEqual(messages[-1], 'Up')
        self.assertEqual(closed, [True])
        self.assertEqual(app.output_label.get(), 'OUTPUT STOPPED')

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


if __name__ == '__main__':
    unittest.main()
