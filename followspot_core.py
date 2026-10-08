"""Validated settings, proportional motion and grandMA3 OSC output."""
from dataclasses import asdict, dataclass, field, fields
import json
import math
from pathlib import Path
import re
import socket
import struct


def clamp(value, low, high):
    return max(low, min(high, value))


@dataclass
class Settings:
    device_name: str = 'PXN-2113 Pro'
    axis_x: int = 0
    axis_y: int = 1
    axis_slider: int = 2
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
        for f in fields(self):
            value = getattr(self, f.name)
            if f.type is float:
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                    raise ValueError(f'{f.name} must be a finite number.')
            elif f.type is int:
                if type(value) is not int:
                    raise ValueError(f'{f.name} must be a whole number.')
            elif f.type is bool and type(value) is not bool:
                raise ValueError(f'{f.name} must be true or false.')
            elif f.type is str and not isinstance(value, str):
                raise ValueError(f'{f.name} must be text.')
        if not 0 <= self.dead_zone < 0.9 or not 0 < self.max_speed <= 100:
            raise ValueError('Dead zone must be 0–0.89; maximum speed must be greater than 0 and at most 100 m/s.')
        if any(not -0.9 <= v <= 0.9 for v in (self.centre_x, self.centre_y)):
            raise ValueError('Calibrate with the stick near its centre.')
        if min(self.axis_x, self.axis_y, self.axis_slider) < 0 or len({self.axis_x, self.axis_y, self.axis_slider}) != 3:
            raise ValueError('Select three different, non-negative axis numbers.')
        for axis in ('x', 'y', 'z'):
            lo, hi = getattr(self, f'space_{axis}_min'), getattr(self, f'space_{axis}_max')
            if lo >= hi:
                raise ValueError(f'{axis.upper()} movement-space minimum must be below maximum.')
            if axis != 'z':
                a, b = getattr(self, f'{axis}_min'), getattr(self, f'{axis}_max')
                initial = getattr(self, f'initial_{axis}')
                if not lo <= a < b <= hi or not a <= initial <= b:
                    raise ValueError(f'{axis.upper()} operating limits and initial position must fit inside the movement space.')
            elif not lo <= self.z <= hi:
                raise ValueError('Z height must fit inside the Z movement space.')
        if min(self.marker_id, self.executor_page, self.executor_number) < 1 or not 1 <= self.port <= 65535:
            raise ValueError('IDs must be positive; OSC port must be 1–65535.')
        if not self.host.strip() or any(c.isspace() for c in self.host) or '\0' in self.host:
            raise ValueError('OSC host must be an IP address or hostname without spaces.')
        if self.prefix and not re.fullmatch(r'[A-Za-z0-9_.-]+', self.prefix):
            raise ValueError('OSC prefix must contain only letters, numbers, dot, underscore or hyphen, without slashes.')
        for name in (self.attribute_x, self.attribute_y, self.attribute_z):
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
                raise ValueError('Use a valid MA attribute library name.')
        if not isinstance(self.buttons, dict):
            raise ValueError('Button mappings must be an object.')
        for key, mapping in self.buttons.items():
            if not isinstance(key, str) or not key.isascii() or not key.isdecimal() or str(int(key)) != key:
                raise ValueError('Button IDs must be zero-based whole numbers.')
            if not isinstance(mapping, dict) or set(mapping) - {'press', 'release'}:
                raise ValueError('Each button has press and release commands.')
            for command in mapping.values():
                if not isinstance(command, str) or '\0' in command or len(command.encode('utf-8')) > 4096:
                    raise ValueError('Button commands must be text up to 4096 bytes with no null characters.')

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


def centred_axis(value, centre, invert):
    value = clamp(value, -1, 1) - centre
    value /= (1 - centre) if value >= 0 else (1 + centre)
    return -value if invert else value


class Motion:
    def __init__(self, settings):
        self.settings = settings
        self.xyz = [settings.initial_x, settings.initial_y, settings.z]

    def check_axes(self, axes):
        s = self.settings
        if max(s.axis_x, s.axis_y, s.axis_slider) >= len(axes):
            raise ValueError('An axis mapping is outside the connected joystick’s axis range.')
        if any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in axes):
            raise ValueError('Joystick reported an invalid axis value.')

    def step(self, axes, dt):
        self.check_axes(axes)
        s = self.settings
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('Invalid sample interval.')
        if dt > 0.25:
            return
        x = centred_axis(axes[s.axis_x], s.centre_x, s.invert_x)
        y = centred_axis(axes[s.axis_y], s.centre_y, s.invert_y)
        radius = math.hypot(x, y)
        speed = max(0.0, min(1.0, (radius - s.dead_zone) / (1 - s.dead_zone))) * s.max_speed
        if radius:
            self.xyz[0] = clamp(self.xyz[0] + x / radius * speed * dt, s.x_min, s.x_max)
            self.xyz[1] = clamp(self.xyz[1] + y / radius * speed * dt, s.y_min, s.y_max)
        self.xyz[2] = s.z

    def brightness(self, axes):
        self.check_axes(axes)
        v = clamp((axes[self.settings.axis_slider] + 1) * 50, 0, 100)
        return 100 - v if self.settings.invert_slider else v


def learn_axis(before, after, threshold=0.3):
    if len(before) != len(after) or not before:
        return None
    changes = [abs(a - b) for a, b in zip(before, after)]
    index = max(range(len(changes)), key=changes.__getitem__)
    return index if changes[index] >= threshold else None


def marker_commands(s, xyz):
    commands = []
    for axis, value in zip(('x', 'y', 'z'), xyz):
        lo, hi = getattr(s, f'space_{axis}_min'), getattr(s, f'space_{axis}_max')
        percent = clamp((value - lo) / (hi - lo) * 100, 0, 100)
        attr = getattr(s, f'attribute_{axis}')
        commands.append(f'MArker {s.marker_id} Attribute "{attr}" At Absolute Percent {percent:.6f}')
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


class Controller:
    def __init__(self, settings, send):
        settings.validate()
        self.settings = settings
        self.motion = Motion(settings)
        self.send = send
        self.active = False
        self.previous_buttons = []
        self.pressed = set()
        self.last_commands = None
        self.last_brightness = None

    def start(self, axes, buttons):
        self.motion.check_axes(axes)
        if self.active:
            raise ValueError('Output is already active.')
        self.previous_buttons = list(buttons)
        self.pressed.clear()
        self.last_commands = self.last_brightness = None
        self.active = True
        try:
            self._output(axes)
        except Exception as exc:
            errors = self.stop()
            if errors:
                raise RuntimeError(f'{exc}; Release send failed: {"; ".join(errors)}') from exc
            raise

    def _output(self, axes):
        commands = marker_commands(self.settings, self.motion.xyz)
        if commands != self.last_commands:
            # One message, three explicit selections. MA does not accept OSC bundles.
            self.send('/cmd', '; '.join(commands))
            self.last_commands = commands
        level = round(self.motion.brightness(axes), 1)
        if level != self.last_brightness:
            s = self.settings
            self.send(f'/Page{s.executor_page}/Fader{s.executor_number}', level)
            self.last_brightness = level

    def tick(self, axes, buttons, dt):
        if not self.active:
            return
        try:
            if len(buttons) != len(self.previous_buttons):
                raise ValueError('Joystick button count changed; restart output.')
            self.motion.step(axes, dt)
            self._output(axes)
            for index, (old, new) in enumerate(zip(self.previous_buttons, buttons)):
                mapping = self.settings.buttons.get(str(index), {})
                if new and not old:
                    # Own every observed press, including release-only mappings.
                    # Buttons held at Start are not observed presses and stay unowned.
                    self.pressed.add(index)
                    command = mapping.get('press', '').strip()
                    if command:
                        self.send('/cmd', command)
                elif old and not new and index in self.pressed:
                    command = mapping.get('release', '').strip()
                    if command:
                        self.send('/cmd', command)
                    self.pressed.discard(index)
            self.previous_buttons = list(buttons)
        except Exception as exc:
            errors = self.stop()
            if errors:
                raise RuntimeError(f'{exc}; Release send failed: {"; ".join(errors)}') from exc
            raise

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
