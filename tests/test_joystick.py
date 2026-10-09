import unittest
import joystick
import sys
from unittest.mock import patch
from types import SimpleNamespace


class JoystickTests(unittest.TestCase):
    def test_native_refresh_reenumerates_after_reconnect(self):
        # The OS manager caches a snapshot until SetDeviceMatching re-enumerates.
        # Simulate that external API contract, and assert the returned device.
        state = {'cached': 101, 'current': 101}
        def rematch(manager, criteria):
            state['cached'] = state['current']
        def set_values(snapshot, values):
            values[0] = snapshot
        j = joystick.MacHIDJoystick.__new__(joystick.MacHIDJoystick)
        j.manager = 1
        j.device_set = None
        j.io = SimpleNamespace(IOHIDManagerSetDeviceMatching=rematch,
                               IOHIDManagerCopyDevices=lambda manager: state['cached'])
        j.cf = SimpleNamespace(CFRelease=lambda snapshot: None,
                               CFSetGetCount=lambda snapshot: 1, CFSetGetValues=set_values)
        j.number = lambda device, key: {'PrimaryUsagePage': 1, 'PrimaryUsage': 4, 'LocationID': device}[key]
        j.name = lambda device: 'New controller' if device == 102 else 'Old controller'
        self.assertEqual(j.devices(), [(0, 'Old controller')])
        state['current'] = 102
        self.assertEqual(j.devices(), [(0, 'New controller')])

    def test_native_hid_axis_normalization(self):
        self.assertEqual(joystick.normalize_hid_axis(0, 0, 255), -1)
        self.assertEqual(joystick.normalize_hid_axis(255, 0, 255), 1)
        self.assertEqual(joystick.normalize_hid_axis(0, -100, 100), 0)
        with self.assertRaises(ValueError):
            joystick.normalize_hid_axis(0, 0, 0)

    def backends(self, sdl_devices, native_devices):
        # These doubles stand in for OS APIs; the actual wrapper policy is tested.
        opened = []
        def backend(label, devices):
            b = SimpleNamespace(handle=None, lib=None, devices=lambda: devices,
                                read=lambda: (label, b.handle), close=lambda: None, shutdown=lambda: None)
            def open_device(index):
                b.handle = index
                opened.append((label, index))
            b.open = open_device
            return b
        return backend('sdl', sdl_devices), backend('native', native_devices), opened

    def test_empty_sdl_list_falls_back_to_native_device(self):
        sdl, native, opened = self.backends([], [(0, 'PXN-2113 Pro')])
        with patch.object(joystick, 'SDLJoystick', return_value=sdl), \
             patch.object(joystick, 'MacHIDJoystick', return_value=native), \
             patch.object(joystick.sys, 'platform', 'darwin'):
            j = joystick.Joystick()
            self.assertEqual(j.devices(), [(0, 'PXN-2113 Pro')])
            j.open(0)
            self.assertEqual(j.read(), ('native', 0))
            j.shutdown()

    def test_native_controller_is_listed_beside_other_sdl_controllers(self):
        sdl, native, opened = self.backends([(0, 'Gamepad')], [(0, 'Gamepad'), (1, 'PXN-2113 Pro')])
        with patch.object(joystick, 'SDLJoystick', return_value=sdl), \
             patch.object(joystick, 'MacHIDJoystick', return_value=native), \
             patch.object(joystick.sys, 'platform', 'darwin'):
            j = joystick.Joystick()
            # The SDL-named Gamepad is not listed twice.
            self.assertEqual(j.devices(), [(0, 'Gamepad'), (1, 'PXN-2113 Pro')])
            j.open(1)
            self.assertEqual(j.read(), ('native', 1))
            j.open(0)
            self.assertEqual(opened, [('native', 1), ('sdl', 0)])
            with self.assertRaises(ConnectionError):
                j.open(2)

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS HID only')
    def test_native_discovery_lists_only_controller_usages(self):
        j = joystick.MacHIDJoystick()
        try:
            devices = j.devices()
            for record in j.records:
                self.assertEqual(record['page'], 1)
                self.assertIn(record['usage'], (4, 5, 8))
            self.assertEqual(len(devices), len(j.records))
        finally:
            j.shutdown()

    def test_signed_axis_endpoints(self):
        self.assertEqual(joystick.normalize_axis(-32768), -1)
        self.assertEqual(joystick.normalize_axis(32767), 1)
        self.assertEqual(joystick.normalize_axis(0), 0)

    def test_virtual_device_read_and_disconnect(self):
        j = joystick.Joystick()
        lib = j.lib
        import ctypes as ct
        lib.SDL_JoystickAttachVirtual.argtypes = [ct.c_int, ct.c_int, ct.c_int, ct.c_int]
        lib.SDL_JoystickAttachVirtual.restype = ct.c_int
        lib.SDL_JoystickSetVirtualAxis.argtypes = [ct.c_void_p, ct.c_int, ct.c_int16]
        lib.SDL_JoystickSetVirtualButton.argtypes = [ct.c_void_p, ct.c_int, ct.c_uint8]
        lib.SDL_JoystickDetachVirtual.argtypes = [ct.c_int]
        index = lib.SDL_JoystickAttachVirtual(1, 3, 2, 0)
        self.assertGreaterEqual(index, 0)
        try:
            # SDL devices are listed first, so the SDL index is also the list index.
            j.devices()
            j.open(index)
            lib.SDL_JoystickSetVirtualAxis(j.handle, 0, 32767)
            lib.SDL_JoystickSetVirtualAxis(j.handle, 2, -32768)
            lib.SDL_JoystickSetVirtualButton(j.handle, 1, 1)
            axes, buttons = j.read()
            self.assertEqual(axes, [1, 0, -1])
            self.assertEqual(buttons, [False, True])
            lib.SDL_JoystickDetachVirtual(index)
            j.devices()
            with self.assertRaises(ConnectionError):
                j.read()
        finally:
            j.close()
            j.shutdown()


if __name__ == '__main__':
    unittest.main()
