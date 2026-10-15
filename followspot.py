#!/usr/bin/env python3
"""Small joystick-to-grandMA3 controller. Run directly or use the launcher."""
import argparse
from dataclasses import replace
from decimal import Decimal
import json
import math
from pathlib import Path
import sys
import time

from followspot_core import (BUTTON_ACTIONS, PSN_FIELDS, ButtonEdges, Controller, OscSender, PsnStreamer, Settings,
                              SettingsError, clamp, learn_axis, local_actions, setting_types)
from followspot_ui import PERCENT_FIELDS, FollowspotView, axis_name, display_value
from joystick import Joystick

SETTINGS_PATH = Path(__file__).resolve().with_name('settings.json')


def settings_from_values(values, buttons):
    data = {}
    for name, kind in setting_types().items():
        if name == 'buttons':
            continue
        value = values[name].get()
        try:
            data[name] = value if kind is bool else kind(value)
            if name in PERCENT_FIELDS and math.isfinite(data[name]):
                data[name] = float(Decimal(str(value)) / 100)
        except (ValueError, TypeError):
            raise SettingsError(f'Enter a valid {"whole number" if kind is int else "number"}.', name) from None
    data['buttons'] = buttons
    return Settings.from_dict(data)


class App:
    def __init__(self, root, settings_path=SETTINGS_PATH):
        import tkinter as tk
        from tkinter import ttk, messagebox
        self.root, self.tk, self.ttk, self.messagebox = root, tk, ttk, messagebox
        self.settings_path = Path(settings_path)
        self.sender = None
        self.streamer = None
        self.joystick = None
        self.controller = None
        self.learning = None
        self.axes, self.buttons = [], []
        self.button_edges = ButtonEdges()
        self.device_choices = []
        self.last_tick = time.monotonic()
        self.last_ui = 0
        self.root.title('Joystick Followspot · grandMA3')
        self.root.geometry('860x740')
        self.root.minsize(760, 660)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        if root.tk.call('tk', 'windowingsystem') == 'aqua':
            # Cmd-Q and the app menu's Quit otherwise bypass the close confirmation.
            root.createcommand('::tk::mac::Quit', self.close)
        try:
            self.settings = Settings.load(self.settings_path)
        except (ValueError, OSError) as exc:
            # Do not fall back silently and allow output against unintended IDs.
            messagebox.showerror('Settings could not be loaded', f'{exc}\n\nCorrect or rename {self.settings_path.name}, then restart.')
            root.destroy()
            return
        self.controller = Controller(self.settings, self.send, self.send_position)
        self.draft_buttons = json.loads(json.dumps(self.settings.buttons))
        self.values = {}
        for name, kind in setting_types().items():
            if name != 'buttons':
                variable = tk.BooleanVar if kind is bool else tk.StringVar
                self.values[name] = variable(value=display_value(name, getattr(self.settings, name)))
        self.status = tk.StringVar(value='Output stopped. Review Setup before starting.')
        self.faults = {}
        self.fault_label = tk.StringVar()
        self.output_label = tk.StringVar(value='OUTPUT STOPPED')
        self.device_label = tk.StringVar(value='No joystick connected')
        self.position_label = tk.StringVar()
        self.brightness_label = tk.StringVar(value='Brightness —')
        self.zoom_label = tk.StringVar()
        self.axes_label = tk.StringVar(value='Axes —')
        self.buttons_label = tk.StringVar(value='Buttons —')
        self.build_window()
        try:
            self.joystick = Joystick()
            self.refresh_devices()
        except (OSError, RuntimeError) as exc:
            self.status.set(str(exc))
            self.record_fault('input', str(exc))
        self.update_position()
        self.root.after(33, self.poll)

    def build_window(self):
        self.view = FollowspotView(self)

    def draft_settings(self):
        return settings_from_values(self.values, self.draft_buttons)

    def record_fault(self, kind, message):
        self.faults[kind] = message
        self.fault_label.set('\n'.join(self.faults.values()))

    def clear_fault(self, kind):
        self.faults.pop(kind, None)
        self.fault_label.set('\n'.join(self.faults.values()))

    def require_stopped(self):
        if self.controller.active:
            self.status.set('Stop output before changing settings or joystick selection.')
            return False
        return True

    def refresh_devices(self):
        if not self.require_stopped():
            return
        self.learning = None
        try:
            if self.joystick is None:
                self.joystick = Joystick()
            self.joystick.close()
            self.axes, self.buttons = [], []
            self.button_edges = ButtonEdges()
            self.device_choices = self.joystick.devices()
            self.device_box['values'] = [f'{index}: {name}' for index, name in self.device_choices]
            if not self.device_choices:
                self.device_box.set('')
                self.device_label.set('No joystick detected')
                self.status.set('No controller was found by SDL or native HID. Reconnect it and click Refresh.')
                return
            matches = [i for i, (_, name) in enumerate(self.device_choices) if name == self.values['device_name'].get()]
            if len(matches) == 1:
                self.device_box.current(matches[0])
                self.select_device()
            else:
                self.device_box.set('')
                self.device_label.set('No saved joystick found — select a device, or reconnect and Refresh.')
                self.status.set('Output stopped. Choose a joystick explicitly; no automatic device substitution.')
        except (OSError, RuntimeError, ValueError) as exc:
            self.status.set(str(exc))
            self.record_fault('input', str(exc))
        finally:
            self.view.refresh()

    def select_device(self, event=None):
        if not self.require_stopped():
            return
        self.learning = None
        choice = self.device_box.current()
        if choice < 0:
            return
        index, name = self.device_choices[choice]
        try:
            self.joystick.open(index)
            self.read_snapshot()
            self.values['device_name'].set(name)
            self.device_label.set(f'{name} · {len(self.axes)} axes · {len(self.buttons)} buttons')
            self.clear_fault('input')
            self.status.set('Joystick connected. Learn the axes and calibrate the released stick before Start.')
        except (OSError, RuntimeError, ValueError) as exc:
            self.joystick.close()
            self.axes, self.buttons = [], []
            self.device_label.set('Joystick unavailable')
            self.status.set(str(exc))
            self.record_fault('input', str(exc))
        finally:
            self.view.refresh()

    def read_snapshot(self):
        """Read outside polling; buttons already held stay unobserved until pressed again."""
        self.axes, self.buttons = self.joystick.read()
        self.button_edges.seed(self.buttons)

    def input_lost(self, reason):
        self.stop_output(reason, fault_kind='input')
        self.joystick.close()
        self.axes, self.buttons = [], []
        self.device_label.set('Joystick disconnected / unavailable · Refresh to reconnect')
        hold = ' The PSN stream is still holding the marker; use Release marker to let it reset.' if self.streamer is not None else ''
        self.record_fault('input', f'Joystick unavailable — output stopped. {reason}\nReconnect it, then Refresh in Setup → Joystick.{hold}')

    def begin_learn(self, key):
        if not self.require_stopped() or not self.axes:
            self.status.set('Connect a joystick and stop output before learning a control.')
            return
        self.learning = (key, list(self.axes), list(self.buttons), time.monotonic() + 8)
        text = 'Press the desired button…' if key == 'button' else f'Move only the {axis_name(key, self.values["control_mode"].get())}…'
        self.view.set_feedback(key, text + ' (8 seconds)')
        self.status.set(text)

    def calibrate(self):
        if not self.require_stopped() or not self.axes:
            return
        try:
            x, y = int(self.values['axis_x'].get()), int(self.values['axis_y'].get())
            if min(x, y) < 0 or max(x, y) >= len(self.axes):
                raise ValueError('Choose valid X/Y axes first.')
            if max(abs(self.axes[x]), abs(self.axes[y])) > 0.9:
                raise ValueError('Release the stick and choose its X/Y axes before calibrating.')
            self.values['centre_x'].set(f'{self.axes[x]:.6f}')
            self.values['centre_y'].set(f'{self.axes[y]:.6f}')
            text = 'Centre captured. Save settings to use it.'
            self.view.set_feedback('axis_x', f'Centre {self.axes[x]:+.3f} captured · save settings')
            self.view.set_feedback('axis_y', f'Centre {self.axes[y]:+.3f} captured · save settings')
            self.status.set(text)
        except (ValueError, IndexError) as exc:
            self.status.set(str(exc))
            self.view.set_feedback('axis_x', str(exc))

    def calibrate_zoom(self):
        if not self.require_stopped() or not self.axes:
            return
        try:
            axis = int(self.values['axis_zoom'].get())
            if not 0 <= axis < len(self.axes):
                raise ValueError('Choose a valid zoom/iris axis first.')
            centre = self.axes[axis]
            if not -0.9 <= centre <= 0.9:
                raise ValueError('Release the zoom/iris control before calibrating.')
            self.values['centre_zoom'].set(f'{centre:.6f}')
            self.view.set_feedback('axis_zoom', f'Centre {centre:+.3f} captured · save settings')
            self.status.set('Zoom/iris centre captured. Save settings to use it.')
        except (ValueError, IndexError) as exc:
            self.status.set(str(exc))
            self.view.set_feedback('axis_zoom', str(exc))

    def apply_settings(self):
        if not self.require_stopped():
            return False
        try:
            if self.view.mapping_pending():
                raise SettingsError('Add / update the button mapping or discard editor changes before saving.', 'buttons')
            settings = settings_from_values(self.values, self.draft_buttons)
            if self.streamer is not None and any(getattr(settings, key) != getattr(self.settings, key) for key in PSN_FIELDS):
                raise SettingsError('Release the PSN marker before changing control mode, position output or PSN settings.', *PSN_FIELDS)
            settings.save(self.settings_path)
        except (OSError, ValueError) as exc:
            self.view.show_error(exc)
            self.record_fault('settings', f'Settings were not saved: {exc}')
            return False
        xyz = self.controller.motion.xyz
        pan_tilt = self.controller.motion.pan_tilt
        zoom_level = self.controller.motion.zoom_level
        self.settings = settings
        self.view.clear_errors()
        self.clear_fault('settings')
        self.controller = Controller(settings, self.send, self.send_position)
        self.controller.motion.xyz = [clamp(xyz[0], settings.x_min, settings.x_max),
                                      clamp(xyz[1], settings.y_min, settings.y_max), settings.z]
        self.controller.motion.pan_tilt = [clamp(pan_tilt[0], settings.pan_min, settings.pan_max),
                                           clamp(pan_tilt[1], settings.tilt_min, settings.tilt_max)]
        self.controller.motion.zoom_level = zoom_level
        self.update_position()
        self.status.set('Settings saved and applied. Output remains stopped.')
        if self.joystick and self.joystick.handle:
            try:
                # New mappings must not act on buttons already held.
                self.read_snapshot()
            except (OSError, RuntimeError, ValueError) as exc:
                self.input_lost(f'Settings saved and applied, but the joystick could not be read: {exc}')
        self.view.refresh()
        return True

    def start_output(self, test=False):
        if not self.require_stopped():
            return
        if self.learning:
            self.status.set('Wait for learning to finish before starting output.')
            return
        if not self.apply_settings():
            return
        created_stream = False
        try:
            if not test:
                if not (self.joystick and self.joystick.handle):
                    raise ConnectionError('Select a joystick in Setup → Joystick first; click Refresh after reconnecting it.')
                # Suppress held buttons even if validation or the first send fails.
                self.read_snapshot()
                self.controller.motion.check_axes(self.axes)
                invalid_buttons = [key for key in self.settings.buttons if int(key) >= len(self.buttons)]
                if invalid_buttons:
                    raise ValueError(f'Button mappings outside this joystick’s range: {", ".join(invalid_buttons)}')
            if self.sender:
                self.sender.close()
            s = self.settings
            self.sender = OscSender(s.host, s.port, s.prefix)
            if s.control_mode == 'marker' and s.position_output == 'psn':
                created_stream = self.open_streamer()
            self.controller.start(self.axes, test=test)
            self.last_tick = time.monotonic()
            self.clear_fault('output')
            self.clear_fault('psn')
            self.output_label.set('TEST RUNNING (figure 8)' if test else 'OUTPUT RUNNING')
            self.lock_settings(True)
            marker = s.control_mode == 'marker'
            self.status.set(('Test running: ' + ('the marker traces a figure 8' if marker else 'pan and tilt trace a figure 8') +
                             '; the joystick is ignored. Stop ends it.') if test else
                            'Output running. Centre holds position and zoom/iris. Stop retains tracked levels.')
        except (OSError, RuntimeError, ValueError) as exc:
            if created_stream:
                self.close_streamer()
            self.stop_output(str(exc))
            self.messagebox.showerror('Could not start output', str(exc))

    def send(self, address, value):
        if self.sender is None:
            raise OSError('OSC output is not connected.')
        self.sender.send(address, value)

    def send_position(self, xyz):
        if self.streamer is None:
            raise OSError('PSN stream is not open.')
        self.streamer.set_position(xyz)

    def open_streamer(self):
        """Open the PSN stream unless one is already held; True when this call created it."""
        if self.streamer is not None:
            return False
        self.streamer = PsnStreamer(self.settings, self.controller.motion.xyz)
        return True

    def close_streamer(self):
        streamer, self.streamer = self.streamer, None
        if streamer is not None:
            streamer.close()

    def release_marker(self):
        if self.streamer is None:
            self.status.set('No PSN stream is open.')
            return False
        if self.controller.active:
            self.stop_output()
        self.close_streamer()
        self.clear_fault('psn')
        self.update_position()
        self.status.set('PSN marker released. onPC resets the MArker to 0, 0, 0.')
        return True

    def check_streamer(self):
        """A held stream may outlive output and the joystick; surface its failure from every poll."""
        if self.streamer is None:
            return
        error = self.streamer.poll_error()
        if error is None:
            return
        reason = f'PSN stream failed: {error}. The marker returns to 0, 0, 0 in onPC. Check the PSN interface; see docs/PSN.md.'
        self.close_streamer()
        if self.controller.active:
            self.stop_output(reason, fault_kind='psn')
        else:
            self.record_fault('psn', reason)
            self.status.set(reason)
        self.update_position()

    def stop_output(self, reason=None, fault_kind='output'):
        if self.controller.test:
            # The joystick is not read during a test; do not act on stale button state.
            self.button_edges = ButtonEdges()
        errors = self.controller.stop()
        if self.sender:
            self.sender.close()
            self.sender = None
        self.learning = None
        self.output_label.set('OUTPUT STOPPED')
        self.lock_settings(False)
        message = reason if reason is not None else 'Output stopped. Position, brightness and zoom/iris are retained.'
        if self.streamer is not None:
            message += ' PSN is still holding the marker; use Release marker to let it reset.'
        self.status.set(message + (' Release send failed: ' + '; '.join(errors) if errors else ''))
        if reason is not None:
            self.record_fault(fault_kind, f'Output stopped: {reason}')
            if 'Release send failed:' in reason:
                self.record_fault('release', reason + ' Check and release held actions in onPC; acknowledge in Diagnostics.')
        if errors:
            self.record_fault('release', 'Release send failed: ' + '; '.join(errors) + '. Check and release held actions in onPC; acknowledge in Diagnostics.')
        if self.streamer is not None:
            self.update_position()

    def lock_settings(self, locked):
        self.view.set_running(locked)
        if locked:
            self.notebook.select(0)

    def set_reset_lock(self):
        try:
            settings = replace(self.settings, reset_locked=self.values['reset_locked'].get())
            # Save only the lock; other editor values remain unapplied drafts.
            settings.save(self.settings_path)
            self.settings.reset_locked = settings.reset_locked
            self.clear_fault('lock')
            self.status.set('Reset is locked while running.' if settings.reset_locked else
                            'Reset is unlocked: it can send the initial target and zoom/iris level while running.')
        except (OSError, ValueError) as exc:
            self.values['reset_locked'].set(self.settings.reset_locked)
            self.messagebox.showerror('Could not save reset lock', str(exc))
            self.record_fault('lock', f'Reset lock was not saved: {exc}')
        self.lock_settings(self.controller.active)

    def reset_target(self, apply_drafts=True):
        """The window button applies edited settings first; a mapped joystick button does not."""
        if self.controller.active and self.settings.reset_locked:
            self.status.set('Reset is locked while running. Unlock it in Live or stop output first.')
            return False
        if not self.controller.active and apply_drafts and not self.apply_settings():
            return False
        try:
            self.controller.reset_target()
            self.update_position()
            self.status.set('Initial target and zoom/iris sent. Output continues; brightness is retained.' if self.controller.active else
                            'Target and zoom/iris reset locally. Start will send them to onPC.')
            return True
        except (OSError, RuntimeError, ValueError) as exc:
            self.stop_output(str(exc))
            return False

    def update_position(self):
        if self.settings.control_mode == 'pan_tilt':
            pan, tilt = self.controller.motion.pan_tilt
            text = f'Pan {pan:.1f}%   Tilt {tilt:.1f}%'
        else:
            x, y, z = self.controller.motion.xyz
            text = f'X {x:+.3f} m   Y {y:+.3f} m   Z {z:.3f} m'
            if self.streamer is not None and not self.controller.active:
                hx, hy, hz = self.streamer.position
                text += f'\nHeld at  X {hx:+.3f} m   Y {hy:+.3f} m   Z {hz:.3f} m'
        self.position_label.set(text)
        self.zoom_label.set(f'Zoom / iris  {self.controller.motion.zoom_level:.1f}%' if self.settings.zoom_enabled else
                            'Zoom / iris  disabled')
        self.view.refresh()

    def process_input(self, dt, allow_actions=True):
        if allow_actions:
            presses, releases = self.button_edges.sample(self.buttons)
        else:
            self.button_edges.seed(self.buttons)
            presses = releases = []
        actions = local_actions(presses, self.settings.buttons)
        # Stop and Release marker both act; Start and Reset are then ignored this sample.
        # Otherwise Start wins over Reset when stopped and is ignored when active.
        stopping = 'stop' in actions or ('toggle' in actions and self.controller.active)
        if stopping:
            self.stop_output()
        # A Release marker press with no stream open does nothing, so the sample continues.
        released = 'release_marker' in actions and self.release_marker()
        if stopping or released:
            return
        if not self.controller.active and ('start' in actions or 'toggle' in actions):
            self.start_output()
            return
        if 'reset' in actions and self.reset_target(apply_drafts=False):
            # Keep MA button edges, but do not move away from home this sample.
            dt = 0
        self.controller.tick(self.axes, dt, presses, releases)

    def poll(self):
        now = time.monotonic()
        dt, self.last_tick = now - self.last_tick, now
        try:
            self.check_streamer()
            if self.controller.active and self.controller.test:
                try:
                    self.controller.tick((), dt)
                except Exception as exc:
                    self.stop_output(str(exc))
                    if not isinstance(exc, (OSError, RuntimeError, ValueError)):
                        raise
                if now - self.last_ui > 0.1:
                    self.last_ui = now
                    self.brightness_label.set(f'Brightness  {self.settings.test_brightness:.1f}% (test)')
                    self.update_position()
            elif self.joystick and self.joystick.handle:
                try:
                    self.axes, self.buttons = self.joystick.read()
                except (OSError, RuntimeError, ValueError) as exc:
                    self.input_lost(str(exc))
                    return
                learning_sample = self.learning is not None
                if self.learning:
                    key, before_axes, before_buttons, deadline = self.learning
                    learned = None
                    if key == 'button':
                        learned = next((i for i, (old, new) in enumerate(zip(before_buttons, self.buttons)) if new and not old), None)
                    else:
                        learned = learn_axis(before_axes, self.axes)
                    if learned is not None:
                        (self.button_id if key == 'button' else self.values[key]).set(str(learned))
                        self.learning = None
                        text = f'Assigned {"button" if key == "button" else "axis"} {learned} · save settings'
                        self.view.set_feedback(key, text)
                        self.status.set(text)
                    elif now >= deadline:
                        self.learning = None
                        self.status.set('Learning timed out; no mapping changed.')
                        self.view.set_feedback(key, 'Learning timed out · click Learn to try again')
                try:
                    self.process_input(dt, allow_actions=not learning_sample)
                except Exception as exc:
                    # Output failures leave the joystick open. The controller has
                    # already stopped; stop here too so the window cannot show running.
                    self.stop_output(str(exc))
                    if not isinstance(exc, (OSError, RuntimeError, ValueError)):
                        raise
                if now - self.last_ui > 0.1:
                    self.last_ui = now
                    self.axes_label.set('Axes  ' + '  '.join(f'{i}: {v:+.3f}' for i, v in enumerate(self.axes)))
                    down = [str(i) for i, state in enumerate(self.buttons) if state]
                    self.buttons_label.set('Buttons down  ' + (', '.join(down) or 'none'))
                    try:
                        level = self.controller.motion.brightness(self.axes)
                        self.brightness_label.set(f'Brightness  {level:.1f}%')
                    except ValueError:
                        self.brightness_label.set('Brightness — choose valid axis mappings')
                    self.update_position()
        finally:
            self.view.refresh()
            self.root.after(33, self.poll)

    def render_buttons(self):
        self.button_table.delete(*self.button_table.get_children())
        for key in sorted(self.draft_buttons, key=int):
            mapping = self.draft_buttons[key]
            self.button_table.insert('', 'end', iid=key, text=key,
                                     values=(BUTTON_ACTIONS[mapping.get('action', 'command')],
                                             mapping.get('press', ''), mapping.get('release', '')))

    def load_button(self, event=None):
        if self.view.mapping_pending():
            self.view.restore_selection()
            self.view.show_error(SettingsError('Add / update the current mapping or discard editor changes before selecting another.', 'buttons'))
            return
        selection = self.button_table.selection()
        if selection:
            key = selection[0]
            mapping = self.draft_buttons[key]
            self.button_id.set(key)
            self.button_action.set(BUTTON_ACTIONS[mapping.get('action', 'command')])
            self.press_command.set(mapping.get('press', ''))
            self.release_command.set(mapping.get('release', ''))
            self.update_button_editor()
            self.view.editor_loaded()

    def update_button_editor(self, event=None):
        state = 'normal' if not self.controller.active and self.button_action.get() == BUTTON_ACTIONS['command'] else 'disabled'
        self.press_entry.configure(state=state)
        self.release_entry.configure(state=state)

    def set_button(self):
        if not self.require_stopped():
            return
        key = self.button_id.get().strip()
        action = next(key for key, label in BUTTON_ACTIONS.items() if label == self.button_action.get())
        mapping = {'action': action}
        if action == 'command':
            mapping.update(press=self.press_command.get().strip(), release=self.release_command.get().strip())
        draft = dict(self.draft_buttons, **{key: mapping})
        try:
            Settings.from_dict(dict(self.settings.to_dict(), buttons=draft))
            self.draft_buttons = draft
            self.render_buttons()
            self.view.editor_loaded()
            self.status.set('Mapping added / updated in the draft. Save settings to persist it.')
        except ValueError as exc:
            self.view.show_error(exc)
            self.record_fault('settings', f'Button mapping was not updated: {exc}')

    def remove_button(self):
        if self.require_stopped():
            self.draft_buttons.pop(self.button_id.get().strip(), None)
            self.render_buttons()
            self.view.editor_loaded()
            self.status.set('Mapping removed from the draft. Save settings to persist the change.')

    def close(self):
        if self.streamer is not None and not self.messagebox.askokcancel(
                'Close and reset the marker?',
                'The PSN stream is open. Closing stops it, and onPC resets the MArker to 0, 0, 0.'):
            return
        if self.controller:
            self.stop_output()
        self.close_streamer()
        if self.joystick:
            self.joystick.shutdown()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, default=SETTINGS_PATH)
    parser.add_argument('--monitor', type=float, metavar='SECONDS', help='Read joystick input only; never sends OSC.')
    parser.add_argument('--list-devices', action='store_true', help='List joystick devices without opening the window.')
    parser.add_argument('--check-settings', action='store_true', help='Validate settings without opening devices or sending OSC.')
    args = parser.parse_args()
    if args.check_settings:
        if not args.settings.is_file():
            raise FileNotFoundError(f'Settings file not found: {args.settings}')
        Settings.load(args.settings).validate()
        print(f'Settings valid: {args.settings}')
        return 0
    if args.list_devices or args.monitor is not None:
        j = Joystick()
        try:
            devices = j.devices()
            for index, name in devices:
                print(f'{index}: {name}')
            if not devices:
                print('No joystick detected by SDL or native HID. Reconnect it and try again.')
                return 1
            if args.monitor is not None:
                if not 0 < args.monitor <= 3600:
                    raise ValueError('Monitor duration must be greater than 0 and at most 3600 seconds.')
                s = Settings.load(args.settings)
                matches = [(index, name) for index, name in devices if name == s.device_name]
                if len(matches) != 1:
                    raise ValueError('Select and save a unique joystick device in the window first.')
                j.open(matches[0][0])
                deadline = time.monotonic() + args.monitor
                while time.monotonic() < deadline:
                    axes, buttons = j.read()
                    print(json.dumps({'axes': [round(v, 4) for v in axes], 'buttons': buttons}), flush=True)
                    time.sleep(0.1)
        finally:
            j.shutdown()
        return 0
    try:
        import tkinter as tk
    except ImportError:
        print('This Python is missing Tk. Use Launch Followspot.command, or install a Python with Tk support.', file=sys.stderr)
        return 1
    root = tk.Tk()
    App(root, args.settings)
    root.mainloop()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'Followspot: {exc}', file=sys.stderr)
        raise SystemExit(1)
