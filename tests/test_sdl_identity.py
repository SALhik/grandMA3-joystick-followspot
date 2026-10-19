"""SDL boundary doubles: no physical controller is opened."""
import unittest
from unittest.mock import patch

import joystick


class Function:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


class SDLDouble:
    def __init__(self):
        self.current = [(41, b'A'), (72, b'B')]
        self.events = True
        self.queued_events = 0
        self.state = 0
        self.pending_state = 0
        self.opened = []
        self.closed = []
        self.replace_on_open = False
        calls = {
            'SDL_SetHint': lambda *args: 1,
            'SDL_InitSubSystem': lambda flags: 0,
            'SDL_QuitSubSystem': lambda flags: None,
            'SDL_GetError': lambda: b'',
            'SDL_ClearError': lambda: None,
            'SDL_NumJoysticks': lambda: len(self.current),
            'SDL_JoystickNameForIndex': lambda i: self.current[i][1],
            'SDL_JoystickGetDeviceInstanceID': lambda i: self.current[i][0],
            'SDL_JoystickInstanceID': lambda handle: handle,
            'SDL_JoystickOpen': self.open,
            'SDL_JoystickClose': self.closed.append,
            'SDL_JoystickGetAttached': lambda handle: any(i == handle for i, _ in self.current),
            'SDL_JoystickNumAxes': lambda handle: 1,
            'SDL_JoystickNumButtons': lambda handle: 0,
            'SDL_JoystickGetAxis': lambda handle, i: self.state,
            'SDL_JoystickGetButton': lambda handle, i: 0,
            'SDL_JoystickUpdate': self.update,
            'SDL_PumpEvents': lambda: None,
            'SDL_JoystickEventState': self.event_state,
        }
        for name, call in calls.items():
            setattr(self, name, Function(call))

    def open(self, index):
        if not 0 <= index < len(self.current):
            return None
        if self.replace_on_open:
            self.current[index] = (93, b'Replacement')
        handle = self.current[index][0]
        self.opened.append(handle)
        return handle

    def event_state(self, state):
        self.events = bool(state)
        return state

    def update(self):
        self.state = self.pending_state
        if self.events:
            self.queued_events += 1


class SDLIdentityTests(unittest.TestCase):
    def setUp(self):
        self.lib = SDLDouble()
        with patch.object(joystick.ct, 'CDLL', return_value=self.lib), \
             patch.object(joystick.ct.util, 'find_library', return_value='fake-sdl'):
            self.sdl = joystick.SDLJoystick()
        with patch.object(joystick, 'SDLJoystick', return_value=self.sdl):
            self.j = joystick.Joystick()
        self.addCleanup(self.sdl.shutdown)

    def test_cached_removed_device_does_not_open_shifted_device(self):
        with patch.object(joystick.sys, 'platform', 'win32'):
            self.assertEqual(self.j.devices(), [(0, 'A'), (1, 'B')])
        self.lib.current.pop(0)
        with self.assertRaisesRegex(ConnectionError, 'Refresh'):
            self.j.open(0)
        self.assertEqual(self.lib.opened, [])
        self.assertIsNone(self.sdl.handle)

    def test_cached_surviving_device_resolves_its_new_index(self):
        with patch.object(joystick.sys, 'platform', 'win32'):
            self.j.devices()
        self.lib.current.pop(0)
        self.j.open(1)
        self.assertEqual(self.sdl.handle, 72)

    def test_replacement_during_open_is_closed_and_rejected(self):
        self.sdl.devices()
        self.lib.replace_on_open = True
        with self.assertRaisesRegex(ConnectionError, 'Refresh'):
            self.sdl.open(0)
        self.assertEqual(self.lib.closed, [93])
        self.assertIsNone(self.sdl.handle)

    def test_polling_updates_state_without_accumulating_unused_events(self):
        self.sdl.devices()
        self.sdl.open(0)
        self.lib.pending_state = 32767
        for _ in range(5):
            self.assertEqual(self.sdl.read(), ([1.0], []))
        self.assertEqual(self.lib.queued_events, 0)
        self.lib.current.pop(0)
        self.assertEqual(self.sdl.devices(), [(0, 'B')])
        with self.assertRaises(ConnectionError):
            self.sdl.read()


if __name__ == '__main__':
    unittest.main()
