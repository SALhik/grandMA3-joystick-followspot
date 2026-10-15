"""Native Tk presentation; input, output and persistence stay in followspot.App."""
from decimal import Decimal
from followspot_core import BUTTON_ACTIONS, Motion, clamp


PERCENT_FIELDS = {'dead_zone', 'zoom_dead_zone'}
AXIS_NAMES = {'axis_x': 'left / right control', 'axis_y': 'upstage / downstage control',
              'axis_slider': 'brightness slider', 'axis_zoom': 'zoom / iris control',
              'button': 'button'}
PAN_TILT_AXIS_NAMES = {'axis_x': 'pan control (left / right)', 'axis_y': 'tilt control (up / down)'}


def axis_name(key, control_mode):
    """Prompt wording for a learnable control; pan/tilt renames the two stick axes."""
    if control_mode == 'pan_tilt' and key in PAN_TILT_AXIS_NAMES:
        return PAN_TILT_AXIS_NAMES[key]
    return AXIS_NAMES[key]


AXIS_CAPTIONS = {'axis_x': ('Left / right axis', 'Pan (left / right) axis'),
                 'axis_y': ('Upstage / downstage axis', 'Tilt (up / down) axis')}
MARKER_FIELDS = ('marker_id', 'z', 'x_min', 'x_max', 'y_min', 'y_max', 'initial_x', 'initial_y',
                 'space_x_min', 'space_x_max', 'space_y_min', 'space_y_max', 'space_z_min', 'space_z_max',
                 'attribute_x', 'attribute_y', 'attribute_z', 'max_speed', 'position_output',
                 'psn_tracker_id', 'psn_group', 'psn_port', 'psn_interface', 'test_size')
PAN_TILT_FIELDS = ('fixture_group', 'attribute_pan', 'attribute_tilt', 'pan_tilt_speed', 'pan_min', 'pan_max',
                   'tilt_min', 'tilt_max', 'initial_pan', 'initial_tilt', 'test_pan_tilt_size')


def display_value(key, value):
    return format(Decimal(str(value)) * 100, 'f') if key in PERCENT_FIELDS else value


class FollowspotView:
    def __init__(self, app):
        import tkinter as tk
        from tkinter import ttk, font
        self.app, self.tk, self.ttk = app, tk, ttk
        self.fields, self.field_pages, self.field_labels = {}, {}, {}
        self.field_captions = {}
        self.editable, self.advanced, self.axis_feedback, self.axis_inputs = [], {}, {}, {}
        self.wrapping = []
        self.page_layouts = []
        self.wrap_widths = {}
        self.editor_baseline = ('0', BUTTON_ACTIONS['command'], '', '')
        self.readiness = tk.StringVar()
        self.summary = tk.StringVar()
        self.save_state = tk.StringVar()
        self.mapping_state = tk.StringVar()
        self.reset_state = tk.StringVar()
        self.brightness_context = tk.StringVar()
        self.editing_state = tk.StringVar()
        self.stage_title = tk.StringVar()
        # Last state/text applied per widget, so refresh (every poll) only touches Tk on a change.
        self.field_states, self.caption_texts = {}, {}
        self.brightness = tk.DoubleVar()
        self.zoom = tk.DoubleVar()
        self.title_font = font.nametofont('TkDefaultFont').copy()
        self.title_font.configure(size=20, weight='bold')
        self.state_font = font.nametofont('TkDefaultFont').copy()
        self.state_font.configure(size=15, weight='bold')
        self.value_font = font.nametofont('TkFixedFont').copy()
        self.value_font.configure(size=14)
        style = ttk.Style(app.root)
        self.background = style.lookup('TFrame', 'background') or 'SystemWindowBackgroundColor'
        self.foreground = style.lookup('TLabel', 'foreground') or 'SystemLabelColor'
        style.configure('Fault.TLabel', foreground='#b33a32')
        style.configure('Running.TLabel', foreground='#247245')
        style.configure('Test.TLabel', foreground='#97651a')
        self.build()
        for variable in app.values.values():
            variable.trace_add('write', self.changed)
        for variable in (app.button_id, app.button_action, app.press_command, app.release_command):
            variable.trace_add('write', self.changed)
        for variable in (app.status, app.device_label, app.fault_label):
            variable.trace_add('write', self.changed)
        self.refresh()

    def label(self, parent, text=None, variable=None, **options):
        label = self.ttk.Label(parent, text=text, textvariable=variable, **options)
        label.configure(wraplength=700)
        self.wrapping.append(label)
        return label

    def edit(self, widget, state='normal'):
        self.editable.append((widget, state))
        return widget

    def entry(self, parent, row, label, key, width=18):
        caption = self.ttk.Label(parent, text=label)
        caption.grid(row=row, column=0, sticky='w', padx=(0, 16), pady=5)
        self.field_captions[key] = caption
        widget = self.edit(self.ttk.Entry(parent, textvariable=self.app.values[key], width=width))
        widget.grid(row=row, column=1, sticky='w', pady=5)
        self.fields[key] = widget
        self.field_labels[key] = label
        # The parent carries the page even when this field is in an advanced section.
        self.field_pages[key] = self.current_page
        return widget

    def choice(self, parent, row, label, key, values):
        caption = self.ttk.Label(parent, text=label)
        caption.grid(row=row, column=0, sticky='w', padx=(0, 16), pady=5)
        self.field_captions[key] = caption
        box = self.edit(self.ttk.Combobox(parent, textvariable=self.app.values[key], values=values,
                                          state='readonly', width=10), 'readonly')
        box.grid(row=row, column=1, sticky='w', pady=5)
        self.fields[key] = box
        self.field_labels[key] = label
        self.field_pages[key] = self.current_page
        return box

    def page(self, notebook, title):
        shell = self.ttk.Frame(notebook)
        notebook.add(shell, text=title)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)
        canvas = self.tk.Canvas(shell, highlightthickness=0, background=self.background)
        canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = self.ttk.Scrollbar(shell, orient='vertical', command=(canvas._w, 'yview'))
        scrollbar.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=(scrollbar._w, 'set'))
        body = self.ttk.Frame(canvas, padding=16)
        window = canvas.create_window(0, 0, window=body, anchor='nw')
        def layout(event=None):
            canvas.itemconfigure(window, width=canvas.winfo_width())
            canvas.configure(scrollregion=canvas.bbox('all'))
            if body.winfo_reqheight() > canvas.winfo_height():
                scrollbar.grid()
            else:
                scrollbar.grid_remove()
                canvas.yview_moveto(0)
        # SDL can dispatch native resize events outside _tkinter's call boundary.
        # Keep layout in the normal poll instead of Python <Configure> callbacks.
        self.page_layouts.append(layout)
        body.scroll_canvas = canvas
        self.current_page = (notebook, shell, body)
        return body

    def build(self):
        app, ttk = self.app, self.ttk
        outer = ttk.Frame(app.root, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Joystick Followspot', font=self.title_font).pack(anchor='w')
        self.label(outer, variable=self.summary).pack(anchor='w', pady=(4, 12))
        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=(0, 4))
        self.state_label = ttk.Label(bar, textvariable=app.output_label, font=self.state_font)
        self.state_label.pack(side='left')
        app.stop_button = ttk.Button(bar, text='Stop output', command=app.stop_output)
        app.stop_button.pack(side='right', padx=(8, 0))
        app.start_button = ttk.Button(bar, text='Start output', command=app.start_output)
        app.start_button.pack(side='right')
        self.label(outer, variable=self.readiness).pack(anchor='w', pady=(0, 12))
        app.notebook = ttk.Notebook(outer)
        app.notebook.pack(fill='both', expand=True)
        live = ttk.Frame(app.notebook, padding=16)
        setup = ttk.Frame(app.notebook, padding=(8, 12))
        app.notebook.add(live, text='Live')
        app.notebook.add(setup, text='Setup')
        diagnostics = self.page(app.notebook, 'Diagnostics')
        self.diagnostics_page = self.current_page
        self.build_live(live)
        self.label(setup, variable=self.editing_state).pack(anchor='w', pady=(0, 8))
        self.setup_tabs = ttk.Notebook(setup)
        self.setup_tabs.pack(fill='both', expand=True)
        controls = self.page(self.setup_tabs, 'Joystick')
        self.build_controls(controls)
        target = self.page(self.setup_tabs, 'Target / stage')
        self.build_target(target)
        levels = self.page(self.setup_tabs, 'Brightness / zoom')
        self.build_levels(levels)
        network = self.page(self.setup_tabs, 'OSC')
        self.build_network(network)
        mappings = self.page(self.setup_tabs, 'Buttons')
        self.mapping_page = self.current_page
        self.build_mappings(mappings)
        self.current_page = self.diagnostics_page
        self.build_diagnostics(diagnostics)
        self.fault = self.label(outer, variable=app.fault_label, style='Fault.TLabel')
        self.fault.pack(fill='x', pady=(10, 0))
        footer = ttk.Frame(outer)
        self.footer = footer
        footer.pack(fill='x', pady=(12, 4))
        app.save_button = ttk.Button(footer, text='Save settings', command=app.apply_settings)
        app.save_button.pack(side='right')
        self.label(footer, variable=self.save_state).pack(side='left')
        self.label(outer, variable=app.status).pack(fill='x')
        # Scroll only the page under the pointer; never bind application-wide wheel events.
        for notebook in (app.notebook, self.setup_tabs):
            self.bind_scrolling(notebook)

    def build_live(self, live):
        app, ttk = self.app, self.ttk
        live.columnconfigure(0, weight=1)
        live.rowconfigure(1, weight=1)
        ttk.Label(live, textvariable=self.stage_title).grid(row=0, column=0, sticky='w', pady=(0, 8))
        self.stage = self.tk.Canvas(live, height=210, width=360, highlightthickness=0,
                                    background=self.background)
        self.stage.grid(row=1, column=0, sticky='nsew', padx=(0, 24))
        levels = ttk.Frame(live)
        levels.grid(row=0, column=1, rowspan=2, sticky='nw', pady=(0, 8))
        ttk.Label(levels, textvariable=app.brightness_label, font=self.state_font).pack(anchor='w')
        ttk.Progressbar(levels, variable=self.brightness, maximum=100, length=185).pack(fill='x', pady=(8, 4))
        self.label(levels, variable=self.brightness_context).pack(anchor='w', pady=(0, 24))
        ttk.Label(levels, textvariable=app.zoom_label, font=self.state_font).pack(anchor='w')
        self.zoom_meter = ttk.Progressbar(levels, variable=self.zoom, maximum=100, length=185)
        self.zoom_meter.pack(fill='x', pady=8)
        ttk.Label(levels, text='Tracked level · no MA feedback').pack(anchor='w')
        ttk.Label(live, textvariable=app.position_label, font=self.value_font).grid(row=2, column=0, columnspan=2, sticky='w', pady=(12, 6))
        self.label(live, text='Start sends this target, the current slider brightness and enabled zoom / iris. Values are not feedback from onPC.').grid(row=3, column=0, columnspan=2, sticky='w', pady=(0, 12))
        ttk.Separator(live).grid(row=4, column=0, columnspan=2, sticky='ew', pady=(0, 12))
        reset = ttk.Frame(live)
        reset.grid(row=5, column=0, columnspan=2, sticky='ew')
        app.reset_button = ttk.Button(reset, text='Reset target + zoom/iris', command=app.reset_target)
        app.reset_button.pack(side='left', padx=(0, 16))
        ttk.Checkbutton(reset, text='Lock reset while running', variable=app.values['reset_locked'],
                        command=app.set_reset_lock).pack(side='left')
        # refresh packs this only when PSN is selected or a stream is held.
        app.release_button = ttk.Button(reset, text='Release marker', command=app.release_marker)
        self.label(live, variable=self.reset_state).grid(row=6, column=0, columnspan=2, sticky='w', pady=(8, 0))

    def axis_row(self, parent, row, label, key, invert):
        self.entry(parent, row, label, key, width=7)
        self.edit(self.ttk.Button(parent, text='Learn', command=lambda: self.app.begin_learn(key))).grid(row=row, column=2, padx=8)
        self.edit(self.ttk.Checkbutton(parent, text='Invert', variable=self.app.values[invert])).grid(row=row, column=3, sticky='w')
        value, level, feedback = self.tk.StringVar(), self.tk.DoubleVar(), self.tk.StringVar()
        self.axis_inputs[key] = (value, level)
        self.axis_feedback[key] = feedback
        self.ttk.Progressbar(parent, variable=level, maximum=100, length=100).grid(row=row+1, column=1, sticky='w')
        self.ttk.Label(parent, textvariable=value).grid(row=row+1, column=2, columnspan=2, sticky='w', padx=8)
        self.label(parent, variable=feedback).grid(row=row+2, column=1, columnspan=3, sticky='w', pady=(2, 8))

    def advanced_fields(self, parent, row, keys):
        visible = self.tk.BooleanVar(value=False)
        panel = self.ttk.Frame(parent)
        panel.grid(row=row+1, column=0, columnspan=4, sticky='ew')
        for index, (key, label) in enumerate(keys):
            self.entry(panel, index, label, key)
            self.advanced[key] = (visible, panel)
        panel.grid_remove()
        def toggle():
            panel.grid() if visible.get() else panel.grid_remove()
        visible.trace_add('write', lambda *args: toggle())
        self.ttk.Checkbutton(parent, text='Advanced calibration offsets', variable=visible).grid(row=row, column=0, columnspan=4, sticky='w', pady=8)

    def build_controls(self, parent):
        app, ttk = self.app, self.ttk
        ttk.Label(parent, text='Joystick').grid(row=0, column=0, sticky='w', pady=5)
        app.device_box = self.edit(ttk.Combobox(parent, state='readonly', width=30), 'readonly')
        app.device_box.grid(row=0, column=1, columnspan=2, sticky='w')
        app.device_box.bind('<<ComboboxSelected>>', app.select_device)
        self.edit(ttk.Button(parent, text='Refresh', command=app.refresh_devices)).grid(row=0, column=3, padx=8)
        self.label(parent, variable=app.device_label).grid(row=1, column=0, columnspan=4, sticky='w', pady=(4, 12))
        for row, label, key, invert in [(2, 'Left / right axis', 'axis_x', 'invert_x'),
                                      (5, 'Upstage / downstage axis', 'axis_y', 'invert_y'),
                                      (8, 'Brightness slider axis', 'axis_slider', 'invert_slider')]:
            self.axis_row(parent, row, label, key, invert)
        self.entry(parent, 11, 'Maximum speed (m/s)', 'max_speed')
        self.entry(parent, 12, 'Centre dead zone (%)', 'dead_zone')
        self.edit(ttk.Button(parent, text='Calibrate stick centre', command=app.calibrate)).grid(row=13, column=0, sticky='w', pady=8)
        self.label(parent, text='Release the stick before calibrating. Learn one control at a time; axis numbers start at 0. Input previews use the draft mappings.').grid(row=14, column=0, columnspan=4, sticky='w', pady=4)
        self.advanced_fields(parent, 15, [('centre_x', 'X centre offset'), ('centre_y', 'Y centre offset')])

    def build_target(self, parent):
        self.choice(parent, 0, 'Control', 'control_mode', ['marker', 'pan_tilt'])
        self.label(parent, text='marker moves one MArker and onPC aims the fixtures at it. pan_tilt drives the pan and tilt of one fixture group directly, over OSC only.').grid(row=1, column=0, columnspan=4, sticky='w', pady=(0, 8))
        self.entry(parent, 2, 'MArker CID', 'marker_id')
        self.entry(parent, 3, 'Z height (m)', 'z')
        self.ttk.Label(parent, text='Operating limits and initial target (m)').grid(row=4, column=0, columnspan=4, sticky='w', pady=(12, 4))
        for row, (key, label) in enumerate([('x_min', 'X minimum'), ('x_max', 'X maximum'),
                                          ('y_min', 'Y minimum'), ('y_max', 'Y maximum'),
                                          ('initial_x', 'Initial / reset X'), ('initial_y', 'Initial / reset Y')], 5):
            self.entry(parent, row, label, key)
        self.ttk.Label(parent, text='MArker movement space (m) · match onPC').grid(row=11, column=0, columnspan=4, sticky='w', pady=(12, 4))
        for row, axis in enumerate('xyz', 12):
            self.entry(parent, row, axis.upper() + ' minimum', f'space_{axis}_min', width=12)
            caption = self.ttk.Label(parent, text='Maximum')
            caption.grid(row=row, column=2, padx=12)
            key = f'space_{axis}_max'
            widget = self.edit(self.ttk.Entry(parent, textvariable=self.app.values[key], width=12))
            widget.grid(row=row, column=3, sticky='w')
            self.fields[key], self.field_pages[key] = widget, self.current_page
            self.field_labels[key] = axis.upper() + ' movement space maximum'
            self.field_captions[key] = caption
        self.label(parent, text='Operating limits fit inside the movement space. Defaults are examples; confirm the actual movement space in onPC.').grid(row=15, column=0, columnspan=4, sticky='w', pady=12)
        self.ttk.Label(parent, text='Pan / tilt (% of the fixture range)', font=self.state_font).grid(row=16, column=0, columnspan=4, sticky='w', pady=(20, 4))
        self.entry(parent, 17, 'Fixture group', 'fixture_group')
        self.entry(parent, 18, 'Pan attribute', 'attribute_pan')
        self.entry(parent, 19, 'Tilt attribute', 'attribute_tilt')
        self.entry(parent, 20, 'Maximum speed (% points/s)', 'pan_tilt_speed')
        for row, (key, label) in enumerate([('pan_min', 'Pan minimum (%)'), ('pan_max', 'Pan maximum (%)'),
                                          ('tilt_min', 'Tilt minimum (%)'), ('tilt_max', 'Tilt maximum (%)'),
                                          ('initial_pan', 'Initial / reset pan (%)'), ('initial_tilt', 'Initial / reset tilt (%)')], 21):
            self.entry(parent, row, label, key)
        self.label(parent, text='Pan/tilt output selects the group, then sets Pan and Tilt as absolute percent, so it takes the console selection while output runs. Limits keep the lights inside a safe range. Confirm the attribute names with List Attribute in onPC.').grid(row=27, column=0, columnspan=4, sticky='w', pady=12)

    def build_levels(self, parent):
        app, ttk = self.app, self.ttk
        ttk.Label(parent, text='Brightness · Master fader', font=self.state_font).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 8))
        self.entry(parent, 1, 'Executor page', 'executor_page')
        self.entry(parent, 2, 'Executor number', 'executor_number')
        self.label(parent, text='The joystick slider sets absolute brightness. Use a Master fader and FaderRange 100 in onPC.').grid(row=3, column=0, columnspan=4, sticky='w', pady=(4, 16))
        self.edit(ttk.Checkbutton(parent, text='Enable zoom / iris axis', variable=app.values['zoom_enabled'])).grid(row=4, column=0, columnspan=4, sticky='w', pady=(0, 8))
        self.axis_row(parent, 5, 'Zoom / iris axis', 'axis_zoom', 'invert_zoom')
        for row, key, label in [(8, 'zoom_speed', 'Maximum speed (% points/s)'),
                                (9, 'zoom_dead_zone', 'Centre dead zone (%)'),
                                (10, 'initial_zoom', 'Initial / reset level (%)'),
                                (11, 'zoom_executor_page', 'Executor page'),
                                (12, 'zoom_executor_number', 'Executor number')]:
            self.entry(parent, row, label, key)
        self.edit(ttk.Button(parent, text='Calibrate zoom / iris centre', command=app.calibrate_zoom)).grid(row=13, column=0, columnspan=4, sticky='w', pady=8)
        self.label(parent, text='Release the control before calibrating. Centre holds its level. Use a separate zoom-only or iris-only sequence with a Temp fader and FaderRange 100.').grid(row=14, column=0, columnspan=4, sticky='w', pady=4)
        self.advanced_fields(parent, 15, [('centre_zoom', 'Axis centre offset')])

    def build_network(self, parent):
        for row, (key, label) in enumerate([('host', 'onPC host / IP'), ('port', 'OSC port'), ('prefix', 'OSC prefix (no slashes)'),
                                            ('attribute_x', 'MArker X attribute'), ('attribute_y', 'MArker Y attribute'), ('attribute_z', 'MArker Z attribute')]):
            self.entry(parent, row, label, key, width=26)
        self.label(parent, text='In onPC, enable OSC Input, Receive and Receive Command. Match the selected OSC Interface, UDP port and prefix. Reception checks are in Diagnostics.').grid(row=6, column=0, columnspan=3, sticky='w', pady=12)
        caption = self.ttk.Label(parent, text='Position output')
        caption.grid(row=7, column=0, sticky='w', padx=(0, 16), pady=(16, 5))
        self.field_captions['position_output'] = caption
        box = self.edit(self.ttk.Combobox(parent, textvariable=self.app.values['position_output'], values=['osc', 'psn'],
                                          state='readonly', width=8), 'readonly')
        box.grid(row=7, column=1, sticky='w', pady=(16, 5))
        self.fields['position_output'] = box
        self.field_labels['position_output'] = 'Position output'
        self.field_pages['position_output'] = self.current_page
        for row, (key, label) in enumerate([('psn_tracker_id', 'PSN tracker ID'), ('psn_group', 'PSN multicast group'),
                                            ('psn_port', 'PSN port'), ('psn_interface', 'PSN interface (this computer)')], 8):
            self.entry(parent, row, label, key, width=26)
        self.label(parent, text='osc moves the MArker with commands and takes the console selection. psn streams the position without touching the selection; brightness, zoom / iris and buttons still use OSC. In onPC set the PSN row Interface to this computer, add a tracker whose Tracker ID and MArker ID match, and see docs/PSN.md. Stop holds the position; Release marker lets the MArker reset to 0, 0, 0. Position output applies to Marker control only; Pan-tilt control always uses OSC.').grid(row=12, column=0, columnspan=3, sticky='w', pady=12)

    def build_mappings(self, parent):
        app, ttk = self.app, self.ttk
        parent.columnconfigure(0, weight=1)
        app.button_table = ttk.Treeview(parent, columns=('action', 'press', 'release'), height=5, selectmode='browse')
        app.button_table.heading('#0', text='Button')
        app.button_table.column('#0', width=60, stretch=False)
        app.button_table.heading('action', text='Action on press')
        app.button_table.column('action', width=130, stretch=False)
        for key in ('press', 'release'):
            app.button_table.heading(key, text=key.capitalize() + ' command')
            app.button_table.column(key, width=200, minwidth=100)
        app.button_table.grid(row=0, column=0, sticky='ew')
        scroll = ttk.Scrollbar(parent, orient='horizontal', command=(app.button_table._w, 'xview'))
        scroll.grid(row=1, column=0, sticky='ew')
        app.button_table.configure(xscrollcommand=(scroll._w, 'set'))
        app.button_table.bind('<<TreeviewSelect>>', app.load_button)
        app.button_id = self.tk.StringVar(value='0')
        app.button_action = self.tk.StringVar(value=BUTTON_ACTIONS['command'])
        app.press_command, app.release_command = self.tk.StringVar(), self.tk.StringVar()
        form = ttk.Frame(parent)
        form.grid(row=2, column=0, sticky='ew', pady=8)
        form.columnconfigure(1, weight=1)
        for row, (label, variable) in enumerate([('Button number', app.button_id), ('Action on press', app.button_action),
                                                 ('Press command', app.press_command), ('Release command', app.release_command)]):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', padx=(0, 16), pady=5)
            if variable is app.button_action:
                widget = self.edit(ttk.Combobox(form, textvariable=variable, values=list(BUTTON_ACTIONS.values()), state='readonly'), 'readonly')
                widget.bind('<<ComboboxSelected>>', app.update_button_editor)
            else:
                widget = self.edit(ttk.Entry(form, textvariable=variable))
            widget.grid(row=row, column=1, sticky='ew', pady=5)
            if variable is app.press_command:
                app.press_entry = widget
            elif variable is app.release_command:
                app.release_entry = widget
        bar = ttk.Frame(parent)
        bar.grid(row=3, column=0, sticky='w')
        for text, command in [('Learn button', lambda: app.begin_learn('button')),
                              ('Add / update mapping', app.set_button), ('Remove mapping', app.remove_button),
                              ('Discard editor changes', self.discard_editor)]:
            self.edit(ttk.Button(bar, text=text, command=command)).pack(side='left', padx=(0, 8))
        self.axis_feedback['button'] = self.tk.StringVar()
        self.label(parent, variable=self.axis_feedback['button']).grid(row=4, column=0, sticky='w', pady=(8, 0))
        self.label(parent, variable=self.mapping_state).grid(row=5, column=0, sticky='w', pady=8)
        self.label(parent, text='MA command examples: Go+ Sequence 10; Go+ Macro 5. Local actions fire on press; Reset obeys the Live lock.').grid(row=6, column=0, sticky='w', pady=4)
        app.render_buttons()

    def build_diagnostics(self, parent):
        app, ttk = self.app, self.ttk
        ttk.Label(parent, text='Input monitor', font=self.state_font).grid(row=0, column=0, columnspan=3, sticky='w')
        self.label(parent, variable=app.axes_label, font='TkFixedFont').grid(row=1, column=0, columnspan=3, sticky='w', pady=8)
        self.label(parent, variable=app.buttons_label).grid(row=2, column=0, columnspan=3, sticky='w')
        ttk.Label(parent, text='Figure 8 test · sends real output', font=self.state_font).grid(row=3, column=0, columnspan=3, sticky='w', pady=(20, 8))
        for row, (key, label) in enumerate([('test_size', 'Figure 8 half-width, marker (m)'),
                                            ('test_pan_tilt_size', 'Figure 8 half-swing, pan/tilt (% points)'),
                                            ('test_period', 'Seconds per lap'),
                                            ('test_brightness', 'Test brightness (%)')], 4):
            self.entry(parent, row, label, key)
        app.test_button = ttk.Button(parent, text='Start test (figure 8)', command=lambda: app.start_output(test=True))
        app.test_button.grid(row=8, column=0, sticky='w', pady=8)
        self.label(parent, text='No joystick needed. Sends OSC around the initial target (marker or pan/tilt, per the applied control mode) at the test brightness; joystick input is ignored. Use Stop output above to end the test.').grid(row=9, column=0, columnspan=3, sticky='w', pady=4)
        ttk.Label(parent, text='OSC reception', font=self.state_font).grid(row=10, column=0, columnspan=3, sticky='w', pady=(20, 8))
        self.label(parent, text='UDP send success does not confirm reception. In onPC, use EchoInput and System Monitor to check incoming commands. Check Input, Receive, Receive Command, Interface/IP, port and prefix.').grid(row=11, column=0, columnspan=3, sticky='w')
        self.label(parent, variable=app.fault_label, style='Fault.TLabel').grid(row=12, column=0, columnspan=3, sticky='w', pady=12)
        self.release_ack = ttk.Button(parent, text='Acknowledge release warning', command=lambda: app.clear_fault('release'))
        self.release_ack.grid(row=13, column=0, sticky='w')

    def editor_values(self):
        app = self.app
        return tuple(variable.get() for variable in (app.button_id, app.button_action, app.press_command, app.release_command))

    def mapping_pending(self):
        return self.editor_values() != self.editor_baseline

    def editor_loaded(self):
        self.editor_baseline = self.editor_values()
        self.refresh()

    def restore_selection(self):
        table = self.app.button_table
        key = self.editor_baseline[0]
        selected = (key,) if key in table.get_children() else ()
        if table.selection() != selected:
            table.selection_set(selected)

    def discard_editor(self):
        for variable, value in zip((self.app.button_id, self.app.button_action, self.app.press_command, self.app.release_command), self.editor_baseline):
            variable.set(value)
        self.restore_selection()
        self.app.update_button_editor()
        self.refresh()

    def set_feedback(self, key, text):
        if key in self.axis_feedback:
            self.axis_feedback[key].set(text)

    def changed(self, *args):
        self.refresh()

    def refresh(self):
        app, active = self.app, self.app.controller.active
        for layout in self.page_layouts:
            layout()
        self.resize()
        self.apply_field_states()
        try:
            draft = app.draft_settings()
            dirty = draft.to_dict() != app.settings.to_dict()
        except ValueError:
            draft = None
            dirty = True
        pending = self.mapping_pending()
        self.save_state.set('Unsaved changes' if dirty or pending else 'Settings saved')
        self.mapping_state.set('Editor changes — Add / update mapping, then Save settings.' if pending else
                               'Mappings are saved with Save settings.')
        self.editing_state.set('Output is running. Settings are available to read; stop output to edit.' if active else
                               'Save settings to apply changes. Start and stopped Reset also save and apply them.')
        s = app.settings
        pan_tilt = s.control_mode == 'pan_tilt'
        target = f'Group {s.fixture_group} pan/tilt' if pan_tilt else f'MArker {s.marker_id}'
        self.summary.set(f'{s.device_name or "No saved joystick"}  ·  {target}  ·  OSC {s.host}:{s.port}' +
                         (f' /{s.prefix}' if s.prefix else '') +
                         (f'  ·  PSN tracker {s.psn_tracker_id} → {s.psn_group}:{s.psn_port} via {s.psn_interface}'
                          if not pan_tilt and s.position_output == 'psn' else ''))
        self.stage_title.set('Pan / tilt' if pan_tilt else 'Tracked target · top view')
        reason = ''
        if active:
            reason = 'OSC sent · reception unconfirmed' + (' · joystick ignored during test' if app.controller.test else '')
        elif app.learning:
            reason = 'Finish learning before starting output.'
        elif not (app.joystick and app.joystick.handle):
            reason = 'Select a joystick in Setup → Joystick; Refresh after reconnecting.'
        elif pending:
            reason = 'Finish the button mapping in Setup → Buttons before starting.'
        elif draft is None:
            reason = 'Check settings in Setup before starting; Save settings identifies invalid fields.'
        else:
            try:
                Motion(draft).check_axes(app.axes)
                reason = 'Ready · Start sends the displayed target and current slider brightness.'
            except ValueError:
                reason = 'Check axis mappings in Setup → Joystick before starting.'
        self.readiness.set(reason)
        ready = not active and not app.learning and not pending and draft is not None and bool(app.joystick and app.joystick.handle)
        if ready:
            try:
                Motion(draft).check_axes(app.axes)
            except ValueError:
                ready = False
            if any(int(key) >= len(app.buttons) for key in draft.buttons):
                ready = False
                self.readiness.set('Check button numbers in Setup → Buttons before starting.')
        app.start_button.configure(state='normal' if ready else 'disabled')
        app.stop_button.configure(state='normal' if active else 'disabled')
        app.test_button.configure(state='disabled' if active or app.learning or pending or draft is None else 'normal')
        app.save_button.configure(state='disabled' if active else 'normal')
        app.reset_button.configure(state='disabled' if active and s.reset_locked else 'normal')
        if (s.control_mode == 'marker' and s.position_output == 'psn') or app.streamer is not None:
            if not app.release_button.winfo_manager():
                app.release_button.pack(side='left', padx=(16, 0))
        else:
            app.release_button.pack_forget()
        app.release_button.configure(state='normal' if app.streamer is not None else 'disabled')
        self.state_label.configure(style='Test.TLabel' if active and app.controller.test else 'Running.TLabel' if active else 'TLabel')
        self.reset_state.set(('Locked during output. ' if s.reset_locked else 'Unlocked during output. ') +
                             'Reset restores initial target and zoom / iris; brightness is retained.')
        self.zoom.set(app.controller.motion.zoom_level if s.zoom_enabled else 0)
        self.zoom_meter.state(['!disabled'] if s.zoom_enabled else ['disabled'])
        self.brightness_context.set('Test level · no MA feedback' if active and app.controller.test else
                                    'Sent level · no MA feedback' if active else 'Slider preview · output stopped')
        level = app.controller.last_brightness if active else None
        if not active and app.axes and app.joystick and app.joystick.handle:
            try:
                level = app.controller.motion.brightness(app.axes)
            except ValueError:
                pass
        self.brightness.set(level if level is not None else 0)
        for key, (text, meter) in self.axis_inputs.items():
            try:
                index = int(app.values[key].get())
                if active and app.controller.test or not app.joystick or not app.joystick.handle:
                    raise IndexError
                if index < 0:
                    raise ValueError
                value = app.axes[index]
                text.set(f'Input {value:+.2f}')
                meter.set((clamp(value, -1, 1) + 1) * 50)
            except (ValueError, IndexError):
                text.set('Input —')
                meter.set(50)
        if app.fault_label.get():
            self.fault.pack(fill='x', pady=(10, 0), before=self.footer)
        else:
            self.fault.pack_forget()
        self.release_ack.configure(state='normal' if 'release' in app.faults else 'disabled')
        self.draw_stage()

    def inapplicable_widgets(self):
        """Editors that belong to the other control mode, from the draft selector (not the parsed draft)."""
        mode = self.app.values['control_mode'].get()
        keys = PAN_TILT_FIELDS if mode == 'marker' else MARKER_FIELDS if mode == 'pan_tilt' else ()
        return {self.fields[key] for key in keys if key in self.fields}

    def apply_field_states(self):
        """Disabled = output running, or the field belongs to the other control mode."""
        running = self.app.controller.active
        inapplicable = self.inapplicable_widgets()
        for widget, base in self.editable:
            state = 'disabled' if running or widget in inapplicable else base
            if self.field_states.get(widget) != state:
                widget.configure(state=state)
                self.field_states[widget] = state
        index = 1 if self.app.values['control_mode'].get() == 'pan_tilt' else 0
        for key, texts in AXIS_CAPTIONS.items():
            if self.caption_texts.get(key) != texts[index]:
                self.field_captions[key].configure(text=texts[index])
                self.caption_texts[key] = texts[index]

    def set_running(self, running):
        # refresh() recomputes every editor's state from controller.active and the draft mode.
        self.app.update_button_editor()
        self.refresh()

    def clear_errors(self):
        for key, widget in self.fields.items():
            widget.state(['!invalid'])
            self.field_captions[key].configure(style='TLabel')

    def show_error(self, error):
        self.clear_errors()
        keys = getattr(error, 'fields', ())
        for key in keys:
            if key in self.fields:
                self.fields[key].state(['invalid'])
                self.field_captions[key].configure(style='Fault.TLabel')
        if 'buttons' in keys:
            page = self.mapping_page
        else:
            page = next((self.field_pages[key] for key in keys if key in self.field_pages), None)
        if page:
            notebook, shell, body = page
            self.app.notebook.select(2 if notebook is self.app.notebook else 1)
            notebook.select(shell)
            key = next((key for key in keys if key in self.fields), None)
            if key:
                if key in self.advanced:
                    self.advanced[key][0].set(True)
                widget = self.fields[key]
                widget.focus_set()
                self.app.root.after_idle(lambda: self.reveal(body, widget))
            label = self.field_labels.get(key, 'Button mapping')
            text = f'{label}: {error}'
            if key and self.fields[key] in self.inapplicable_widgets():
                text += f' Switch Control to {"Pan-tilt" if key in PAN_TILT_FIELDS else "Marker"} to correct it.'
            self.app.status.set(text)

    def reveal(self, body, widget):
        canvas = body.scroll_canvas
        if body.winfo_height() > canvas.winfo_height():
            y = widget.winfo_rooty() - body.winfo_rooty()
            top = canvas.canvasy(0)
            if y < top or y + widget.winfo_height() > top + canvas.winfo_height():
                canvas.yview_moveto(max(0, y - 20) / body.winfo_height())

    def bind_scrolling(self, parent):
        for child in parent.winfo_children():
            self.bind_scrolling(child)
        widget = parent
        body = widget
        while body is not None and not hasattr(body, 'scroll_canvas'):
            body = body.master
        if body is not None:
            def wheel(event, canvas=body.scroll_canvas):
                if canvas.bbox('all') and canvas.bbox('all')[3] > canvas.winfo_height():
                    delta = -1 if event.num == 4 or event.delta > 0 else 1
                    canvas.yview_scroll(delta, 'units')
                    return 'break'
            for event in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                widget.bind(event, wheel, add='+')
            if widget.winfo_class() in ('TEntry', 'TCombobox'):
                widget.bind('<FocusIn>', lambda event, b=body, w=widget: self.reveal(b, w), add='+')

    def resize(self):
        for label in self.wrapping:
            # Hidden pages have width 1; wait until the section has been laid out.
            width = label.master.winfo_width()
            if width > 80:
                wrap = max(160, width - 40)
                if self.wrap_widths.get(label) != wrap:
                    label.configure(wraplength=wrap)
                    self.wrap_widths[label] = wrap

    def draw_stage(self):
        canvas, s = self.stage, self.app.settings
        pan_tilt = s.control_mode == 'pan_tilt'
        if pan_tilt:
            x_min, x_max, y_min, y_max = s.pan_min, s.pan_max, s.tilt_min, s.tilt_max
            x_name, y_name, unit = 'Pan', 'Tilt', '%'
            x, y = self.app.controller.motion.pan_tilt
        else:
            x_min, x_max, y_min, y_max = s.x_min, s.x_max, s.y_min, s.y_max
            x_name, y_name, unit = 'X', 'Y', ' m'
            x, y, _ = self.app.controller.motion.xyz
        width, height = max(160, canvas.winfo_width()), max(130, canvas.winfo_height())
        scale = min((width - 90) / (x_max - x_min), (height - 65) / (y_max - y_min))
        stage_width, stage_height = (x_max - x_min) * scale, (y_max - y_min) * scale
        left, top = (width - stage_width) / 2, (height - stage_height) / 2
        right, bottom = left + stage_width, top + stage_height
        canvas.delete('all')
        color = self.foreground
        canvas.create_rectangle(left, top, right, bottom, outline=color, tags='limits')
        canvas.create_text((left+right)/2, top-14, text=f'{y_name} {y_max:g}{unit}', fill=color)
        canvas.create_text((left+right)/2, bottom+14, text=f'{y_name} {y_min:g}{unit}', fill=color)
        canvas.create_text(left-8, (top+bottom)/2, text=f'{x_name}\n{x_min:g}{unit}', anchor='e', fill=color)
        canvas.create_text(right+8, (top+bottom)/2, text=f'{x_name}\n{x_max:g}{unit}', anchor='w', fill=color)
        px = left + (clamp(x, x_min, x_max) - x_min) * scale
        py = bottom - (clamp(y, y_min, y_max) - y_min) * scale
        canvas.create_oval(px-5, py-5, px+5, py+5, fill=color, outline=color, tags='target')
        if not pan_tilt and self.app.streamer is not None and not self.app.controller.active:
            hx, hy, _ = self.app.streamer.position
            hpx = left + (clamp(hx, x_min, x_max) - x_min) * scale
            hpy = bottom - (clamp(hy, y_min, y_max) - y_min) * scale
            canvas.create_oval(hpx-8, hpy-8, hpx+8, hpy+8, outline=color, dash=(3, 2), tags='held')
