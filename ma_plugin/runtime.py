"""Transport adapter and lifecycle for the grandMA3 plugin's embedded helper."""
import copy
import math
import time

from followspot_core import (ButtonEdges, Controller, PSN_FIELDS, PsnStreamer, Settings,
    clamp, figure_eight, learn_axis, local_actions, pan_tilt_commands)
from joystick import Joystick


PROTOCOL = 'FOLLOWSPOT_PLUGIN_1'
VERSION = '1.0.0'


def normalize(config):
    if not isinstance(config, dict) or set(config) - {'settings', 'output_mode'}:
        raise ValueError('Invalid plugin configuration.')
    mode = config.get('output_mode', 'direct')
    if mode not in ('direct', 'psn'):
        raise ValueError('Position output must be direct or psn.')
    data = copy.deepcopy(config.get('settings', {}))
    # OSC settings are intentionally not part of the plugin's transport.
    for key in ('host', 'port', 'prefix', 'position_output'):
        data.pop(key, None)
    data['position_output'] = 'psn' if mode == 'psn' else 'osc'
    settings = Settings.from_dict(data)
    if mode == 'psn' and settings.control_mode != 'marker':
        raise ValueError('PSN requires MArker control mode.')
    return settings, dict(settings={k: v for k, v in settings.to_dict().items()
        if k not in ('host', 'port', 'prefix', 'position_output')}, output_mode=mode)


class NativeController(Controller):
    def __init__(self, settings, owner):
        self.owner = owner
        self.command_context = []
        super().__init__(settings, self.send_native, owner.position)

    def _output_position(self):
        s = self.settings
        if s.control_mode == 'pan_tilt':
            self.owner.publish(target=dict(kind='pan_tilt', values=self.motion.pan_tilt[:],
                command='; '.join(pan_tilt_commands(s, self.motion.pan_tilt))))
        elif s.position_output == 'psn':
            self.owner.position(tuple(self.motion.xyz))
        else:
            percent = [clamp((value - getattr(s, f'space_{axis}_min')) /
                (getattr(s, f'space_{axis}_max') - getattr(s, f'space_{axis}_min')) * 100, 0, 100)
                for axis, value in zip('xyz', self.motion.xyz)]
            self.owner.publish(target=dict(kind='marker', xyz=self.motion.xyz[:], percent=percent))

    def send_native(self, address, value):
        if address == '/cmd':
            if not self.command_context or self.command_context[0]['command'] != value:
                raise RuntimeError('Unexpected native button output.')
            self.owner.enqueue(**self.command_context.pop(0))
        elif address == f'/Page{self.settings.executor_page}/Fader{self.settings.executor_number}':
            self.owner.publish(brightness=value)
        elif address == f'/Page{self.settings.zoom_executor_page}/Fader{self.settings.zoom_executor_number}':
            self.owner.publish(zoom=value)
        else:
            raise ValueError('Unknown native output address: ' + address)

    def button_event(self, index, release):
        mapping = self.settings.buttons.get(str(index), {})
        press, off = mapping.get('press', '').strip(), mapping.get('release', '').strip()
        return dict(command=off if release else press, owner=f'{self.owner.generation}:{index}',
                    release=release, paired=bool(press), release_command=off)

    def tick(self, axes, dt, presses=(), releases=()):
        # Carry edge identity across the OSC-shaped core callback. Comparing command
        # text cannot distinguish identical press/release commands or two buttons.
        self.command_context = []
        for index in sorted([*presses, *releases]):
            mapping = self.settings.buttons.get(str(index), {})
            release = index not in presses
            if ((not release and mapping.get('action', 'command') == 'command') or
                    (release and index in self.pressed)):
                event = self.button_event(index, release)
                if event['command']: self.command_context.append(event)
        try: return super().tick(axes, dt, presses, releases)
        finally: self.command_context = []

    def stop(self):
        previous = self.command_context
        self.command_context = [self.button_event(i, True) for i in sorted(self.pressed)
                                if self.settings.buttons.get(str(i), {}).get('release', '').strip()]
        try: errors = super().stop()
        finally: self.command_context = previous
        if errors:
            self.owner.warning = 'Release commands failed: ' + '; '.join(errors)
        return errors


class PluginRuntime:
    def __init__(self, config, input_factory=Joystick, stream_factory=PsnStreamer, clock=time.monotonic):
        self.settings, self.config = normalize(config)
        self.input_factory, self.stream_factory, self.clock = input_factory, stream_factory, clock
        self.input, self.stream = None, None
        self.devices, self.axes, self.buttons = [], [], []
        self.edges = ButtonEdges()
        self.frame, self.frame_seq, self.generation = None, 0, 0
        self.events, self.event_seq, self.acked = [], 0, 0
        self.fault, self.warning, self.message = '', '', 'Stopped — choose a joystick or run a test.'
        self.learning, self.learned, self.learn_seq = None, None, 0
        self.controller = NativeController(self.settings, self)
        self.closed = False

    def publish(self, **values):
        previous = self.frame or {}
        if previous.get('generation') == self.generation and all(previous.get(k) == v for k, v in values.items()):
            return
        self.frame_seq += 1
        self.frame = dict(previous, **copy.deepcopy(values), seq=self.frame_seq, generation=self.generation)

    def enqueue(self, command, owner, release=False, paired=False, release_command=''):
        if len(self.events) >= 64:
            raise RuntimeError('MA command queue is full; check the plugin connection.')
        self.event_seq += 1
        self.events.append(dict(id=self.event_seq, command=command, owner=owner, paired=paired,
                                release_command=release_command, release=release,generation=self.generation))

    def acknowledge(self, event_id):
        if type(event_id) is not int or not self.acked <= event_id <= self.event_seq:
            raise ValueError('Invalid command acknowledgement.')
        self.acked = event_id
        self.events = [e for e in self.events if e['id'] > event_id]

    def position(self, xyz):
        if self.stream is None:
            raise RuntimeError('PSN stream is not open.')
        self.stream.set_position(xyz)
        self.publish(target=dict(kind='psn', xyz=list(xyz)))

    def stopped_only(self):
        if self.controller.active:
            raise ValueError('Stop output before changing setup.')

    def stop(self):
        errors = self.controller.stop()
        if errors: self.warning = 'Release commands failed: ' + '; '.join(errors)
        self.learning = None
        self.message = 'PSN HOLDING — last position streaming.' if self.stream else 'Stopped — target and levels retained.'

    def fail(self, detail, input_lost=False):
        self.stop()
        self.fault = str(detail)
        if input_lost and self.input:
            self.input.close()
            self.edges = ButtonEdges()

    def release(self):
        self.stop()
        if self.stream:
            stream, self.stream = self.stream, None
            stream.close()
            self.message = 'PSN released — MA can return the MArker to origin.'

    def reset(self):
        if not self.controller.reset_target():
            self.message = 'Reset is locked while running.'
            return False
        if self.controller.active:
            self.publish(force_position=self.frame_seq + 1)
        self.message = 'Target and zoom/iris reset; brightness retained.'
        return True

    def start(self, test=False):
        if self.controller.active: return
        if self.learning: raise ValueError('Finish or cancel learning before Start.')
        if not test:
            if not self.input or not self.input.handle:
                raise ValueError('Refresh and open a joystick first, or use Test figure eight.')
            try: self.axes, self.buttons = self.input.read()
            except Exception as exc:
                self.fail(exc,input_lost=True)
                raise
            self.edges.seed(self.buttons)
            self.controller.motion.check_axes(self.axes)
        new_stream = False
        try:
            if self.settings.position_output == 'psn' and not self.stream:
                seed = figure_eight(self.settings, 0) if test else self.controller.motion.xyz
                self.stream = self.stream_factory(self.settings, seed)
                new_stream = True
            self.generation += 1
            self.controller.start(self.axes, test=test)
        except Exception:
            self.stop()
            if new_stream:
                stream, self.stream = self.stream, None
                stream.close()
            raise
        self.fault = ''
        self.message = 'Test figure eight running.' if test else 'Joystick output running.'

    def configure(self, config):
        self.stopped_only()
        settings, normalized = normalize(config)
        if self.stream and any(getattr(settings, key) != getattr(self.settings, key) for key in PSN_FIELDS):
            raise ValueError('Release the PSN marker before changing its output settings.')
        motion = self.controller.motion
        controller = NativeController(settings, self)
        controller.motion.xyz = motion.xyz[:]
        controller.motion.pan_tilt = motion.pan_tilt[:]
        if settings.control_mode=='marker':
            controller.motion.xyz = [clamp(motion.xyz[0], settings.x_min, settings.x_max),
                                     clamp(motion.xyz[1], settings.y_min, settings.y_max), settings.z]
        else:
            controller.motion.pan_tilt = [clamp(motion.pan_tilt[0], settings.pan_min, settings.pan_max),
                                          clamp(motion.pan_tilt[1], settings.tilt_min, settings.tilt_max)]
        controller.motion.zoom_level = motion.zoom_level
        self.settings, self.config, self.controller = settings, normalized, controller
        self.edges.seed(self.buttons)
        self.message = 'Settings applied. Review the Start preview.'

    def command(self, action, payload=None):
        payload = payload or {}
        if action == 'configure': self.configure(payload['config'])
        elif action == 'start': self.start()
        elif action == 'test': self.start(test=True)
        elif action == 'stop': self.stop()
        elif action == 'release': self.release()
        elif action == 'reset': self.reset()
        elif action == 'reset_lock':
            if type(payload.get('locked')) is not bool: raise ValueError('Reset lock must be true or false.')
            self.settings.reset_locked = payload['locked']
            self.config['settings']['reset_locked'] = payload['locked']
        elif action == 'refresh':
            self.stopped_only()
            if not self.input: self.input = self.input_factory()
            self.input.close()
            self.devices = [dict(index=i, name=name) for i, name in self.input.devices()]
            self.edges = ButtonEdges()
            self.message = f'{len(self.devices)} joystick entries found. Select and open one.'
        elif action == 'select':
            self.stopped_only()
            matches = [d for d in self.devices if d['index'] == payload.get('index') and d['name'] == payload.get('name')]
            if not self.input or len(matches) != 1: raise ValueError('Device list changed; Refresh and select again.')
            self.input.open(matches[0]['index'])
            try: self.axes, self.buttons = self.input.read()
            except Exception:
                self.input.close()
                raise
            self.edges.seed(self.buttons)
            self.config['settings']['device_name'] = matches[0]['name']
            self.settings.device_name = matches[0]['name']
            self.fault = ''
            self.message = 'Opened ' + matches[0]['name']
        elif action == 'learn':
            self.stopped_only()
            if not self.input or not self.input.handle: raise ValueError('Open a joystick before learning.')
            key = payload.get('key')
            if key not in ('axis_x', 'axis_y', 'axis_slider', 'axis_zoom', 'button'):
                raise ValueError('Unknown learning control.')
            self.learning = dict(key=key, axes=self.axes[:], buttons=self.buttons[:], until=self.clock() + 10)
            self.edges.seed(self.buttons)
            self.message = 'Learning: move only the requested control (10 seconds).'
        elif action == 'cancel_learn':
            self.learning = None
            self.edges.seed(self.buttons)
        elif action == 'calibrate':
            self.stopped_only()
            if not self.input or not self.input.handle: raise ValueError('Open a joystick before calibration.')
            values = {}
            for key in payload.get('keys', ['x', 'y']):
                if key not in ('x', 'y', 'zoom'): raise ValueError('Invalid calibration control.')
                axis = payload.get('axis_' + key, getattr(self.settings, 'axis_' + key))
                if type(axis) is not int or not 0 <= axis < len(self.axes): raise ValueError('Axis is out of range.')
                if abs(self.axes[axis]) > .9: raise ValueError('Centre the control before calibrating.')
                values['centre_' + key] = self.axes[axis]
            self.learn_seq += 1
            self.learned = dict(id=self.learn_seq, values=values)
            self.edges.seed(self.buttons)
        elif action == 'fault': self.fail(payload.get('detail', 'Native MA output failed.'))
        elif action == 'ack_warning': self.warning = ''
        elif action == 'shutdown': self.close()
        else: raise ValueError('Unknown plugin action: ' + str(action))

    def tick(self, dt):
        if self.closed: return
        try:
            if self.stream:
                error = self.stream.poll_error()
                if error:
                    self.release()
                    raise RuntimeError('PSN: ' + str(error))
            if self.controller.active and self.controller.test:
                self.controller.tick(None, min(dt, max(0, self.settings.test_period - self.controller.test_time)))
                if self.controller.test_time >= self.settings.test_period - 1e-8:
                    self.stop()
                    self.message = 'Test complete. ' + self.message
                return
            if not self.input or not self.input.handle: return
            try: self.axes, self.buttons = self.input.read()
            except Exception as exc:
                self.fail(exc, input_lost=True)
                return
            if self.learning:
                item = self.learning
                self.edges.seed(self.buttons)
                if item['key'] == 'button':
                    found = next((i for i, (a, b) in enumerate(zip(item['buttons'], self.buttons)) if b and not a), None)
                else: found = learn_axis(item['axes'], self.axes)
                if found is not None:
                    self.learn_seq += 1
                    self.learned = dict(id=self.learn_seq, values={item['key']: found})
                    self.learning = None
                    self.message = 'Learned control. Save settings to apply the draft.'
                elif self.clock() >= item['until']:
                    self.learning = None
                    self.message = 'Learning timed out; mapping unchanged.'
                return
            presses, releases = self.edges.sample(self.buttons)
            actions = local_actions(presses, self.settings.buttons)
            stopping = 'stop' in actions or ('toggle' in actions and self.controller.active)
            releasing = 'release_marker' in actions and self.stream is not None
            if stopping: self.stop()
            if releasing: self.release()
            if stopping or releasing: return
            if not self.controller.active and ('start' in actions or 'toggle' in actions):
                self.start()
                return
            if 'reset' in actions and self.reset(): dt = 0
            self.controller.tick(self.axes, dt, presses, releases)
        except Exception as exc:
            self.fail(exc)

    def snapshot(self):
        preview_level = self.frame.get('brightness') if self.frame else None
        if not self.controller.active and self.axes:
            try: preview_level = self.controller.motion.brightness(self.axes)
            except ValueError: pass
        return copy.deepcopy(dict(protocol=PROTOCOL, version=VERSION, config=self.config,
            running=self.controller.active, test=self.controller.test and self.controller.active,
            holding=self.stream is not None, held_xyz=list(self.stream.position) if self.stream else None,
            device_open=bool(self.input and self.input.handle), devices=self.devices,
            axes=self.axes, buttons=self.buttons, frame=self.frame, events=self.events,
            fault=self.fault, warning=self.warning, message=self.message,
            learning=self.learning['key'] if self.learning else None, learned=self.learned,
            preview=dict(xyz=self.controller.motion.xyz[:], pan_tilt=self.controller.motion.pan_tilt[:],
                         brightness=preview_level, zoom=self.controller.motion.zoom_level)))

    def close(self):
        try: self.release()
        finally:
            self.closed = True
            if self.input: self.input.shutdown()
