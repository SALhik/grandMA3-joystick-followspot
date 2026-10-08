"""Window behaviour tested without requiring macOS WindowServer access."""
import unittest
from types import SimpleNamespace
import followspot
from followspot_core import Controller, Settings


class Value:
    def __init__(self, value=''):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class WindowTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
