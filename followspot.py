#!/usr/bin/env python3
"""Small joystick-to-grandMA3 controller. Run directly or use the launcher."""
import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys
import time

from followspot_core import Controller, OscSender, Settings, clamp, learn_axis
from joystick import Joystick

SETTINGS_PATH = Path(__file__).resolve().with_name('settings.json')


def settings_from_values(values, buttons):
    data = {}
    for f in fields(Settings):
        if f.name == 'buttons':
            continue
        value = values[f.name].get()
        try:
            data[f.name] = value if f.type is bool else f.type(value)
        except (ValueError, TypeError):
            raise ValueError(f'{f.name}: enter a valid {"whole number" if f.type is int else "number"}.') from None
    data['buttons'] = buttons
    return Settings.from_dict(data)


class App:
    def __init__(self, root, settings_path=SETTINGS_PATH):
        import tkinter as tk
        from tkinter import ttk, messagebox
        self.root, self.tk, self.ttk, self.messagebox = root, tk, ttk, messagebox
        self.settings_path = Path(settings_path)
        self.sender = None
        self.joystick = None
        self.controller = None
        self.learning = None
        self.axes, self.buttons = [], []
        self.device_choices = []
        self.last_tick = time.monotonic()
        self.last_scan = 0
        self.last_ui = 0
        self.root.title('Joystick Followspot · grandMA3')
        self.root.geometry('860x720')
        self.root.minsize(760, 660)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        try:
            self.settings = Settings.load(self.settings_path)
        except (ValueError, OSError) as exc:
            # Do not fall back silently and allow output against unintended IDs.
            messagebox.showerror('Settings could not be loaded', f'{exc}\n\nCorrect or rename {self.settings_path.name}, then restart.')
            root.destroy()
            return
        self.controller = Controller(self.settings, self.send)
        self.draft_buttons = json.loads(json.dumps(self.settings.buttons))
        self.values = {}
        for f in fields(Settings):
            if f.name != 'buttons':
                kind = tk.BooleanVar if f.type is bool else tk.StringVar
                self.values[f.name] = kind(value=getattr(self.settings, f.name))
        self.status = tk.StringVar(value='Output is stopped. Configure the MArker and movement space before starting.')
        self.output_label = tk.StringVar(value='OUTPUT STOPPED')
        self.device_label = tk.StringVar(value='No joystick connected')
        self.position_label = tk.StringVar()
        self.brightness_label = tk.StringVar(value='Brightness —')
        self.axes_label = tk.StringVar(value='Axes —')
        self.buttons_label = tk.StringVar(value='Buttons —')
        self.build_window()
        try:
            self.joystick = Joystick()
            self.refresh_devices()
        except (OSError, RuntimeError) as exc:
            self.status.set(str(exc))
        self.update_position()
        self.root.after(33, self.poll)

    def build_window(self):
        ttk = self.ttk
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Joystick Followspot', font=('Helvetica', 20, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='Stick → X/Y speed     Slider → brightness     Buttons → onPC commands').pack(anchor='w', pady=(4, 12))
        notebook = ttk.Notebook(outer)
        notebook.pack(fill='both', expand=True)
        self.notebook = notebook
        live = ttk.Frame(notebook, padding=16)
        controls = ttk.Frame(notebook, padding=16)
        target = ttk.Frame(notebook, padding=16)
        network = ttk.Frame(notebook, padding=16)
        mappings = ttk.Frame(notebook, padding=16)
        for tab, name in [(live, 'Live'), (controls, 'Controls'), (target, 'Target / stage'),
                          (network, 'OSC'), (mappings, 'Buttons')]:
            notebook.add(tab, text=name)
        self.setting_tabs = [controls, target, network, mappings]
        for variable, font in [(self.output_label, ('Helvetica', 17, 'bold')),
                               (self.device_label, None), (self.position_label, ('Menlo', 16)),
                               (self.brightness_label, ('Helvetica', 15)), (self.axes_label, ('Menlo', 11)),
                               (self.buttons_label, ('Menlo', 11))]:
            options = {'textvariable': variable, 'wraplength': 770}
            if font:
                options['font'] = font
            ttk.Label(live, **options).pack(anchor='w', pady=9)
        ttk.Label(live, text='Position shows the script’s target, not feedback from onPC.\nStart applies settings and sends this target and the current slider level.',
                  wraplength=760).pack(anchor='w', pady=15)
        bar = ttk.Frame(live)
        bar.pack(anchor='w', pady=8)
        self.start_button = ttk.Button(bar, text='Start output', command=self.start_output)
        self.start_button.pack(side='left', padx=(0, 10))
        ttk.Button(bar, text='Stop output', command=self.stop_output).pack(side='left', padx=(0, 10))
        self.reset_button = ttk.Button(bar, text='Reset target (stopped)', command=self.reset_target)
        self.reset_button.pack(side='left')
        device_bar = ttk.Frame(controls)
        device_bar.grid(row=0, column=0, columnspan=4, sticky='ew', pady=(0, 10))
        ttk.Label(device_bar, text='Joystick').pack(side='left')
        self.device_box = ttk.Combobox(device_bar, state='readonly', width=40)
        self.device_box.pack(side='left', padx=8)
        self.device_box.bind('<<ComboboxSelected>>', self.select_device)
        ttk.Button(device_bar, text='Refresh', command=self.refresh_devices).pack(side='left')
        row = 1
        for label, axis, invert in [('Left / right', 'axis_x', 'invert_x'),
                                    ('Upstage / downstage', 'axis_y', 'invert_y'),
                                    ('Brightness slider', 'axis_slider', 'invert_slider')]:
            self.entry(controls, row, label + ' axis', axis, width=8)
            ttk.Button(controls, text='Learn', command=lambda key=axis: self.begin_learn(key)).grid(row=row, column=2, padx=8)
            ttk.Checkbutton(controls, text='Invert', variable=self.values[invert]).grid(row=row, column=3, sticky='w')
            row += 1
        for key, label in [('max_speed', 'Maximum speed (m/s)'), ('dead_zone', 'Centre dead zone (0–0.89)'),
                           ('centre_x', 'X centre'), ('centre_y', 'Y centre')]:
            self.entry(controls, row, label, key)
            row += 1
        ttk.Button(controls, text='Calibrate centre (release the stick first)', command=self.calibrate).grid(row=row, column=0, columnspan=4, sticky='w', pady=8)
        ttk.Label(controls, text='Learn: click Learn, then move only that control. Axis/button numbers start at 0.\nChanges take effect when you save/apply settings or Start output.',
                  wraplength=740).grid(row=row+1, column=0, columnspan=4, sticky='w', pady=10)
        self.entry(target, 0, 'MArker CID', 'marker_id')
        self.entry(target, 1, 'Z height (m)', 'z')
        ttk.Label(target, text='Operating limits (m) — smaller than or equal to the movement space').grid(row=2, column=0, columnspan=6, sticky='w', pady=10)
        for column, (key, label) in enumerate([('x_min', 'X min'), ('x_max', 'X max'), ('y_min', 'Y min'), ('y_max', 'Y max')]):
            ttk.Label(target, text=label).grid(row=3, column=column, sticky='w')
            ttk.Entry(target, textvariable=self.values[key], width=10).grid(row=4, column=column, sticky='w', padx=(0, 12))
        ttk.Label(target, text='Initial target (m) — used by Reset and on script launch').grid(row=5, column=0, columnspan=6, sticky='w', pady=10)
        for column, (key, label) in enumerate([('initial_x', 'X'), ('initial_y', 'Y')]):
            ttk.Label(target, text=label).grid(row=6, column=column*2, sticky='w')
            ttk.Entry(target, textvariable=self.values[key], width=10).grid(row=6, column=column*2+1, sticky='w')
        ttk.Label(target, text='MArker movement space (m) — must match onPC, including its centre/offset').grid(row=7, column=0, columnspan=6, sticky='w', pady=10)
        for row, axis in enumerate(('x', 'y', 'z'), 8):
            ttk.Label(target, text=axis.upper()).grid(row=row, column=0, sticky='w', pady=4)
            ttk.Entry(target, textvariable=self.values[f'space_{axis}_min'], width=10).grid(row=row, column=1, sticky='w')
            ttk.Label(target, text='to').grid(row=row, column=2)
            ttk.Entry(target, textvariable=self.values[f'space_{axis}_max'], width=10).grid(row=row, column=3, sticky='w')
        ttk.Label(target, text='Default space bounds assume a 200 m cube centred at the origin.\nConfirm the actual space in onPC before enabling output.', wraplength=740).grid(row=11, column=0, columnspan=6, sticky='w', pady=10)
        for row, (key, label) in enumerate([('host', 'onPC host / IP'), ('port', 'OSC port'), ('prefix', 'OSC prefix (no slashes)'),
                                            ('executor_page', 'Brightness executor page'), ('executor_number', 'Brightness executor number'),
                                            ('attribute_x', 'MArker X attribute'), ('attribute_y', 'MArker Y attribute'), ('attribute_z', 'MArker Z attribute')]):
            self.entry(network, row, label, key, width=26)
        ttk.Label(network, text='In onPC: enable OSC Input, Receive and Receive Command.\nUse UDP and the same port/prefix. Set FaderRange to 100.\nIf loopback is unavailable, enter the IP selected in onPC’s OSC Interface.',
                  wraplength=740).grid(row=8, column=0, columnspan=3, sticky='w', pady=15)
        self.button_table = ttk.Treeview(mappings, columns=('press', 'release'), height=8)
        self.button_table.heading('#0', text='Button')
        self.button_table.column('#0', width=65, stretch=False)
        for key in ('press', 'release'):
            self.button_table.heading(key, text=key.capitalize() + ' command')
            self.button_table.column(key, width=290)
        self.button_table.pack(fill='x')
        self.button_table.bind('<<TreeviewSelect>>', self.load_button)
        self.button_id = self.tk.StringVar(value='0')
        self.press_command = self.tk.StringVar()
        self.release_command = self.tk.StringVar()
        for label, var in [('Button number', self.button_id), ('Press command', self.press_command), ('Release command', self.release_command)]:
            line = ttk.Frame(mappings)
            line.pack(fill='x', pady=4)
            ttk.Label(line, text=label, width=17).pack(side='left')
            ttk.Entry(line, textvariable=var).pack(side='left', fill='x', expand=True)
        line = ttk.Frame(mappings)
        line.pack(anchor='w', pady=8)
        ttk.Button(line, text='Learn button', command=lambda: self.begin_learn('button')).pack(side='left', padx=(0, 8))
        ttk.Button(line, text='Set mapping', command=self.set_button).pack(side='left', padx=(0, 8))
        ttk.Button(line, text='Remove mapping', command=self.remove_button).pack(side='left')
        ttk.Label(mappings, text='Examples: Go+ Sequence 10; Go+ Macro 5.\nFor held actions, set both press and release commands. Click Set mapping, then Save / apply settings.',
                  wraplength=740).pack(anchor='w', pady=8)
        self.render_buttons()
        self.save_button = ttk.Button(outer, text='Save / apply settings', command=self.apply_settings)
        self.save_button.pack(anchor='w', pady=(12, 6))
        ttk.Label(outer, textvariable=self.status, wraplength=810).pack(fill='x', anchor='w')

    def entry(self, parent, row, label, key, width=16):
        self.ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=5, padx=(0, 14))
        self.ttk.Entry(parent, textvariable=self.values[key], width=width).grid(row=row, column=1, sticky='w', pady=5)

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
            self.device_choices = self.joystick.devices()
            self.device_box['values'] = [f'{index}: {name}' for index, name in self.device_choices]
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
            self.axes, self.buttons = self.joystick.read()
            self.values['device_name'].set(name)
            self.device_label.set(f'{name} · {len(self.axes)} axes · {len(self.buttons)} buttons')
            self.status.set('Joystick connected. Learn the axes and calibrate the released stick before Start.')
        except (OSError, RuntimeError, ValueError) as exc:
            self.joystick.close()
            self.axes, self.buttons = [], []
            self.device_label.set('Joystick unavailable')
            self.status.set(str(exc))

    def begin_learn(self, key):
        if not self.require_stopped() or not self.axes:
            self.status.set('Connect a joystick and stop output before learning a control.')
            return
        self.learning = (key, list(self.axes), list(self.buttons), time.monotonic() + 8)
        self.status.set('Press the desired button.' if key == 'button' else 'Move only the control you want to assign; learning times out after 8 seconds.')

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
            self.status.set('Centre captured. Save / apply settings to use it.')
        except (ValueError, IndexError) as exc:
            self.status.set(str(exc))

    def apply_settings(self):
        if not self.require_stopped():
            return False
        try:
            settings = settings_from_values(self.values, self.draft_buttons)
            settings.save(self.settings_path)
            xyz = self.controller.motion.xyz
            self.settings = settings
            self.controller = Controller(settings, self.send)
            self.controller.motion.xyz = [clamp(xyz[0], settings.x_min, settings.x_max),
                                          clamp(xyz[1], settings.y_min, settings.y_max), settings.z]
            self.update_position()
            self.status.set('Settings saved and applied. Output remains stopped.')
            return True
        except (OSError, ValueError) as exc:
            self.messagebox.showerror('Settings', str(exc))
            return False

    def start_output(self):
        if not self.require_stopped():
            return
        if self.learning:
            self.status.set('Wait for learning to finish before starting output.')
            return
        if not self.apply_settings():
            return
        try:
            if self.joystick is None:
                raise ConnectionError('Connect a joystick first.')
            self.axes, self.buttons = self.joystick.read()
            self.controller.motion.check_axes(self.axes)
            invalid_buttons = [key for key in self.settings.buttons if int(key) >= len(self.buttons)]
            if invalid_buttons:
                raise ValueError(f'Button mappings outside this joystick’s range: {", ".join(invalid_buttons)}')
            if self.sender:
                self.sender.close()
            s = self.settings
            self.sender = OscSender(s.host, s.port, s.prefix)
            self.controller.start(self.axes, self.buttons)
            self.last_tick = time.monotonic()
            self.output_label.set('OUTPUT RUNNING · OSC sent, reception unconfirmed')
            self.lock_settings(True)
            self.status.set('Output running. Stick controls speed; centre holds position. Stop retains target and brightness.')
        except (OSError, RuntimeError, ValueError) as exc:
            self.stop_output(str(exc))
            self.messagebox.showerror('Could not start output', str(exc))

    def send(self, address, value):
        if self.sender is None:
            raise OSError('OSC output is not connected.')
        self.sender.send(address, value)

    def stop_output(self, reason='Output stopped. Position and brightness are retained in onPC.'):
        errors = self.controller.stop()
        if self.sender:
            self.sender.close()
            self.sender = None
        self.learning = None
        self.output_label.set('OUTPUT STOPPED')
        if hasattr(self, 'setting_tabs'):
            self.lock_settings(False)
        self.status.set(reason + (' Release send failed: ' + '; '.join(errors) if errors else ''))

    def lock_settings(self, locked):
        for tab in self.setting_tabs:
            self.notebook.tab(tab, state='disabled' if locked else 'normal')
        for button in (self.start_button, self.reset_button, self.save_button):
            button.configure(state='disabled' if locked else 'normal')
        if locked:
            self.notebook.select(0)

    def reset_target(self):
        if not self.require_stopped() or not self.apply_settings():
            return
        s = self.settings
        self.controller.motion.xyz = [s.initial_x, s.initial_y, s.z]
        self.update_position()
        self.status.set('Target reset locally. Start will send this position to onPC.')

    def update_position(self):
        x, y, z = self.controller.motion.xyz
        self.position_label.set(f'Target  X {x:+.3f} m   Y {y:+.3f} m   Z {z:.3f} m')

    def poll(self):
        now = time.monotonic()
        dt, self.last_tick = now - self.last_tick, now
        try:
            if self.joystick and self.joystick.handle:
                self.axes, self.buttons = self.joystick.read()
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
                        self.status.set(f'Learned {key}: {learned}. Save / apply settings after completing mappings.')
                    elif now >= deadline:
                        self.learning = None
                        self.status.set('Learning timed out; no mapping changed.')
                self.controller.tick(self.axes, self.buttons, dt)
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
        except (OSError, RuntimeError, ValueError) as exc:
            self.stop_output(str(exc))
            self.joystick.close()
            self.axes, self.buttons = [], []
            self.device_label.set('Joystick disconnected / unavailable · Refresh to reconnect')
        finally:
            self.root.after(33, self.poll)

    def render_buttons(self):
        self.button_table.delete(*self.button_table.get_children())
        for key in sorted(self.draft_buttons, key=int):
            mapping = self.draft_buttons[key]
            self.button_table.insert('', 'end', iid=key, text=key,
                                     values=(mapping.get('press', ''), mapping.get('release', '')))

    def load_button(self, event=None):
        selection = self.button_table.selection()
        if selection:
            key = selection[0]
            mapping = self.draft_buttons[key]
            self.button_id.set(key)
            self.press_command.set(mapping.get('press', ''))
            self.release_command.set(mapping.get('release', ''))

    def set_button(self):
        if not self.require_stopped():
            return
        key = self.button_id.get().strip()
        mapping = {'press': self.press_command.get().strip(), 'release': self.release_command.get().strip()}
        draft = dict(self.draft_buttons, **{key: mapping})
        try:
            Settings.from_dict(dict(self.settings.to_dict(), buttons=draft))
            self.draft_buttons = draft
            self.render_buttons()
            self.status.set('Button mapping updated. Save / apply settings to persist it.')
        except ValueError as exc:
            self.messagebox.showerror('Button mapping', str(exc))

    def remove_button(self):
        if self.require_stopped():
            self.draft_buttons.pop(self.button_id.get().strip(), None)
            self.render_buttons()
            self.status.set('Mapping removed. Save / apply settings to persist the change.')

    def close(self):
        if self.controller:
            self.stop_output('Window closed; output stopped.')
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
                print('No joystick detected by SDL. Reconnect it and run from a normal macOS terminal.')
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
