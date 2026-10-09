"""SDL joystick input plus native macOS HID controllers that SDL does not list."""
from collections import Counter
import ctypes as ct
import ctypes.util
import os
import sys


def normalize_axis(value):
    return value / (32768.0 if value < 0 else 32767.0)


class SDLJoystick:
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


def normalize_hid_axis(value, low, high):
    if high <= low:
        raise ValueError('Joystick reported an invalid axis range.')
    return max(-1.0, min(1.0, (value - low) / (high - low) * 2 - 1))


class MacHIDJoystick:
    """Discover controllers without opening a manager over keyboard/mouse devices.

    Open only the selected controller, non-exclusively. A device access denial
    is reported rather than being mistaken for an empty device list.
    """
    def __init__(self):
        self.io = ct.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
        self.cf = ct.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        p, u, n = ct.c_void_p, ct.c_uint32, ct.c_long
        signatures = {
            'IOHIDManagerCreate': ([p, u], p),
            'IOHIDManagerSetDeviceMatching': ([p, p], None),
            'IOHIDManagerCopyDevices': ([p], p),
            'IOHIDDeviceGetProperty': ([p, p], p),
            'IOHIDDeviceOpen': ([p, u], ct.c_int32),
            'IOHIDDeviceClose': ([p, u], ct.c_int32),
            'IOHIDDeviceCopyMatchingElements': ([p, p, u], p),
            'IOHIDDeviceGetValue': ([p, p, ct.POINTER(p)], ct.c_int32),
            'IOHIDValueGetIntegerValue': ([p], n),
            'IOHIDElementGetUsagePage': ([p], u),
            'IOHIDElementGetUsage': ([p], u),
            'IOHIDElementGetType': ([p], u),
            'IOHIDElementGetCookie': ([p], u),
            'IOHIDElementGetLogicalMin': ([p], n),
            'IOHIDElementGetLogicalMax': ([p], n),
        }
        for name, (args, result) in signatures.items():
            f = getattr(self.io, name)
            f.argtypes, f.restype = args, result
        signatures = {
            'CFRelease': ([p], None), 'CFRetain': ([p], p),
            'CFGetTypeID': ([p], ct.c_ulong),
            'CFStringGetTypeID': ([], ct.c_ulong),
            'CFNumberGetTypeID': ([], ct.c_ulong),
            'CFSetGetCount': ([p], n), 'CFSetGetValues': ([p, p], None),
            'CFArrayGetCount': ([p], n), 'CFArrayGetValueAtIndex': ([p, n], p),
            'CFStringCreateWithCString': ([p, ct.c_char_p, u], p),
            'CFStringGetCString': ([p, p, n, u], ct.c_bool),
            'CFNumberGetValue': ([p, ct.c_int, p], ct.c_bool),
        }
        for name, (args, result) in signatures.items():
            f = getattr(self.cf, name)
            f.argtypes, f.restype = args, result
        self.handle = self.device_set = self.elements = None
        self.records = []
        self.keys = {}
        self.manager = self.io.IOHIDManagerCreate(None, 0)
        if not self.manager:
            raise RuntimeError('Could not create the macOS HID discovery manager.')
        # Discovery requires no manager open, and does not read keyboard input.
        self.io.IOHIDManagerSetDeviceMatching(self.manager, None)

    def property(self, device, name):
        if name not in self.keys:
            self.keys[name] = self.cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)
        return self.io.IOHIDDeviceGetProperty(device, self.keys[name])

    def number(self, device, name):
        value = self.property(device, name)
        result = ct.c_int64()
        if value and self.cf.CFGetTypeID(value) == self.cf.CFNumberGetTypeID():
            self.cf.CFNumberGetValue(value, 4, ct.byref(result))
        return result.value

    def name(self, device):
        value = self.property(device, 'Product')
        buffer = ct.create_string_buffer(512)
        if value and self.cf.CFGetTypeID(value) == self.cf.CFStringGetTypeID():
            if self.cf.CFStringGetCString(value, buffer, len(buffer), 0x08000100):
                return buffer.value.decode('utf-8', 'replace')
        return 'Unnamed HID joystick'

    def devices(self):
        # Without a scheduled run loop, matching must refresh the cached device set.
        self.io.IOHIDManagerSetDeviceMatching(self.manager, None)
        snapshot = self.io.IOHIDManagerCopyDevices(self.manager)
        if self.device_set:
            self.cf.CFRelease(self.device_set)
        self.device_set = snapshot
        self.records = []
        if snapshot:
            devices = (ct.c_void_p * self.cf.CFSetGetCount(snapshot))()
            self.cf.CFSetGetValues(snapshot, devices)
            for device in devices:
                page, usage = self.number(device, 'PrimaryUsagePage'), self.number(device, 'PrimaryUsage')
                if page == 1 and usage in (4, 5, 8):
                    self.records.append({'device': device, 'name': self.name(device),
                                         'page': page, 'usage': usage,
                                         'location': self.number(device, 'LocationID')})
        self.records.sort(key=lambda r: (r['name'], r['location'], r['device']))
        return [(index, record['name']) for index, record in enumerate(self.records)]

    def open(self, index):
        self.close()
        if not 0 <= index < len(self.records):
            raise ConnectionError('Joystick list changed. Click Refresh and select it again.')
        device = self.records[index]['device']
        status = self.io.IOHIDDeviceOpen(device, 0)
        if status:
            code = f'0x{status & 0xffffffff:08x}'
            if (status & 0xffffffff) == 0xe00002e2:
                raise ConnectionError(
                    f'macOS sees the joystick but denied input access ({code}). '
                    'Check Privacy & Security → Input Monitoring for your launcher (Terminal/Python), '
                    'then quit and relaunch it. A sandbox may also deny access.')
            raise ConnectionError(f'Could not open the joystick: macOS HID error {code}.')
        self.handle = self.cf.CFRetain(device)
        try:
            self.elements = self.io.IOHIDDeviceCopyMatchingElements(self.handle, None, 0)
            self.axis_elements, self.button_elements = [], []
            seen = set()
            if self.elements:
                for i in range(self.cf.CFArrayGetCount(self.elements)):
                    element = self.cf.CFArrayGetValueAtIndex(self.elements, i)
                    kind = self.io.IOHIDElementGetType(element)
                    if kind not in (1, 2, 3):
                        continue
                    page = self.io.IOHIDElementGetUsagePage(element)
                    usage = self.io.IOHIDElementGetUsage(element)
                    cookie = self.io.IOHIDElementGetCookie(element)
                    if cookie in seen:
                        continue
                    seen.add(cookie)
                    if page == 1 and 0x30 <= usage <= 0x38:
                        low = self.io.IOHIDElementGetLogicalMin(element)
                        high = self.io.IOHIDElementGetLogicalMax(element)
                        if high > low:
                            self.axis_elements.append((usage, cookie, element, low, high))
                    elif page == 9:
                        self.button_elements.append((usage, cookie, element))
            self.axis_elements.sort()
            self.button_elements.sort()
            self.axis_count, self.button_count = len(self.axis_elements), len(self.button_elements)
            if not self.axis_elements:
                raise ConnectionError('This HID controller exposes no usable joystick axes.')
        except Exception:
            self.close()
            raise

    def value(self, element):
        value = ct.c_void_p()
        status = self.io.IOHIDDeviceGetValue(self.handle, element, ct.byref(value))
        if status or not value:
            raise ConnectionError(f'Joystick read failed or disconnected (HID 0x{status & 0xffffffff:08x}). Refresh after reconnecting.')
        return self.io.IOHIDValueGetIntegerValue(value)

    def read(self):
        if not self.handle:
            raise ConnectionError('Select and open a joystick first.')
        axes = [normalize_hid_axis(self.value(e), low, high) for _, _, e, low, high in self.axis_elements]
        buttons = [bool(self.value(e)) for _, _, e in self.button_elements]
        return axes, buttons

    def close(self):
        if self.handle:
            self.io.IOHIDDeviceClose(self.handle, 0)
            self.cf.CFRelease(self.handle)
            self.handle = None
        if self.elements:
            self.cf.CFRelease(self.elements)
            self.elements = None

    def shutdown(self):
        self.close()
        if self.device_set:
            self.cf.CFRelease(self.device_set)
            self.device_set = None
        for key in self.keys.values():
            self.cf.CFRelease(key)
        self.keys.clear()
        if self.manager:
            self.cf.CFRelease(self.manager)
            self.manager = None


class Joystick:
    """List SDL controllers plus native Mac HID controllers that SDL did not name.

    Each listed index maps to one backend; that backend is used once opened.
    """
    def __init__(self):
        self.native = None
        self.choices = []
        try:
            self.sdl = SDLJoystick()
        except (RuntimeError, OSError):
            if sys.platform != 'darwin':
                raise
            self.sdl = None
        self.backend = self.sdl

    @property
    def lib(self):
        return self.sdl.lib if self.sdl else None

    @property
    def handle(self):
        return self.backend.handle if self.backend else None

    def devices(self):
        # Re-enumerating also lets SDL notice that an open device was detached.
        choices = [(self.sdl, index, name) for index, name in self.sdl.devices()] if self.sdl else []
        if sys.platform == 'darwin':
            if self.native is None:
                self.native = MacHIDJoystick()
            native = self.native.devices()
            sdl_counts = Counter(name for _, _, name in choices)
            native_counts = Counter(name for _, name in native)
            # SDL gives no physical identity to match against HID records. If HID
            # sees more controllers with a name than SDL lists, list all of them so
            # the one SDL missed stays selectable.
            choices += [(self.native, index, name) for index, name in native
                        if native_counts[name] > sdl_counts[name]]
        self.choices = choices
        return [(index, name) for index, (_, _, name) in enumerate(choices)]

    def open(self, index):
        if not 0 <= index < len(self.choices):
            raise ConnectionError('Joystick list changed. Click Refresh and select it again.')
        self.close()
        self.backend, backend_index, _ = self.choices[index]
        self.backend.open(backend_index)

    def read(self):
        if self.backend is None:
            raise ConnectionError('Connect and select a joystick first.')
        return self.backend.read()

    def close(self):
        if self.backend:
            self.backend.close()

    def shutdown(self):
        if self.native:
            self.native.shutdown()
        if self.sdl:
            self.sdl.shutdown()
