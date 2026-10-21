-- Native MA panel: a compact Live strip that expands to paginated Setup tabs in the same
-- BaseInput. Editing and confirmation never block the worker lease.
local json, schema = ...
local UI = {}
UI.__index = UI

-- A pending Release/Close confirmation outranks faults so the operator sees what the next press does.
local NOTICE_COLORS = {info='Global.Text', warning='Global.WarningText', error='Global.ErrorText',
                       confirm='Global.WarningText'}
local SEVERITY = {info=1, warning=2, error=3, confirm=4}
local STATE_COLORS = {['RUNNING']='Global.SuccessText', ['TEST RUNNING']='Global.WarningText',
                      ['PSN HOLDING']='Global.WarningText', ['STOPPED']='Global.Text',
                      ['NO HELPER']='Global.ErrorText'}
local ON_OFF = {[true]='On', [false]='Off'}
local TABS = {'Joystick', 'Target', 'Levels', 'Buttons', 'Diagnostics'}
local BODY_ROWS = 9
-- Root rows: title, live summary, controls, notice, then (Setup only) tabs, page actions, body, page footer.
local ROW_SIZES = {50, 116, 56, 52, 46, 46, BODY_ROWS * 38, 50}
local COMPACT_ROWS = 4
local NOTICE_BUTTON = 230

local FIELDS = {}
for _, page in ipairs(TABS) do
    for _, field in ipairs(schema[page] or {}) do FIELDS[field.key] = field end
end

local function copy(value)
    return json.decode(json.encode(value))
end

local function grid(parent, kind, columns, rows, anchors)
    local w = parent:Append(kind)
    w.Columns = columns
    w.Rows = rows
    w.Anchors = anchors
    return w
end

local function text(parent, kind, value, anchors)
    local w = parent:Append(kind)
    w.Text = value
    w.Anchors = anchors
    w.Font = 'Regular20'
    w.Margin = '3,3,3,3'
    return w
end

local function label(parent, anchors)
    local w = text(parent, 'UIObject', '', anchors)
    w.Interactive = false
    w.TextalignmentH = 'Left'
    return w
end

local function fixed(item, size)
    item.SizePolicy = 'Fixed'
    item.Size = tostring(size)
end

local function number(v)
    return type(v) == 'number' and string.format('%.2f', v) or '—'
end

local function plain(v)
    return type(v) == 'number' and string.format('%.10g', v) or tostring(v)
end

-- Editor text for a value; dead zones are stored as fractions and shown as percentages.
local function display(field, value)
    if type(value) ~= 'number' then return tostring(value or '') end
    return plain(value * (field.scale or 1))
end

local function present(v)
    return v ~= nil and v ~= '' and v ~= false
end

-- Settings compared for the unsaved indicator; the helper sets device_name when a joystick opens.
local function comparable(config)
    local settings = {}
    for key, value in pairs(config.settings or {}) do
        if key ~= 'device_name' then settings[key] = value end
    end
    return json.encode({settings=settings, output_mode=config.output_mode})
end

local function devices_key(data)
    local parts = {}
    for _, d in ipairs(data.devices or {}) do parts[#parts + 1] = tostring(d.index) .. ':' .. tostring(d.name) end
    return table.concat(parts, '\n')
end

local function locked(data)
    return data.config and data.config.settings.reset_locked
end

function UI.new(signal, component, config, python, on_action, owner)
    local self = setmetatable({signal=signal, component=component, draft=copy(config), python=python,
        on_action=on_action, expanded=false, page='Joystick', subpage=1, page_count=1, data={},
        bindings={}, shown=setmetatable({}, {__mode='k'}),
        button_edit={id='0', action='command', press='', release=''}}, UI)
    if owner then owner.ui = self end -- Make a partially constructed panel cleanable.
    local root = GetFocusDisplay().ScreenOverlay:Append('BaseInput')
    self.root = root
    root.Name = 'JoystickFollowspotPanel'
    root.W = 1100
    root.Columns = 1
    root.Rows = #ROW_SIZES
    root.AutoClose = false
    root.CloseOnEscape = false
    self.controls = {}

    local title = grid(root, 'TitleBar', 2, 1, '0,0')
    fixed(title[2][2], 300)
    text(title, 'TitleButton', 'JOYSTICK FOLLOWSPOT   1.0', '0,0')
    self.controls.Close = self:button(title, 'Close', 'Close', '1,0', function() self:act('close') end)

    local live = grid(root, 'UILayoutGrid', 2, 4, '0,1')
    fixed(live[2][1], 280)
    self.state = text(live, 'UIObject', 'STOPPED', '0,0,0,2')
    self.state.Name = 'State'
    self.state.Interactive = false
    self.state.Font = 'Regular28'
    self.target_line = label(live, '1,0')
    self.levels_line = label(live, '1,1')
    self.device_line = label(live, '1,2')
    self.hint = label(live, '0,3,1,3')
    self.hint.Name = 'Hint'

    local bar = grid(root, 'UILayoutGrid', 7, 1, '0,2')
    for i, item in ipairs({{'Start', 'Start output', 'start'}, {'Stop', 'Stop', 'stop'},
        {'Reset', 'Reset target', 'reset'}, {'Release', 'Release PSN', 'release'},
        {'Test', 'Test figure 8', 'test'}, {'ResetLock', 'Reset lock', 'reset_lock'}}) do
        self.controls[item[1]] = self:button(bar, item[1], item[2], tostring(i - 1) .. ',0', function()
            self:act(item[3])
        end)
    end
    self.controls.Setup = self:button(bar, 'Setup', 'Setup', '6,0', function() self:set_expanded(true) end)
    self.controls.Collapse = self:button(bar, 'Collapse', 'Hide setup', '6,0', function() self:set_expanded(false) end)

    self.notice_row = grid(root, 'UILayoutGrid', 3, 1, '0,3')
    fixed(self.notice_row[2][2], 0)
    fixed(self.notice_row[2][3], 0)
    self.status = label(self.notice_row, '0,0')
    self.status.Name = 'Status'
    self.status.TextAutoAdjust = true
    self.controls.CancelConfirm = self:button(self.notice_row, 'CancelConfirm', 'Cancel confirmation', '1,0',
        function() self:act('cancel_confirm') end)
    self.controls.AckWarning = self:button(self.notice_row, 'AckWarning', 'Ack release warning', '2,0',
        function() self:act('ack_warning') end)

    self.setup_parts = {}
    local tabs = grid(root, 'UILayoutGrid', #TABS, 1, '0,4')
    self.setup_parts[#self.setup_parts + 1] = tabs
    self.tabs = {}
    for i, page in ipairs(TABS) do
        self.tabs[page] = self:button(tabs, 'Tab_' .. page, page, tostring(i - 1) .. ',0', function()
            self:capture()
            self.page = page
            self.subpage = 1
            self:render()
        end)
    end

    local actions = grid(root, 'UILayoutGrid', 6, 1, '0,5')
    self.setup_parts[#self.setup_parts + 1] = actions
    self.action_buttons = {}
    for i = 1, 6 do
        local index = i
        self.action_buttons[i] = self:button(actions, 'Action' .. i, '', tostring(i - 1) .. ',0', function()
            local item = self.action_items[index]
            if item then
                self:capture()
                item[2]()
            end
        end)
    end

    -- Columns: label (0-1), editor (2-3), Learn (4); table rows use one column per cell.
    local body = grid(root, 'UILayoutGrid', 5, BODY_ROWS, '0,6')
    self.setup_parts[#self.setup_parts + 1] = body
    fixed(body[2][1], 120)
    fixed(body[2][2], 250)
    fixed(body[2][5], 125)
    self.rows = {}
    for i = 1, BODY_ROWS do
        local index = i
        local r = tostring(i - 1)
        local row = {}
        row.label = label(body, '0,' .. r .. ',1,' .. r)
        row.note = label(body, '0,' .. r .. ',4,' .. r)
        row.edit = text(body, 'LineEdit', '', '2,' .. r .. ',3,' .. r)
        row.edit.ContentDriven = true
        row.edit.ShowKeyboardButton = true
        row.toggle = self:button(body, 'Value' .. i, '', '2,' .. r .. ',3,' .. r, function() self:toggle(index) end)
        row.extra = self:button(body, 'Learn' .. i, 'Learn', '4,' .. r, function() self:learn(index) end)
        row.wide = self:button(body, 'Row' .. i, '', '0,' .. r .. ',4,' .. r, function() self:pick(index) end)
        row.cells = {}
        for j, anchors in ipairs({'0,' .. r, '1,' .. r, '2,' .. r, '3,' .. r .. ',4,' .. r}) do
            row.cells[j] = self:button(body, 'Cell' .. i .. '_' .. j, '', anchors, function() self:pick(index) end)
        end
        self.rows[i] = row
    end

    local footer = grid(root, 'UILayoutGrid', 5, 1, '0,7')
    self.setup_parts[#self.setup_parts + 1] = footer
    fixed(footer[2][1], 160)
    fixed(footer[2][2], 200)
    fixed(footer[2][3], 160)
    fixed(footer[2][5], 260)
    self.controls.PreviousPage = self:button(footer, 'PreviousPage', 'Previous', '0,0', function() self:turn(-1) end)
    self.page_label = text(footer, 'UIObject', '', '1,0')
    self.page_label.Name = 'PageLabel'
    self.page_label.Interactive = false
    self.controls.NextPage = self:button(footer, 'NextPage', 'Next', '2,0', function() self:turn(1) end)
    self.draft_label = label(footer, '3,0')
    self.draft_label.Name = 'Draft'
    self.controls.Save = self:button(footer, 'Save', 'Save settings', '4,0', function() self:act('save') end)

    self:render()
    return self
end

function UI:button(parent, name, caption, anchors, callback)
    local button = text(parent, 'Button', caption, anchors)
    button.Name = name
    local key = 'FS_' .. name
    self.signal[key] = callback
    button.PluginComponent = self.component
    button.Clicked = key
    return button
end

-- Assign a widget property only when it changes, so 30 Hz status updates do not repaint idle widgets.
function UI:set(widget, property, value)
    local seen = self.shown[widget]
    if not seen then
        seen = {}
        self.shown[widget] = seen
    end
    if seen[property] ~= value then
        seen[property] = value
        widget[property] = value
    end
end

function UI:act(action, payload)
    self:capture()
    self.on_action(action, payload or {})
end

function UI:target(field)
    if field.button then return self.button_edit end
    if field.root then return self.draft end
    return self.draft.settings
end

-- Copy the visible text editors into `draft`/`edit`; returns the typed Python path, if shown.
-- An editor still showing its value's text keeps the exact stored value.
function UI:collect(draft, edit)
    local python = nil
    for i, item in ipairs(self.bindings) do
        local field = item.kind == 'field' and item.field
        if field and field.kind ~= 'bool' and field.kind ~= 'choice' then
            local holder = field.button and edit or field.root and draft or draft.settings
            local current = field.python and self.python or holder[field.key]
            local value = tostring(self.rows[i].edit.Content or '')
            if value == display(field, current) then
                value = current
            elseif field.kind == 'int' or field.kind == 'float' then
                local n = tonumber(value)
                if n and field.scale then
                    value = n / field.scale
                elseif n then
                    value = math.tointeger(n) or n
                end
            end
            if field.python then
                python = value
            else
                holder[field.key] = value
            end
        end
    end
    return python
end

function UI:capture()
    local python = self:collect(self.draft, self.button_edit)
    if python then self.python = python end
end

function UI:toggle(index)
    self:capture()
    local item = self.bindings[index]
    if not item or item.kind ~= 'field' then return end
    local field = item.field
    local target = self:target(field)
    if field.kind == 'bool' then
        target[field.key] = not target[field.key]
    else
        local choices = field.choices
        local at = 1
        for i, v in ipairs(choices) do
            if v == target[field.key] then at = i % #choices + 1 end
        end
        target[field.key] = choices[at]
        if field.key == 'control_mode' and target[field.key] == 'pan_tilt' then self.draft.output_mode = 'direct' end
    end
    self:render()
end

function UI:learn(index)
    local item = self.bindings[index]
    if not item or item.kind ~= 'field' or not item.field.learn then return end
    local field = item.field
    self:act('learn', {key=field.learn == true and field.key or field.learn})
end

-- A tapped device row is chosen for Open; a tapped mapping row loads into the editor.
function UI:pick(index)
    local item = self.bindings[index]
    if not item then return end
    self:capture()
    if item.kind == 'device' then
        self.device_choice = {index=item.device.index, name=item.device.name}
        self:render()
    elseif item.kind == 'mapping' then
        self.button_edit.id = item.id
        self:load_mapping()
    end
end

function UI:load_mapping()
    local saved = self.draft.settings.buttons[tostring(self.button_edit.id)] or {}
    self.button_edit.action = saved.action or 'command'
    self.button_edit.press = saved.press or ''
    self.button_edit.release = saved.release or ''
    self.mapping_saved = json.encode(self.button_edit)
    self:render()
end

function UI:clear_editor()
    self.button_edit.press = ''
    self.button_edit.release = ''
    self.button_edit.action = 'command'
    self.mapping_saved = json.encode(self.button_edit)
end

function UI:set_expanded(expanded)
    self:capture()
    self.expanded = expanded
    self:render()
end

function UI:turn(step)
    self:capture()
    self.subpage = math.max(1, math.min(self.page_count, self.subpage + step))
    self:render()
end

function UI:chosen_device()
    local choice = self.device_choice
    if not choice then return nil end
    for _, d in ipairs(self.data.devices or {}) do
        if d.index == choice.index and d.name == choice.name then return d end
    end
    return nil
end

function UI:fields()
    local result = {}
    local s = self.draft.settings
    for _, field in ipairs(schema[self.page] or {}) do
        if (not field.mode or s.control_mode == field.mode)
            and (not field.output or self.draft.output_mode == field.output) then
            result[#result + 1] = field
        end
    end
    return result
end

function UI:raw_input()
    local d = self.data
    if not d.device_open then return 'No joystick open.' end
    local raw = {}
    for i, v in ipairs(d.axes or {}) do raw[#raw + 1] = string.format('%d:%+.3f', i - 1, v) end
    local down = {}
    for i, v in ipairs(d.buttons or {}) do
        if v then down[#down + 1] = tostring(i - 1) end
    end
    return 'Axes ' .. table.concat(raw, '  ') .. '    Buttons ' .. (#down > 0 and table.concat(down, ',') or 'none')
end

-- Draft-based Start preview; Live shows what is applied.
function UI:preview_lines()
    local d, s = self.data, self.draft.settings
    local p = d.preview or {}
    local xyz = p.xyz or {s.initial_x, s.initial_y, s.z}
    local pt = p.pan_tilt or {s.initial_pan, s.initial_tilt}
    local function bounded(v, low, high)
        v, low, high = tonumber(v), tonumber(low), tonumber(high)
        return v and low and high and math.max(low, math.min(high, v)) or nil
    end
    local axis = tonumber(s.axis_slider)
    local slider = axis and (d.axes or {})[axis + 1]
    local level = slider and math.max(0, math.min(100, (slider + 1) * 50)) or nil
    if level and s.invert_slider then level = 100 - level end
    local marker = s.control_mode == 'marker'
    return {
        'Next Start: ' .. (marker and ('MArker ' .. plain(s.marker_id) .. ' · '
            .. self:choice_label(FIELDS.output_mode, self.draft.output_mode))
            or ('Group ' .. plain(s.fixture_group) .. ' · pan / tilt (changes selection)')),
        marker and ('Position X ' .. number(bounded(xyz[1], s.x_min, s.x_max)) .. '  Y '
            .. number(bounded(xyz[2], s.y_min, s.y_max)) .. '  Z ' .. number(tonumber(s.z)) .. ' m')
            or ('Pan ' .. number(bounded(pt[1], s.pan_min, s.pan_max)) .. '  Tilt '
            .. number(bounded(pt[2], s.tilt_min, s.tilt_max)) .. ' %'),
        'Brightness: Page ' .. plain(s.executor_page) .. ' / Executor ' .. plain(s.executor_number)
            .. ' · Master · current slider ' .. number(level) .. '%',
        'Test uses ' .. plain(s.test_brightness) .. '% for ' .. plain(s.test_period) .. ' seconds.',
        self.draft.output_mode == 'psn' and marker
            and 'PSN needs MA tracker mapping and the matching local interface.'
            or 'Direct output uses the programmer. Blind, Clear and playback priorities apply.',
        'Settings persist in this show/user profile. Save the MA show to keep them.',
    }
end

function UI:sections()
    local sections, index = {}, {}
    local function add(title, item)
        local section = index[title]
        if not section then
            section = {title=title, items={}}
            index[title] = section
            sections[#sections + 1] = section
        end
        section.items[#section.items + 1] = item
    end
    if self.page == 'Joystick' then
        local devices = self.data.devices or {}
        for i, d in ipairs(devices) do add('Device', {kind='device', device=d, position=i}) end
        if #devices == 0 then add('Device', {kind='note', text='No joysticks listed. Press Refresh.'}) end
        add('Device', {kind='live', text=function() return self:raw_input() end})
    end
    for _, field in ipairs(self:fields()) do add(field.section, {kind='field', field=field}) end
    if self.page == 'Buttons' then
        local ids = {}
        for key in pairs(self.draft.settings.buttons) do ids[#ids + 1] = key end
        table.sort(ids, function(a, b) return (tonumber(a) or 0) < (tonumber(b) or 0) end)
        add('Saved mappings', {kind='table_head'})
        for _, id in ipairs(ids) do add('Saved mappings', {kind='mapping', id=id, map=self.draft.settings.buttons[id]}) end
        if #ids == 0 then add('Saved mappings', {kind='note', text='No button mappings in the draft.'}) end
    end
    if self.page == 'Diagnostics' then
        for i = 1, #self:preview_lines() do
            add('Start preview', {kind='live', text=function() return self:preview_lines()[i] end})
        end
    end
    return sections
end

-- Fill pages of BODY_ROWS, starting a new page at a section boundary when the section would not fit.
function UI:pages()
    local pages, current = {}, {}
    local function flush()
        if #current > 0 then
            pages[#pages + 1] = current
            current = {}
        end
    end
    for _, section in ipairs(self:sections()) do
        local block = {{kind='heading', text=section.title}}
        for _, item in ipairs(section.items) do block[#block + 1] = item end
        if #current + #block > BODY_ROWS then flush() end
        for _, item in ipairs(block) do
            if #current == BODY_ROWS then
                flush()
                current[1] = {kind='heading', text=section.title .. ' (continued)'}
            end
            current[#current + 1] = item
        end
    end
    flush()
    if #pages == 0 then pages[1] = {} end
    return pages
end

function UI:choice_label(field, value)
    if field.kind == 'bool' then return ON_OFF[value == true] end
    return field.labels and field.labels[tostring(value)] or tostring(value)
end

function UI:editable()
    return not self.data.running and not self.busy
end

function UI:action_list()
    local d = self.data
    local s = self.draft.settings
    local editable = self:editable()
    local helper = editable and d.ready == true
    local function action(name, payload) return function() self:act(name, payload) end end
    if self.page == 'Joystick' then
        local chosen = self:chosen_device()
        return {
            {'Refresh', action('refresh'), 'Refresh', helper},
            {'Open chosen device', function()
                self:act('select', {index=chosen.index, name=chosen.name})
            end, 'OpenDevice', helper and chosen ~= nil},
            {'Calibrate X / Y', function()
                self:act('calibrate', {axis_x=s.axis_x, axis_y=s.axis_y})
            end, 'Calibrate', helper and d.device_open == true},
            {'Cancel learn', action('cancel_learn'), 'CancelLearn', present(d.learning)},
        }
    elseif self.page == 'Levels' then
        return {{'Calibrate zoom centre', function()
            self:act('calibrate', {keys={'zoom'}, axis_zoom=s.axis_zoom})
        end, 'CalibrateZoom', helper and d.device_open == true and s.zoom_enabled == true}}
    elseif self.page == 'Target' and s.control_mode == 'marker' and self.draft.output_mode == 'direct' then
        return {{'Read MA movement space', action('read_space'), 'ReadSpace', editable}}
    elseif self.page == 'Buttons' then
        return {
            {'Learn button', action('learn', {key='button'}), 'LearnButton', helper and d.device_open == true},
            {'Load mapping', function() self:load_mapping() end, 'LoadMapping', editable},
            {'Add / update', function()
                local e = self.button_edit
                local id = tonumber(e.id)
                if not id or id < 0 or id % 1 ~= 0 then
                    self:notify('Enter a non-negative whole button index.', 'error')
                    return
                end
                local map = e.action == 'command' and {press=e.press, release=e.release} or {action=e.action}
                self.draft.settings.buttons[tostring(math.tointeger(id) or id)] = map
                self.mapping_saved = json.encode(e)
                self:notify('Mapping added to the draft. Save settings to apply it.', 'info')
                self:render()
            end, 'AddMapping', editable},
            {'Remove mapping', function()
                self.draft.settings.buttons[tostring(self.button_edit.id)] = nil
                self:clear_editor()
                self:notify('Mapping removed from the draft. Save settings to apply it.', 'info')
                self:render()
            end, 'RemoveMapping', editable},
            {'Discard editor', function()
                self:clear_editor()
                self:render()
            end, 'DiscardEditor', editable},
        }
    elseif self.page == 'Diagnostics' then
        return {{'Reconnect helper', action('reconnect'), 'Reconnect', not d.running and not d.holding}}
    end
    return {}
end

function UI:layout()
    local height = 14
    for i, size in ipairs(ROW_SIZES) do
        local shown = i <= COMPACT_ROWS or self.expanded
        fixed(self.root[1][i], shown and size or 0)
        if shown then height = height + size end
    end
    for _, part in ipairs(self.setup_parts) do self:set(part, 'Visible', self.expanded) end
    self.root.H = height
    self.layout_expanded = self.expanded
end

-- Row widgets are reused across pages; `put` collects each widget's final state so the
-- change cache sees one assignment per property instead of a hide followed by a show.
local function row_defaults(put, row, index)
    for _, part in ipairs({'label', 'note', 'edit', 'toggle', 'extra', 'wide'}) do put(row[part], 'Visible', false) end
    for j, cell in ipairs(row.cells) do
        put(cell, 'Visible', false)
        put(cell, 'Name', 'Cell' .. index .. '_' .. j)
    end
    put(row.label, 'Name', 'Label' .. index)
    put(row.edit, 'Name', 'Edit' .. index)
    put(row.toggle, 'Name', 'Value' .. index)
    put(row.extra, 'Name', 'Learn' .. index)
    put(row.wide, 'Name', 'Row' .. index)
end

function UI:show_field(put, row, field, editable)
    local target = self:target(field)
    local value = field.python and self.python or target[field.key]
    local marked = self.error_key == field.key
    put(row.label, 'Visible', true)
    put(row.label, 'Name', 'label_' .. field.key)
    put(row.label, 'Text', (marked and '! ' or '') .. field.label)
    put(row.label, 'TextColor', marked and 'Global.ErrorText' or 'Global.Text')
    local enabled = editable and (not field.zoom or self.draft.settings.zoom_enabled == true)
    if field.command_only and self.button_edit.action ~= 'command' then enabled = false end
    if field.kind == 'bool' or field.kind == 'choice' then
        put(row.toggle, 'Visible', true)
        put(row.toggle, 'Name', 'field_' .. field.key)
        put(row.toggle, 'Text', self:choice_label(field, value))
        put(row.toggle, 'Enabled', enabled)
    else
        put(row.edit, 'Visible', true)
        put(row.edit, 'Name', 'field_' .. field.key)
        put(row.edit, 'Enabled', enabled)
        -- Written directly: the operator's typing changes Content behind the change cache.
        row.edit.Content = display(field, value)
    end
    if field.learn then
        put(row.extra, 'Visible', true)
        put(row.extra, 'Name', 'Learn_' .. field.key)
        put(row.extra, 'Enabled', enabled and self.data.device_open == true)
    end
end

local CELL_SUFFIX = {'', '_action', '_press', '_release'}

local function show_cells(put, row, values, name)
    for j, cell in ipairs(row.cells) do
        put(cell, 'Visible', true)
        put(cell, 'Text', tostring(values[j]))
        if name then put(cell, 'Name', name .. CELL_SUFFIX[j]) end
    end
end

function UI:show_row(row, index, item, editable)
    local want, order = {}, {}
    local function put(widget, property, value)
        if not want[widget] then
            want[widget] = {}
            order[#order + 1] = widget
        end
        want[widget][property] = value
    end
    row_defaults(put, row, index)
    local kind = item and item.kind
    if kind == 'heading' or kind == 'note' or kind == 'live' then
        put(row.note, 'Visible', true)
        put(row.note, 'Font', kind == 'heading' and 'Medium20' or 'Regular20')
        put(row.note, 'Text', kind == 'live' and item.text() or item.text)
    elseif kind == 'field' then
        self:show_field(put, row, item.field, editable)
    elseif kind == 'device' then
        local d = item.device
        local choice = self.device_choice
        local chosen = choice ~= nil and choice.index == d.index and choice.name == d.name
        local open = self.data.device_open and self.data.config and self.data.config.settings.device_name == d.name
        put(row.wide, 'Visible', true)
        put(row.wide, 'Name', 'Device' .. item.position)
        put(row.wide, 'Text', (chosen and '> ' or '') .. tostring(d.name) .. '   (entry ' .. tostring(d.index) .. ')'
            .. (open and '   open' or ''))
        put(row.wide, 'TextColor', chosen and 'Global.Selected' or 'Global.Text')
        put(row.wide, 'BackColor', chosen and 'Button.ActiveBackground' or 'Button.Background')
    elseif kind == 'table_head' then
        show_cells(put, row, {'Index', 'Action', 'Press', 'Release'})
    elseif kind == 'mapping' then
        local map = item.map
        local action = map.action or 'command'
        local command = action == 'command'
        show_cells(put, row, {item.id, self:choice_label(FIELDS.action, action),
            command and present(map.press) and map.press or '—',
            command and present(map.release) and map.release or '—'}, 'Mapping_' .. item.id)
    end
    for _, widget in ipairs(order) do
        for property, value in pairs(want[widget]) do self:set(widget, property, value) end
    end
end

function UI:render()
    if self.layout_expanded ~= self.expanded then self:layout() end
    local editable = self:editable()
    for _, page in ipairs(TABS) do
        local active = page == self.page
        local tab = self.tabs[page]
        self:set(tab, 'Text', active and ('[ ' .. page .. ' ]') or page)
        self:set(tab, 'TextColor', active and 'Global.Selected' or 'Global.Text')
        self:set(tab, 'BackColor', active and 'Button.ActiveBackground' or 'Button.Background')
    end
    local pages = self:pages()
    self.page_count = #pages
    self.subpage = math.max(1, math.min(self.subpage, self.page_count))
    local items = pages[self.subpage]
    self.bindings = {}
    for i, row in ipairs(self.rows) do
        self.bindings[i] = items[i]
        self:show_row(row, i, items[i], editable)
    end
    self.action_items = self:action_list()
    for i, button in ipairs(self.action_buttons) do
        local item = self.action_items[i]
        self:set(button, 'Visible', item ~= nil)
        self:set(button, 'Text', item and item[1] or '')
        self:set(button, 'Name', item and item[3] or 'Action' .. i)
        self:set(button, 'Enabled', item ~= nil and item[4] == true)
    end
    local paged = self.page_count > 1
    self:set(self.controls.PreviousPage, 'Visible', paged)
    self:set(self.controls.NextPage, 'Visible', paged)
    self:set(self.controls.PreviousPage, 'Enabled', self.subpage > 1)
    self:set(self.controls.NextPage, 'Enabled', self.subpage < self.page_count)
    self:set(self.page_label, 'Text', 'Page ' .. self.subpage .. ' of ' .. self.page_count)
    self:update_text()
end

-- Local notices carry a severity; helper faults and release warnings stay visible until cleared.
-- A settings error opens its field; a fault during output never expands Setup.
function UI:notify(message, level, fields)
    self.notice = message and {text=tostring(message), level=level or 'error'} or nil
    if self.error_key then self:unmark() end
    if not self.notice or self.notice.level ~= 'error' or self.data.running then return end
    -- Fields reported by the helper's SettingsError take precedence over text matching.
    local hint = nil
    for _, key in ipairs(fields or {}) do
        local page = self:page_of(key)
        if page and self:reveal(page, key) then return end
        hint = hint or self:reach_hint(key)
    end
    if hint then
        self.notice.text = self.notice.text .. ' ' .. hint
        return
    end
    self:locate(self.notice.text)
end

function UI:page_of(key)
    for _, page in ipairs(TABS) do
        for _, field in ipairs(schema[page] or {}) do
            if field.key == key then return page end
        end
    end
end

-- How to show a field the current control mode or position output hides.
function UI:reach_hint(key)
    local field = FIELDS[key]
    if not field then return nil end
    local selector, value
    if field.mode and self.draft.settings.control_mode ~= field.mode then
        selector, value = FIELDS.control_mode, field.mode
    elseif field.output and self.draft.output_mode ~= field.output then
        selector, value = FIELDS.output_mode, field.output
    else
        return nil
    end
    return 'Switch ' .. selector.label .. ' to ' .. self:choice_label(selector, value) .. ' (Setup > '
        .. self:page_of(selector.key) .. ') to correct it.'
end

function UI:current_notice()
    local d = self.data
    local best = self.notice
    for _, candidate in ipairs({{text=d.fault, level='error'}, {text=d.warning, level='warning'}}) do
        if present(candidate.text) and (not best or SEVERITY[candidate.level] > SEVERITY[best.level]) then
            best = candidate
        end
    end
    return best
end

-- An error naming a settings key or label opens that field's page and marks its label.
function UI:locate(message)
    local lower = message:lower()
    for _, page in ipairs(TABS) do
        for _, field in ipairs(schema[page] or {}) do
            local name = field.label:gsub('%s*%b()$', ''):lower()
            if message:find('%f[%w_]' .. field.key .. '%f[^%w_]') or lower:find(name, 1, true) then
                if self:reveal(page, field.key) then return end
            end
        end
    end
end

function UI:reveal(page, key)
    self:capture()
    local previous = self.page
    self.page = page
    for index, items in ipairs(self:pages()) do
        for _, item in ipairs(items) do
            if item.kind == 'field' and item.field.key == key then
                self.subpage = index
                self.expanded = true
                self.error_key = key
                self:render()
                return true
            end
        end
    end
    self.page = previous
    return false
end

-- Clear the error mark without redrawing the editors, which may hold half-typed values.
function UI:unmark()
    local key = self.error_key
    self.error_key = nil
    for i, item in ipairs(self.bindings) do
        if item.kind == 'field' and item.field.key == key then
            self:set(self.rows[i].label, 'Text', item.field.label)
            self:set(self.rows[i].label, 'TextColor', 'Global.Text')
        end
    end
end

function UI:start_blocker()
    local d = self.data
    if d.helper_gone then return 'No helper running. Reconnect in Setup > Diagnostics.' end
    if d.running then return 'Stop output to edit settings.' end
    if d.ready ~= true then return 'Helper not ready. If this persists, check Diagnostics.' end
    if self.busy then return 'Waiting for the helper.' end
    if present(d.learning) then return 'Finish learning first.' end
    if d.device_open ~= true then return 'Start needs an open joystick. Test needs none.' end
    return nil
end

function UI:draft_state()
    local draft, edit = copy(self.draft), copy(self.button_edit)
    self:collect(draft, edit)
    local nonempty = edit.press ~= '' or edit.release ~= '' or edit.action ~= 'command'
    if nonempty and self.mapping_saved ~= json.encode(edit) then
        return 'Button editor: Add / update or Discard', 'Global.WarningText', true
    end
    if not self.data.config then return '', 'Global.Text', false end
    local ok, same = pcall(function() return comparable(draft) == comparable(self.data.config) end)
    if ok and same then return 'No unsaved changes', 'Global.Text', false end
    return 'Unsaved changes', 'Global.WarningText', true
end

function UI:update_text()
    local d = self.data
    local s = self.draft.settings
    local applied = d.config and d.config.settings or s
    local applied_output = d.config and d.config.output_mode or self.draft.output_mode
    local p = d.preview or {}
    local levels = d.frame or {}
    local state = d.helper_gone and 'NO HELPER' or d.running and (d.test and 'TEST RUNNING' or 'RUNNING')
        or d.holding and 'PSN HOLDING' or 'STOPPED'
    self:set(self.state, 'Text', state)
    self:set(self.state, 'TextColor', STATE_COLORS[state])

    local target
    if applied.control_mode == 'marker' then
        local xyz = p.xyz or {applied.initial_x, applied.initial_y, applied.z}
        target = 'MArker ' .. plain(applied.marker_id) .. ' · ' .. self:choice_label(FIELDS.output_mode, applied_output)
            .. '     X ' .. number(xyz[1]) .. ' m   Y ' .. number(xyz[2]) .. ' m   Z ' .. number(xyz[3]) .. ' m'
        if d.holding then
            local held = d.held_xyz or {}
            target = target .. '     Held ' .. number(held[1]) .. ' / ' .. number(held[2]) .. ' / ' .. number(held[3]) .. ' m'
        end
    else
        local pt = p.pan_tilt or {applied.initial_pan, applied.initial_tilt}
        target = 'Group ' .. plain(applied.fixture_group) .. ' · pan / tilt (changes selection)     Pan '
            .. number(pt[1]) .. ' %   Tilt ' .. number(pt[2]) .. ' %'
    end
    self:set(self.target_line, 'Text', target)
    self:set(self.levels_line, 'Text', 'Brightness ' .. number(levels.brightness or p.brightness) .. ' %     Zoom / iris '
        .. (applied.zoom_enabled and (number(levels.zoom or p.zoom) .. ' %') or 'off'))
    self:set(self.device_line, 'Text', d.device_open and ('Joystick: ' .. tostring(applied.device_name or ''))
        or 'No joystick open')

    local blocker = self:start_blocker()
    local draft_text, draft_color, dirty = self:draft_state()
    local ready_text = 'Ready to start. Start uses the current slider level.'
    if dirty and draft_text == 'Unsaved changes' then
        -- Start applies the draft, so name what it will switch to; the full preview is in Diagnostics.
        ready_text = 'Start applies unsaved changes: ' .. self:preview_lines()[1]:gsub('^Next Start: ', '')
            .. '. Full preview: Setup > Diagnostics.'
    end
    self:set(self.hint, 'Text', blocker or ready_text)

    local ready = d.ready == true
    local busy = self.busy == true
    local running = d.running == true
    local c = self.controls
    self:set(c.Start, 'Enabled', blocker == nil)
    self:set(c.Stop, 'Enabled', running or busy)
    self:set(c.Reset, 'Enabled', ready and not busy and (not running or not applied.reset_locked))
    self:set(c.Release, 'Enabled', d.holding == true)
    self:set(c.Release, 'Text', self.confirm == 'release' and 'CONFIRM release' or 'Release PSN')
    self:set(c.Close, 'Text', self.confirm == 'close' and 'CONFIRM close / release' or 'Close')
    self:set(c.Test, 'Enabled', ready and not running and not busy)
    self:set(c.ResetLock, 'Text', 'Reset lock: ' .. ON_OFF[applied.reset_locked == true])
    self:set(c.ResetLock, 'Enabled', ready)
    self:set(c.Setup, 'Visible', not self.expanded)
    self:set(c.Collapse, 'Visible', self.expanded)

    local confirming = self.confirm ~= nil
    local warned = present(d.warning)
    self:set(c.CancelConfirm, 'Visible', confirming)
    self:set(c.AckWarning, 'Visible', warned)
    self:set(self.notice_row[2][2], 'Size', confirming and tostring(NOTICE_BUTTON) or '0')
    self:set(self.notice_row[2][3], 'Size', warned and tostring(NOTICE_BUTTON) or '0')
    local notice = self:current_notice()
    self:set(self.status, 'Text', notice and notice.text or tostring(d.message or 'Starting helper…'))
    self:set(self.status, 'TextColor', notice and NOTICE_COLORS[notice.level] or 'Global.Text')

    self:set(self.draft_label, 'Text', draft_text)
    self:set(self.draft_label, 'TextColor', draft_color)
    self:set(c.Save, 'Text', dirty and 'Save changes' or 'Save settings')
    self:set(c.Save, 'Enabled', ready and not busy and not running)

    for i, item in ipairs(self.bindings) do
        if item.kind == 'live' then self:set(self.rows[i].note, 'Text', item.text()) end
    end
end

-- Each helper numbers its learn results from 1.
function UI:helper_restarted()
    self.learned_id = nil
end

function UI:refresh(data, busy)
    -- Do not normalize a half-typed number or rewrite the focused editor.
    local before = self.data
    local redraw = before.ready ~= data.ready or before.running ~= data.running
        or before.holding ~= data.holding or before.device_open ~= data.device_open or self.busy ~= busy
        or locked(before) ~= locked(data) or before.learning ~= data.learning
        or devices_key(before) ~= devices_key(data)
    if redraw then self:capture() end
    self.data = data
    self.busy = busy
    if data.learned and data.learned.id ~= self.learned_id then
        self:capture()
        redraw = true
        self.learned_id = data.learned.id
        for key, value in pairs(data.learned.values) do
            if key == 'button' then self.button_edit.id = tostring(value) else self.draft.settings[key] = value end
        end
    end
    if redraw then self:render() else self:update_text() end
end

return UI
