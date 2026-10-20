-- Native, paginated MA panel. Editing and confirmation never block the worker lease.
local json,schema=...
local UI={};UI.__index=UI
local function grid(parent,kind,columns,rows,anchors)
    local w=parent:Append(kind);w.Columns=columns;w.Rows=rows;w.Anchors=anchors
    return w
end
local function text(parent,kind,value,anchors)
    local w=parent:Append(kind);w.Text=value;w.Anchors=anchors;w.Font='Regular20';w.Margin='3,3,3,3'
    return w
end
local function number(v) return type(v)=='number' and string.format('%.2f',v) or '—' end
function UI.new(signal,component,config,python,on_action,owner)
    local self=setmetatable({signal=signal,component=component,draft=json.decode(json.encode(config)),
        python=python,on_action=on_action,page='Live',subpage=1,data={},bindings={},edits={},
        button_edit={id='0',action='command',press='',release=''},device_choice=1},UI)
    if owner then owner.ui=self end -- Make a partially constructed panel cleanable.
    local root=GetFocusDisplay().ScreenOverlay:Append('BaseInput')
    self.root=root;root.Name='JoystickFollowspotPanel';root.W=1100;root.H=760
    root.Columns=1;root.Rows=6;root.AutoClose=false;root.CloseOnEscape=false
    for i,size in ipairs({50,48,48,460,75,65}) do root[1][i].SizePolicy='Fixed';root[1][i].Size=tostring(size) end
    local title=grid(root,'TitleBar',2,1,'0,0')
    text(title,'TitleButton','JOYSTICK FOLLOWSPOT   •   1.0','0,0')
    self:button(title,'TitleClose','Close','1,0',function() self:act('close') end)
    local nav=grid(root,'UILayoutGrid',6,1,'0,1')
    for i,page in ipairs({'Live','Joystick','Target','Levels','Buttons','Diagnostics'}) do
        self:button(nav,'Tab_'..page,page,tostring(i-1)..',0',function()
            self:capture();self.page=page;self.subpage=1;self:render()
        end)
    end
    self.actions=grid(root,'UILayoutGrid',6,1,'0,2');self.action_buttons={}
    for i=1,6 do
        local index=i
        self.action_buttons[i]=self:button(self.actions,'Action'..i,'',tostring(i-1)..',0',function()
            local item=self.action_items[index];if item then self:capture();item[2]() end
        end)
    end
    self.body=grid(root,'UILayoutGrid',3,9,'0,3');self.rows={}
    self.body[2][1].SizePolicy='Fixed';self.body[2][1].Size='370'
    self.body[2][3].SizePolicy='Fixed';self.body[2][3].Size='125'
    for i=1,8 do
        local index=i
        local row={}
        row.label=text(self.body,'UIObject','',string.format('0,%d',i-1));row.label.Interactive=false
        row.edit=text(self.body,'LineEdit','',string.format('1,%d',i-1));row.edit.ContentDriven=true
        row.edit.ShowKeyboardButton=true
        row.toggle=self:button(self.body,'Value'..i,'',string.format('1,%d',i-1),function() self:toggle(index) end)
        row.extra=self:button(self.body,'Learn'..i,'Learn',string.format('2,%d',i-1),function()
            local field=self.bindings[index];if field then self:act('learn',{key=field.key}) end
        end)
        self.rows[i]=row
    end
    self.info=text(self.body,'UIObject','','0,0,2,7');self.info.Interactive=false
    self.info.TextAutoAdjust=true
    self.page_note=text(self.body,'UIObject','','0,8,2,8');self.page_note.Interactive=false;self.page_note.TextAutoAdjust=true
    self.status=text(root,'UIObject','','0,4');self.status.Interactive=false;self.status.TextAutoAdjust=true
    local footer=grid(root,'UILayoutGrid',6,1,'0,5');self.controls={}
    for i,item in ipairs({{'Start','Start output','start'},{'Stop','Stop','stop'},
        {'Reset','Reset target','reset'},{'Release','Release PSN','release'},
        {'Save','Save settings','save'},{'Close','Close','close'}}) do
        self.controls[item[1]]=self:button(footer,item[1],item[2],tostring(i-1)..',0',function() self:act(item[3]) end)
    end
    self:render();return self
end
function UI:button(parent,name,label,anchors,callback)
    local button=text(parent,'Button',label,anchors);button.Name=name
    local key='FS_'..name;self.signal[key]=callback;button.PluginComponent=self.component;button.Clicked=key
    return button
end
function UI:act(action,payload)
    self:capture();self.on_action(action,payload or {})
end
function UI:capture()
    for i,field in ipairs(self.bindings) do
        local row=self.rows[i]
        if field.kind~='bool' and field.kind~='choice' then
            local value=tostring(row.edit.Content or '')
            if field.kind=='int' or field.kind=='float' then
                local n=tonumber(value);value=n and n/(field.scale or 1) or value
            end
            if field.button then self.button_edit[field.key]=value
            elseif field.python then self.python=value
            else (field.root and self.draft or self.draft.settings)[field.key]=value end
        end
    end
end
function UI:toggle(index)
    self:capture();local field=self.bindings[index];if not field then return end
    local target=field.button and self.button_edit or field.root and self.draft or self.draft.settings
    if field.kind=='bool' then target[field.key]=not target[field.key]
    else
        local choices=field.choices
        local at=1;for i,v in ipairs(choices) do if v==target[field.key] then at=i%#choices+1 end end
        target[field.key]=choices[at]
        if field.key=='control_mode' and target[field.key]=='pan_tilt' then self.draft.output_mode='direct' end
    end
    self:render()
end
function UI:fields()
    if self.page=='Buttons' then return {
        {key='id',label='Button index (starts at 0)',kind='str',button=true},
        {key='action',label='Action on press',kind='choice',button=true,
         choices={'command','start','stop','toggle','reset','release_marker'}},
        {key='press',label='MA command on press',kind='str',button=true},
        {key='release',label='MA command on release',kind='str',button=true}}
    end
    local result={};local s=self.draft.settings
    for _,field in ipairs(schema[self.page] or {}) do
        if (not field.mode or s.control_mode==field.mode) and
           (not field.output or self.draft.output_mode==field.output) then result[#result+1]=field end
    end
    if self.page=='Diagnostics' then result[#result+1]={key='python',label='Python 3.10+ executable (this Mac)',kind='str',python=true} end
    return result
end
function UI:action_list()
    local function action(name,payload) return function() self:act(name,payload) end end
    local list={}
    if self.page=='Live' or self.page=='Diagnostics' then
        list={{'Test figure eight',action('test')},{'Reset lock: '..tostring(self.draft.settings.reset_locked),action('reset_lock')},
              {'Cancel confirmation',action('cancel_confirm')}}
        if self.page=='Diagnostics' then
            list[#list+1]={'Reconnect helper',action('reconnect')}
            list[#list+1]={'Ack release warning',action('ack_warning')}
        end
    elseif self.page=='Joystick' then
        local devices=self.data.devices or {};local d=devices[self.device_choice]
        list={{'Refresh',action('refresh')},{d and d.name or 'Choose device',function()
            self.device_choice=self.device_choice%math.max(1,#devices)+1;self:render()
        end},{'Open chosen device',function()
            if d then self:act('select',{index=d.index,name=d.name}) else self.local_error='Refresh to find a joystick.' end
        end},{'Calibrate X / Y',function() self:act('calibrate',{axis_x=self.draft.settings.axis_x,axis_y=self.draft.settings.axis_y}) end},
        {'Cancel learn',action('cancel_learn')}}
    elseif self.page=='Levels' then
        list={{'Calibrate zoom centre',function() self:act('calibrate',{keys={'zoom'},axis_zoom=self.draft.settings.axis_zoom}) end}}
    elseif self.page=='Target' and self.draft.settings.control_mode=='marker' and self.draft.output_mode=='direct' then
        list={{'Read MA movement space',action('read_space')}}
    elseif self.page=='Buttons' then
        list={{'Learn button',action('learn',{key='button'})},{'Load mapping',function()
            local saved=self.draft.settings.buttons[tostring(self.button_edit.id)] or {}
            self.button_edit.action=saved.action or 'command';self.button_edit.press=saved.press or '';self.button_edit.release=saved.release or ''
            self.mapping_saved=json.encode(self.button_edit)
            self:render()
        end},{'Add / update',function()
            local e=self.button_edit;local id=tonumber(e.id)
            if not id or id<0 or id%1~=0 then self.local_error='Enter a non-negative whole button index.';return end
            local map=e.action=='command' and {press=e.press,release=e.release} or {action=e.action}
            self.draft.settings.buttons[tostring(id)]=map;self.mapping_saved=json.encode(e);self.local_error='Mapping added to draft; Save settings.'
        end},{'Remove mapping',function()
            self.draft.settings.buttons[tostring(self.button_edit.id)]=nil
            self.button_edit.press='';self.button_edit.release='';self.button_edit.action='command'
            self.mapping_saved=json.encode(self.button_edit);self.local_error='Mapping removed from draft; Save settings.';self:render()
        end},{'Discard editor',function()
            self.button_edit.press='';self.button_edit.release='';self.button_edit.action='command'
            self.mapping_saved=json.encode(self.button_edit);self:render()
        end}}
    end
    local count=#self:fields();if count>8 then
        list[#list+1]={'Next settings page',function() self:capture();self.subpage=self.subpage%math.ceil(count/8)+1;self:render() end}
    end
    return list
end
function UI:render()
    local editable=not self.data.running and not self.busy
    self.action_items=self:action_list()
    for i,button in ipairs(self.action_buttons) do
        local item=self.action_items[i];button.Visible=item~=nil;button.Text=item and item[1] or ''
        button.Name='Action'..i
        button.Enabled=editable or (self.page=='Live' and i==2) or item and item[1]=='Cancel confirmation'
        if item and item[1]=='Test figure eight' then button.Name='Test';button.Enabled=self.data.ready==true and editable end
    end
    self.info.Visible=self.page=='Live'
    self.bindings={};local fields=self:fields()
    for i,row in ipairs(self.rows) do
        local field=fields[(self.subpage-1)*8+i];self.bindings[i]=field
        row.label.Visible=field~=nil;row.edit.Visible=false;row.toggle.Visible=false;row.extra.Visible=false
        if field then
            local target=field.button and self.button_edit or field.root and self.draft or self.draft.settings
            local value=field.python and self.python or target[field.key]
            row.label.Text=field.label
            local enabled=editable and (not field.zoom or self.draft.settings.zoom_enabled)
            if field.button and (field.key=='press' or field.key=='release') and self.button_edit.action~='command' then enabled=false end
            if field.kind=='bool' or field.kind=='choice' then
                row.toggle.Visible=true;row.toggle.Name='field_'..field.key;row.toggle.Text=tostring(value);row.toggle.Enabled=enabled
            else
                row.edit.Visible=true;row.edit.Name='field_'..field.key;row.edit.Enabled=enabled
                row.edit.Content=tostring(type(value)=='number' and value*(field.scale or 1) or value or '')
            end
            if field.learn or field.button and field.key=='id' then
                row.extra.Visible=true;row.extra.Enabled=enabled and self.data.device_open==true
                if field.button then
                    self.signal['FS_Learn'..i]=function() self:act('learn',{key='button'}) end
                else self.signal['FS_Learn'..i]=function() self:act('learn',{key=field.key}) end end
            end
        end
    end
    for _,name in ipairs({'Start','Save','Reset'}) do
        self.controls[name].Enabled=self.data.ready==true and not self.busy and (not self.data.running or name=='Reset')
    end
    self.controls.Start.Enabled=self.controls.Start.Enabled and self.data.device_open==true and not self.data.learning
    self.controls.Stop.Enabled=self.data.running==true or self.busy==true
    self.controls.Release.Enabled=self.data.holding==true
    self.controls.Release.Text=self.confirm=='release' and 'CONFIRM release' or 'Release PSN'
    self.controls.Close.Text=self.confirm=='close' and 'CONFIRM close / release' or 'Close'
    local mappings={}
    for key,map in pairs(self.draft.settings.buttons) do mappings[#mappings+1]=key..':'..(map.action or 'command') end
    table.sort(mappings)
    self.page_note.Text=self.page=='Buttons' and ('Saved in draft: '..table.concat(mappings,'  ')) or
        (self.page=='Live' and 'Settings persist in this show/user profile. Save the MA show to keep them after reload.' or
        ('Page '..self.subpage..' / '..math.max(1,math.ceil(#fields/8))..'  •  Save settings applies the complete draft.'))
    self:update_text()
end
function UI:update_text()
    local d,s=self.data,self.draft.settings;local p=d.preview or {}
    local xyz=p.xyz or {s.initial_x,s.initial_y,s.z};local pt=p.pan_tilt or {s.initial_pan,s.initial_tilt}
    local mode=d.running and (d.test and 'TEST RUNNING' or 'RUNNING') or d.holding and 'PSN HOLDING' or 'STOPPED'
    local levels=d.frame or {}
    local applied=d.config and d.config.settings or s
    local position=applied.control_mode=='marker' and ('X '..number(xyz[1])..' m     Y '..number(xyz[2])..' m     Z '..number(xyz[3])..' m') or
        ('Pan '..number(pt[1])..'%     Tilt '..number(pt[2])..'%')
    local function bounded(v,low,high)
        v,low,high=tonumber(v),tonumber(low),tonumber(high)
        return v and low and high and math.max(low,math.min(high,v)) or nil
    end
    local next_position=s.control_mode=='marker' and ('X '..number(bounded(xyz[1],s.x_min,s.x_max))
        ..'  Y '..number(bounded(xyz[2],s.y_min,s.y_max))..'  Z '..number(tonumber(s.z))..' m') or
        ('Pan '..number(bounded(pt[1],s.pan_min,s.pan_max))..'  Tilt '..number(bounded(pt[2],s.tilt_min,s.tilt_max))..'%')
    local axis=tonumber(s.axis_slider);local slider=axis and (d.axes or {})[axis+1]
    local next_level=slider and math.max(0,math.min(100,(slider+1)*50)) or nil
    if next_level and s.invert_slider then next_level=100-next_level end
    self.info.Text=mode..'\n\n'..position..'\n\nRequested brightness '..number(levels.brightness or p.brightness)..'%'
        ..'     Zoom / iris '..(s.zoom_enabled and number(levels.zoom or p.zoom)..'%' or 'off')
        ..'\n\nNext Start: '..(s.control_mode=='marker' and 'MArker '..tostring(s.marker_id)..' • '..self.draft.output_mode
        or 'Group '..tostring(s.fixture_group)..' • pan / tilt (changes selection)')
        ..'\nBrightness: Page '..tostring(s.executor_page)..' / Executor '..tostring(s.executor_number)..' • Master'
        ..'\n'..next_position..'     Current slider '..number(next_level)..'%'
        ..'\nStart uses the current slider. Test uses '..tostring(s.test_brightness)..'% for '..tostring(s.test_period)..' seconds.'
        ..'\n\n'..(d.device_open and 'Joystick open: '..tostring(d.config and d.config.settings.device_name or '') or 'No joystick open — Test needs none.')
        ..'\n\n'..(d.holding and 'PSN is streaming. Stop holds; Release ends the stream and may move the MArker to origin.'
        ..'\nHeld XYZ: '..number((d.held_xyz or {})[1])..' / '..number((d.held_xyz or {})[2])..' / '..number((d.held_xyz or {})[3])..' m'
        or self.draft.output_mode=='psn' and 'PSN requires MA tracker mapping and the matching local interface. No OSC setup is needed.'
        or 'Direct output uses the programmer. Blind, Clear and playback priorities still apply.')
    local raw={};for i,v in ipairs(d.axes or {}) do raw[#raw+1]=string.format('%d:%+.3f',i-1,v) end
    local down={};for i,v in ipairs(d.buttons or {}) do if v then down[#down+1]=tostring(i-1) end end
    local problem=self.local_error or d.fault or ''
    if problem=='' then problem=d.warning or '' end
    self.status.Text=mode..'  •  '..tostring(d.message or 'Starting helper…')
        ..'\n'..(problem~='' and problem or ('Axes '..table.concat(raw,'  ')..'    Buttons '..table.concat(down,',')))
    self.status.TextColor=problem~='' and 'Global.ErrorText' or 'Global.SuccessText'
end
function UI:refresh(data,busy)
    -- Do not normalize a half-typed number or rewrite the focused editor.
    local redraw=self.data.ready~=data.ready or self.data.running~=data.running
        or self.data.holding~=data.holding or self.data.device_open~=data.device_open or self.busy~=busy
    if redraw then self:capture() end
    self.data=data;self.busy=busy
    if data.learned and data.learned.id~=self.learned_id then
        self:capture();redraw=true
        self.learned_id=data.learned.id
        for key,value in pairs(data.learned.values) do
            if key=='button' then self.button_edit.id=tostring(value) else self.draft.settings[key]=value end
        end
    end
    if redraw then self:render() else self:update_text() end
end
return UI
