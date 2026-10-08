"""Minimal SDL2 joystick reader; uses the installed native library."""
import ctypes as ct
import ctypes.util
import os


def normalize_axis(value):
    return value / (32768.0 if value < 0 else 32767.0)


class Joystick:
    def __init__(self):
        candidates = [os.environ.get('FOLLOWSPOT_SDL2'), ct.util.find_library('SDL2'),
                      '/opt/homebrew/lib/libSDL2.dylib', '/usr/local/lib/libSDL2.dylib',
                      '/Library/Frameworks/SDL2.framework/SDL2']
        self.lib = None
        self.handle = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                self.lib = ct.CDLL(candidate)
                break
            except OSError:
                pass
        if self.lib is None:
            raise RuntimeError('SDL2 is missing. Install it with: brew install sdl2')
        signatures = {
            'SDL_SetHint': ([ct.c_char_p, ct.c_char_p], ct.c_int),
            'SDL_InitSubSystem': ([ct.c_uint32], ct.c_int),
            'SDL_QuitSubSystem': ([ct.c_uint32], None),
            'SDL_GetError': ([], ct.c_char_p),
            'SDL_ClearError': ([], None),
            'SDL_NumJoysticks': ([], ct.c_int),
            'SDL_JoystickNameForIndex': ([ct.c_int], ct.c_char_p),
            'SDL_JoystickOpen': ([ct.c_int], ct.c_void_p),
            'SDL_JoystickClose': ([ct.c_void_p], None),
            'SDL_JoystickGetAttached': ([ct.c_void_p], ct.c_int),
            'SDL_JoystickNumAxes': ([ct.c_void_p], ct.c_int),
            'SDL_JoystickNumButtons': ([ct.c_void_p], ct.c_int),
            'SDL_JoystickGetAxis': ([ct.c_void_p, ct.c_int], ct.c_int16),
            'SDL_JoystickGetButton': ([ct.c_void_p, ct.c_int], ct.c_uint8),
            'SDL_JoystickUpdate': ([], None),
            'SDL_PumpEvents': ([], None),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result
        self.lib.SDL_SetHint(b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', b'1')
        if self.lib.SDL_InitSubSystem(0x200) != 0:
            raise RuntimeError(self.error())

    def error(self):
        return (self.lib.SDL_GetError() or b'Unknown SDL error').decode('utf-8', 'replace')

    def update(self):
        self.lib.SDL_PumpEvents()
        self.lib.SDL_JoystickUpdate()

    def devices(self):
        self.update()
        count = self.lib.SDL_NumJoysticks()
        if count < 0:
            raise RuntimeError(self.error())
        return [(i, (self.lib.SDL_JoystickNameForIndex(i) or b'Unnamed joystick').decode('utf-8', 'replace'))
                for i in range(count)]

    def open(self, index):
        self.close()
        self.handle = self.lib.SDL_JoystickOpen(index)
        if not self.handle:
            raise ConnectionError(self.error())
        self.axis_count = self.lib.SDL_JoystickNumAxes(self.handle)
        self.button_count = self.lib.SDL_JoystickNumButtons(self.handle)
        if self.axis_count < 0 or self.button_count < 0:
            self.close()
            raise ConnectionError(self.error())

    def read(self):
        self.update()
        if not self.handle or not self.lib.SDL_JoystickGetAttached(self.handle):
            raise ConnectionError('Joystick disconnected. Reconnect it and click Refresh, then Start.')
        self.lib.SDL_ClearError()
        axes = [normalize_axis(self.lib.SDL_JoystickGetAxis(self.handle, i)) for i in range(self.axis_count)]
        buttons = [bool(self.lib.SDL_JoystickGetButton(self.handle, i)) for i in range(self.button_count)]
        if self.lib.SDL_GetError():
            raise ConnectionError(self.error())
        return axes, buttons

    def close(self):
        if self.handle:
            self.lib.SDL_JoystickClose(self.handle)
            self.handle = None

    def shutdown(self):
        self.close()
        self.lib.SDL_QuitSubSystem(0x200)
