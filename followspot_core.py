"""Validated settings, proportional motion and grandMA3 OSC output."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
import ipaddress
import json
import math
from pathlib import Path
import re
import socket
import struct
import threading
import time
from typing import get_type_hints


# Longest sample interval integrated as motion; longer gaps move at most this far.
MAX_STEP = 0.25
BUTTON_ACTIONS = {'command': 'MA command', 'start': 'Start output',
                  'stop': 'Stop output', 'toggle': 'Toggle output',
                  'reset': 'Reset target', 'release_marker': 'Release PSN marker'}
PSN_FIELDS = ('control_mode', 'position_output', 'psn_tracker_id', 'psn_group', 'psn_port', 'psn_interface')


def clamp(value, low, high):
    return max(low, min(high, value))


class SettingsError(ValueError):
    """A validation error with the fields an editor should highlight."""
    def __init__(self, message, *fields):
        super().__init__(message)
        self.fields = fields


@dataclass
class Settings:
    device_name: str = 'PXN-2113 Pro'
    axis_x: int = 0
    axis_y: int = 1
    axis_slider: int = 2
    zoom_enabled: bool = False
    axis_zoom: int = 3
    invert_zoom: bool = False
    centre_zoom: float = 0.0
    zoom_dead_zone: float = 0.1
    zoom_speed: float = 50.0
    initial_zoom: float = 50.0
    zoom_executor_page: int = 1
    zoom_executor_number: int = 202
    invert_x: bool = False
    invert_y: bool = True
    invert_slider: bool = False
    centre_x: float = 0.0
    centre_y: float = 0.0
    dead_zone: float = 0.1
    max_speed: float = 1.0
    z: float = 1.5
    initial_x: float = 0.0
    initial_y: float = 0.0
    reset_locked: bool = True
    test_size: float = 2.0
    test_period: float = 20.0
    test_brightness: float = 100.0
    x_min: float = -10.0
    x_max: float = 10.0
    y_min: float = -10.0
    y_max: float = 10.0
    space_x_min: float = -100.0
    space_x_max: float = 100.0
    space_y_min: float = -100.0
    space_y_max: float = 100.0
    space_z_min: float = -100.0
    space_z_max: float = 100.0
    marker_id: int = 1
    attribute_x: str = 'XYZ_X'
    attribute_y: str = 'XYZ_Y'
    attribute_z: str = 'XYZ_Z'
    executor_page: int = 1
    executor_number: int = 201
    host: str = '127.0.0.1'
    port: int = 8000
    prefix: str = ''
    position_output: str = 'osc'
    psn_tracker_id: int = 1
    psn_group: str = '236.10.10.10'
    psn_port: int = 56565
    psn_interface: str = '127.0.0.1'
    control_mode: str = 'marker'
    fixture_group: int = 1
    attribute_pan: str = 'Pan'
    attribute_tilt: str = 'Tilt'
    pan_tilt_speed: float = 25.0
    pan_min: float = 0.0
    pan_max: float = 100.0
    tilt_min: float = 0.0
    tilt_max: float = 100.0
    initial_pan: float = 50.0
    initial_tilt: float = 50.0
    test_pan_tilt_size: float = 10.0
    buttons: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError('Settings must be a JSON object.')
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f'Unknown settings: {", ".join(sorted(unknown))}')
        result = cls(**data)
        result.validate()
        return result

    def validate(self):
        for name, kind in setting_types().items():
            value = getattr(self, name)
            if kind is float:
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                    raise SettingsError(f'{name} must be a finite number.', name)
            elif kind is int:
                if type(value) is not int:
                    raise SettingsError(f'{name} must be a whole number.', name)
            elif kind is bool and type(value) is not bool:
                raise SettingsError(f'{name} must be true or false.', name)
            elif kind is str and not isinstance(value, str):
                raise SettingsError(f'{name} must be text.', name)
        if not 0 <= self.dead_zone < 0.9:
            raise SettingsError('Dead zone must be at least 0% and below 90%.', 'dead_zone')
        if not 0 < self.max_speed <= 100:
            raise SettingsError('Maximum speed must be greater than 0 and at most 100 m/s.', 'max_speed')
        if any(not -0.9 <= v <= 0.9 for v in (self.centre_x, self.centre_y)):
            raise SettingsError('Calibrate with the stick near its centre.', 'centre_x', 'centre_y')
        if min(self.axis_x, self.axis_y, self.axis_slider) < 0 or len({self.axis_x, self.axis_y, self.axis_slider}) != 3:
            raise SettingsError('Select three different, non-negative axis numbers.', 'axis_x', 'axis_y', 'axis_slider')
        if self.axis_zoom < 0 or (self.zoom_enabled and self.axis_zoom in (self.axis_x, self.axis_y, self.axis_slider)):
            raise SettingsError('Choose a separate, non-negative zoom/iris axis.', 'axis_zoom')
        if not -0.9 <= self.centre_zoom <= 0.9:
            raise SettingsError('Calibrate with the zoom/iris control near its centre.', 'centre_zoom')
        if not 0 <= self.zoom_dead_zone < 0.9:
            raise SettingsError('Zoom/iris dead zone must be at least 0% and below 90%.', 'zoom_dead_zone')
        if not 0 < self.zoom_speed <= 1000:
            raise SettingsError('Zoom/iris speed must be greater than 0 and at most 1000 percentage points/s.', 'zoom_speed')
        if not 0 <= self.initial_zoom <= 100:
            raise SettingsError('Initial zoom/iris level must be 0–100%.', 'initial_zoom')
        if min(self.zoom_executor_page, self.zoom_executor_number) < 1:
            raise SettingsError('Zoom/iris executor page and number must be positive.', 'zoom_executor_page', 'zoom_executor_number')
        if self.zoom_enabled and (self.zoom_executor_page, self.zoom_executor_number) == (self.executor_page, self.executor_number):
            raise SettingsError('Zoom/iris and brightness must use different executors.', 'zoom_executor_page', 'zoom_executor_number', 'executor_page', 'executor_number')
        for axis in ('x', 'y', 'z'):
            lo, hi = getattr(self, f'space_{axis}_min'), getattr(self, f'space_{axis}_max')
            if lo >= hi:
                raise SettingsError(f'{axis.upper()} movement-space minimum must be below maximum.', f'space_{axis}_min', f'space_{axis}_max')
            if axis != 'z':
                a, b = getattr(self, f'{axis}_min'), getattr(self, f'{axis}_max')
                initial = getattr(self, f'initial_{axis}')
                if not lo <= a < b <= hi or not a <= initial <= b:
                    raise SettingsError(f'{axis.upper()} operating limits and initial position must fit inside the movement space.', f'{axis}_min', f'{axis}_max', f'initial_{axis}', f'space_{axis}_min', f'space_{axis}_max')
            elif not lo <= self.z <= hi:
                raise SettingsError('Z height must fit inside the Z movement space.', 'z', 'space_z_min', 'space_z_max')
        if not 0 < self.test_size <= 100 or not 2 <= self.test_period <= 600 or not 0 <= self.test_brightness <= 100:
            raise SettingsError('Test size must be greater than 0 and at most 100 m, period 2–600 s and brightness 0–100%.', 'test_size', 'test_period', 'test_brightness')
        for key in ('marker_id', 'executor_page', 'executor_number'):
            if getattr(self, key) < 1:
                raise SettingsError('IDs must be positive.', key)
        if not 1 <= self.port <= 65535:
            raise SettingsError('OSC port must be 1–65535.', 'port')
        if self.position_output not in ('osc', 'psn'):
            raise SettingsError('Position output must be osc or psn.', 'position_output')
        if self.control_mode not in ('marker', 'pan_tilt'):
            raise SettingsError('Control mode must be marker or pan_tilt.', 'control_mode')
        if self.fixture_group < 1:
            raise SettingsError('Fixture group must be positive.', 'fixture_group')
        if not 0 < self.pan_tilt_speed <= 1000:
            raise SettingsError('Pan/tilt speed must be greater than 0 and at most 1000 percentage points/s.', 'pan_tilt_speed')
        for axis in ('pan', 'tilt'):
            lo, hi, initial = getattr(self, f'{axis}_min'), getattr(self, f'{axis}_max'), getattr(self, f'initial_{axis}')
            if not 0 <= lo < hi <= 100 or not lo <= initial <= hi:
                raise SettingsError(f'{axis.capitalize()} limits must be 0-100 with the minimum below the maximum, and contain the initial value.',
                                    f'{axis}_min', f'{axis}_max', f'initial_{axis}')
        if not 0 < self.test_pan_tilt_size <= 50:
            raise SettingsError('Pan/tilt test size must be greater than 0 and at most 50 percentage points.', 'test_pan_tilt_size')
        if not 1 <= self.psn_tracker_id <= 65535:
            raise SettingsError('PSN tracker ID must be 1–65535.', 'psn_tracker_id')
        if not 1 <= self.psn_port <= 65535:
            raise SettingsError('PSN port must be 1–65535.', 'psn_port')
        try:
            group_is_multicast = ipaddress.IPv4Address(self.psn_group).is_multicast
        except ValueError:
            group_is_multicast = False
        if not group_is_multicast:
            raise SettingsError('PSN group must be an IPv4 multicast address such as 236.10.10.10.', 'psn_group')
        try:
            ipaddress.IPv4Address(self.psn_interface)
        except ValueError:
            raise SettingsError('PSN interface must be an IPv4 address of this computer, for example 127.0.0.1.', 'psn_interface') from None
        if not self.host.strip() or any(c.isspace() for c in self.host) or '\0' in self.host:
            raise SettingsError('OSC host must be an IP address or hostname without spaces.', 'host')
        if self.prefix and not re.fullmatch(r'[A-Za-z0-9_.-]+', self.prefix):
            raise SettingsError('OSC prefix must contain only letters, numbers, dot, underscore or hyphen, without slashes.', 'prefix')
        for key in ('attribute_x', 'attribute_y', 'attribute_z', 'attribute_pan', 'attribute_tilt'):
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', getattr(self, key)):
                raise SettingsError('Use a valid MA attribute library name.', key)
        if not isinstance(self.buttons, dict):
            raise SettingsError('Button mappings must be an object.', 'buttons')
        for key, mapping in self.buttons.items():
            if not isinstance(key, str) or not key.isascii() or not key.isdecimal() or str(int(key)) != key:
                raise SettingsError('Button IDs must be zero-based whole numbers.', 'buttons')
            if not isinstance(mapping, dict) or set(mapping) - {'action', 'press', 'release'}:
                raise SettingsError('Each button has an action and optional press/release commands.', 'buttons')
            action = mapping.get('action', 'command')
            if not isinstance(action, str) or action not in BUTTON_ACTIONS:
                raise SettingsError('Choose a valid button action.', 'buttons')
            for command in mapping.values():
                if not isinstance(command, str) or '\0' in command or len(command.encode('utf-8')) > 4096:
                    raise SettingsError('Button commands must be text up to 4096 bytes with no null characters.', 'buttons')
            if action != 'command' and any(mapping.get(edge, '').strip() for edge in ('press', 'release')):
                raise SettingsError('Local button actions cannot also send MA commands.', 'buttons')

    def save(self, path):
        self.validate()
        path = Path(path)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(self.to_dict(), indent=2, allow_nan=False) + '\n', encoding='utf-8')
        temporary.replace(path)

    @classmethod
    def load(cls, path):
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else cls()


def setting_types():
    """Resolved field types; unlike Field.type, also correct with string annotations."""
    return get_type_hints(Settings)


def centred_axis(value, centre, invert):
    value = clamp(value, -1, 1) - centre
    value /= (1 - centre) if value >= 0 else (1 + centre)
    return -value if invert else value


class Motion:
    def __init__(self, settings):
        self.settings = settings
        self.xyz = [settings.initial_x, settings.initial_y, settings.z]
        self.zoom_level = settings.initial_zoom

    def check_axes(self, axes):
        s = self.settings
        mappings = [s.axis_x, s.axis_y, s.axis_slider]
        if s.zoom_enabled:
            mappings.append(s.axis_zoom)
        if max(mappings) >= len(axes):
            raise ValueError('An axis mapping is outside the connected joystick’s axis range.')
        if any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in axes):
            raise ValueError('Joystick reported an invalid axis value.')

    def step(self, axes, dt):
        self.check_axes(axes)
        s = self.settings
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('Invalid sample interval.')
        dt = min(dt, MAX_STEP)
        x = centred_axis(axes[s.axis_x], s.centre_x, s.invert_x)
        y = centred_axis(axes[s.axis_y], s.centre_y, s.invert_y)
        radius = math.hypot(x, y)
        speed = max(0.0, min(1.0, (radius - s.dead_zone) / (1 - s.dead_zone))) * s.max_speed
        if radius:
            self.xyz[0] = clamp(self.xyz[0] + x / radius * speed * dt, s.x_min, s.x_max)
            self.xyz[1] = clamp(self.xyz[1] + y / radius * speed * dt, s.y_min, s.y_max)
        self.xyz[2] = s.z
        if s.zoom_enabled:
            value = centred_axis(axes[s.axis_zoom], s.centre_zoom, s.invert_zoom)
            speed = max(0.0, min(1.0, (abs(value) - s.zoom_dead_zone) / (1 - s.zoom_dead_zone))) * s.zoom_speed
            self.zoom_level = clamp(self.zoom_level + math.copysign(speed, value) * dt, 0, 100)

    def brightness(self, axes):
        self.check_axes(axes)
        v = clamp((axes[self.settings.axis_slider] + 1) * 50, 0, 100)
        return 100 - v if self.settings.invert_slider else v


def figure_eight(s, t):
    """Test-mode target: a figure 8 centred on the initial X/Y, kept inside the operating limits."""
    phase = 2 * math.pi * t / s.test_period
    return [clamp(s.initial_x + s.test_size * math.sin(phase), s.x_min, s.x_max),
            clamp(s.initial_y + s.test_size / 2 * math.sin(2 * phase), s.y_min, s.y_max), s.z]


def learn_axis(before, after, threshold=0.3):
    if len(before) != len(after) or not before:
        return None
    changes = [abs(a - b) for a, b in zip(before, after)]
    index = max(range(len(changes)), key=changes.__getitem__)
    return index if changes[index] >= threshold else None


def marker_commands(s, xyz):
    # MA requires selection and attribute assignment as separate commands.
    # ClearSelection preserves programmer values and isolates the target marker.
    commands = ['ClearSelection', f'MArker {s.marker_id}']
    for axis, value in zip(('x', 'y', 'z'), xyz):
        lo, hi = getattr(s, f'space_{axis}_min'), getattr(s, f'space_{axis}_max')
        percent = clamp((value - lo) / (hi - lo) * 100, 0, 100)
        attr = getattr(s, f'attribute_{axis}')
        commands.append(f'Attribute "{attr}" At Absolute Percent {percent:.6f}')
    return commands


def osc_string(value):
    if '\0' in value:
        raise ValueError('OSC strings cannot contain null characters.')
    data = value.encode('utf-8') + b'\0'
    return data + b'\0' * (-len(data) % 4)


def osc_packet(address, value):
    if not address.startswith('/'):
        raise ValueError('OSC address must start with /.')
    if isinstance(value, str):
        return osc_string(address) + osc_string(',s') + osc_string(value)
    if not math.isfinite(value):
        raise ValueError('OSC numeric values must be finite.')
    return osc_string(address) + osc_string(',f') + struct.pack('>f', value)


PSN_DATA, PSN_INFO = 0x6755, 0x6756


def psn_chunk(chunk_id, payload, has_children=False):
    """One PSN chunk: header is id | length << 16 | has_children << 31, little-endian."""
    if len(payload) > 0x7FFF:
        raise ValueError('PSN chunk payload is too long.')
    return struct.pack('<I', chunk_id | len(payload) << 16 | int(has_children) << 31) + payload


def _psn_header(timestamp_us, frame):
    # Version 2.0, one packet per frame.
    return psn_chunk(0x0000, struct.pack('<QBBBB', timestamp_us, 2, 0, frame & 255, 1))


def psn_data_packet(tracker_id, xyz, timestamp_us, frame):
    position = psn_chunk(0x0000, struct.pack('<3f', *xyz))
    trackers = psn_chunk(0x0001, psn_chunk(tracker_id, position, True), True)
    return psn_chunk(PSN_DATA, _psn_header(timestamp_us, frame) + trackers, True)


def psn_info_packet(system_name, tracker_id, tracker_name, timestamp_us, frame):
    name = psn_chunk(0x0000, tracker_name.encode('utf-8'))
    trackers = psn_chunk(0x0002, psn_chunk(tracker_id, name, True), True)
    return psn_chunk(PSN_INFO, _psn_header(timestamp_us, frame)
                     + psn_chunk(0x0001, system_name.encode('utf-8')) + trackers, True)


PSN_RATE = 30.0
PSN_SYSTEM_NAME = 'Followspot'


class PsnStreamer:
    """Streams one tracker's latest position as PSN at about 30 Hz.

    A stopped stream makes onPC reset the MArker to 0, 0, 0, so the thread
    keeps sending even while the joystick is idle. Errors are stored for
    the window's poll; nothing is raised into the Tk callback.
    """
    def __init__(self, settings, xyz, sock=None, clock=time.monotonic, start=True):
        self.destination = (settings.psn_group, settings.psn_port)
        self.tracker_id = settings.psn_tracker_id
        self.clock = clock
        self.began = clock()
        self.lock = threading.Lock()
        self._xyz = tuple(xyz)
        self._error = None
        self.frame = 0
        self.last_info = None
        self.stopping = threading.Event()
        self.thread = None
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(settings.psn_interface))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            except OSError:
                sock.close()
                raise
        self.socket = sock
        if start:
            self.thread = threading.Thread(target=self._run, name='psn-stream', daemon=True)
            self.thread.start()

    @property
    def position(self):
        with self.lock:
            return self._xyz

    def set_position(self, xyz):
        with self.lock:
            self._xyz = tuple(xyz)

    def poll_error(self):
        with self.lock:
            error, self._error = self._error, None
        return error

    def step(self):
        now = self.clock()
        timestamp = int((now - self.began) * 1_000_000)
        if self.last_info is None or now - self.last_info >= 1.0:
            self.socket.sendto(psn_info_packet(PSN_SYSTEM_NAME, self.tracker_id, PSN_SYSTEM_NAME,
                                               timestamp, self.frame), self.destination)
            self.last_info = now
        self.socket.sendto(psn_data_packet(self.tracker_id, self.position, timestamp, self.frame), self.destination)
        self.frame += 1

    def _run(self):
        while not self.stopping.is_set():
            try:
                self.step()
            except Exception as exc:
                with self.lock:
                    self._error = exc
                return
            self.stopping.wait(1 / PSN_RATE)

    def close(self):
        self.stopping.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=1.0)
        self.socket.close()


class OscSender:
    def __init__(self, host, port, prefix=''):
        # Resolve once when starting, not inside the 30 Hz UI callback.
        self.destination = (socket.gethostbyname(host), port)
        self.prefix = '/' + prefix if prefix else ''
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)

    def send(self, address, value):
        self.socket.sendto(osc_packet(self.prefix + address, value), self.destination)

    def close(self):
        self.socket.close()


class ButtonEdges:
    """The single press/release tracker, observed whether or not output runs.

    Seeding with a fresh snapshot makes buttons already held unobserved until
    they are released and pressed again.
    """
    def __init__(self):
        self.previous = None

    def seed(self, buttons):
        self.previous = list(buttons)

    def sample(self, buttons):
        previous = self.previous
        self.seed(buttons)
        if previous is None or len(previous) != len(buttons):
            return [], []
        presses = [i for i, (old, new) in enumerate(zip(previous, buttons)) if new and not old]
        releases = [i for i, (old, new) in enumerate(zip(previous, buttons)) if old and not new]
        return presses, releases


def button_action(mappings, index):
    return mappings.get(str(index), {}).get('action', 'command')


def local_actions(presses, mappings):
    return [action for action in (button_action(mappings, i) for i in presses) if action != 'command']


class Controller:
    def __init__(self, settings, send, send_position=None):
        settings.validate()
        if settings.position_output == 'psn' and send_position is None:
            raise ValueError('PSN position output needs a position callback.')
        self.settings = settings
        self.motion = Motion(settings)
        self.send = send
        self.send_position = send_position
        self.active = False
        self.test = False
        self.test_time = 0.0
        self.pressed = set()
        self.last_commands = None
        self.last_brightness = None
        self.last_zoom = None

    @contextmanager
    def _stop_on_failure(self):
        try:
            yield
        except Exception as exc:
            errors = self.stop()
            if errors:
                raise RuntimeError(f'{exc}; Release send failed: {"; ".join(errors)}') from exc
            raise

    def start(self, axes=None, test=False):
        """Test mode needs no joystick: it drives a figure 8 at a fixed brightness."""
        if not test:
            self.motion.check_axes(axes)
        if self.active:
            raise ValueError('Output is already active.')
        self.test, self.test_time = test, 0.0
        if test:
            self.motion.xyz = figure_eight(self.settings, 0)
        self.pressed.clear()
        self.last_commands = self.last_brightness = self.last_zoom = None
        self.active = True
        with self._stop_on_failure():
            self._output(axes)

    def _output_position(self):
        if self.settings.position_output == 'psn':
            # The streamer keeps sending; the selection is never touched.
            self.send_position(tuple(self.motion.xyz))
            return
        commands = marker_commands(self.settings, self.motion.xyz)
        if commands != self.last_commands:
            # Keep selection and XYZ assignments in one OSC command string.
            # MA does not accept OSC bundles.
            self.send('/cmd', '; '.join(commands))
            self.last_commands = commands

    def _output(self, axes):
        self._output_position()
        level = round(self.settings.test_brightness if self.test else self.motion.brightness(axes), 1)
        if level != self.last_brightness:
            s = self.settings
            self.send(f'/Page{s.executor_page}/Fader{s.executor_number}', level)
            self.last_brightness = level
        self._output_zoom()

    def _output_zoom(self):
        s = self.settings
        if s.zoom_enabled:
            level = round(self.motion.zoom_level, 1)
            if level != self.last_zoom:
                self.send(f'/Page{s.zoom_executor_page}/Fader{s.zoom_executor_number}', level)
                self.last_zoom = level

    def reset_target(self):
        if self.active and self.settings.reset_locked:
            return False
        s = self.settings
        self.motion.xyz = [s.initial_x, s.initial_y, s.z]
        self.motion.zoom_level = s.initial_zoom
        if self.active:
            with self._stop_on_failure():
                # An explicit Reset also resends a target already at home.
                self.last_commands = None
                self._output_position()
                self.last_zoom = None
                self._output_zoom()
        return True

    def tick(self, axes, dt, presses=(), releases=()):
        """Move, output, then send MA commands for this sample's button edges."""
        if not self.active:
            return
        with self._stop_on_failure():
            if self.test:
                self.test_time += min(max(dt, 0), MAX_STEP)
                self.motion.xyz = figure_eight(self.settings, self.test_time)
            else:
                self.motion.step(axes, dt)
            self._output(axes)
            for index in sorted([*presses, *releases]):
                mapping = self.settings.buttons.get(str(index), {})
                if index in presses:
                    if mapping.get('action', 'command') != 'command':
                        continue
                    # Own every observed press, including release-only mappings.
                    # Buttons held at Start are not observed presses and stay unowned.
                    self.pressed.add(index)
                    command = mapping.get('press', '').strip()
                    if command:
                        self.send('/cmd', command)
                elif index in self.pressed:
                    command = mapping.get('release', '').strip()
                    if command:
                        self.send('/cmd', command)
                    self.pressed.discard(index)

    def stop(self):
        self.active = False
        errors = []
        for index in sorted(self.pressed):
            command = self.settings.buttons.get(str(index), {}).get('release', '').strip()
            if command:
                try:
                    self.send('/cmd', command)
                except Exception as exc:
                    errors.append(str(exc))
        self.pressed.clear()
        return errors
