import unittest
import joystick


class JoystickTests(unittest.TestCase):
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
