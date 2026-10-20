-- Single imported component; all modules and Python files are embedded at build time.
local signalTable,component=select(3,...),select(4,...)
signalTable=signalTable or {}
local json=(function() __JSON__ end)()
local Output=(function() __OUTPUT__ end)()
local schema=json.decode(__SCHEMA__)
local UI=(function(...) __UI__ end)(json,schema)
local defaults=json.decode(__DEFAULTS__)
local sources=__PAYLOADS__
local active=nil
local config_variable='JoystickFollowspot_Config_v1'

local function quote(value) return "'"..value:gsub("'","'\\''").."'" end
local function read(path)
    local f=io.open(path,'rb');if not f then return nil end
    local value=f:read(1048577);f:close();assert(#value<=1048576,'Plugin file too large');return value
end
local function write(path,value)
    local f=assert(io.open(path,'wb'));assert(f:write(value));assert(f:close())
end
local function atomic(path,value)
    write(path..'.lua.tmp',value);assert(os.rename(path..'.lua.tmp',path))
end
local function data(path)
    local value=read(path);if not value then return nil end
    return json.decode(value)
end
local function save_config(state,config,preserve_draft)
    assert(UserVars()==state.variables,'MA show/user profile changed; reopen the plugin')
    local encoded=json.encode(config)
    local result=SetVar(UserVars(),config_variable,encoded)
    assert(result~=false and result~=0,'MA could not save plugin settings')
    if preserve_draft then state.ui.draft.settings.reset_locked=config.settings.reset_locked
    else state.ui.draft=json.decode(encoded) end
    state.ui.local_error=nil
    state.ui:render()
end
local function urgent(state,action,detail)
    if not state.root then return end
    state.urgent_id=state.urgent_id+1
    atomic(state.root..'/urgent.json',json.encode({token=state.token,id=state.urgent_id,
        action=action,detail=detail,cancel_through=state.request_id}))
    state.queue={};state.pending=nil
    state.blocked_generation=state.generation or 0
    state.ignore_frames=true
end
local function queue(state,action,payload,after)
    assert(state.root and state.status.ready,'Helper is not ready. Open Diagnostics to reconnect.')
    assert(#state.queue<16,'Too many pending actions; wait for the helper.')
    state.queue[#state.queue+1]={action=action,payload=payload or {},after=after}
end
local function executable_default()
    for _,path in ipairs({'/Library/Frameworks/Python.framework/Versions/Current/bin/python3',
        '/opt/homebrew/bin/python3','/usr/local/bin/python3'}) do
        local f=io.open(path,'rb');if f then f:close();return path end
    end
    return ''
end
local function launch(state)
    local python=state.ui.python
    assert(python:sub(1,1)=='/' and not python:find('[%z\r\n]'),'Enter an absolute Python 3.10+ executable in Diagnostics.')
    write(state.base..'/python.txt',python)
    local f=assert(io.popen('/usr/bin/mktemp -d '..quote(state.base..'/run.XXXXXXXX')))
    state.root=assert(f:read('*l'));assert(f:close());state.token=assert(state.root:match('([^/]+)$'))
    state.request_id,state.urgent_id,state.frame_seen,state.last_event=0,0,0,0
    state.queue={};state.pending=nil;state.status={ready=false,message='Launching Python helper…'}
    state.launched,state.last_heartbeat=Time(),Time();state.heartbeat=nil
    state.generation,state.blocked_generation=0,-1;state.native=nil
    state.ignore_frames=false
    for name,source in pairs(sources) do write(state.root..'/'..name,source) end
    write(state.root..'/config.json',json.encode(state.ui.draft))
    write(state.root..'/lease',state.token..':0')
    local command=quote(python)..' '..quote(state.root..'/worker.py')..' '..quote(state.root)..' '
        ..quote(state.token)..' --base '..quote(state.base)
        ..' < /dev/null > '..quote(state.root..'/reader.log')..' 2>&1 &'
    assert(os.execute(command),'Could not launch the Python helper')
    Printf('Joystick Followspot 1.0 — helper reports: %s',state.root)
end
local function cleanup_releases(state)
    if UserVars()~=state.variables then
        Printf('Followspot: show/user profile changed; check held actions in the previous show.')
        return
    end
    local errors={}
    for owner,command in pairs(state.held) do
        local ok,why=pcall(function() assert(Cmd(command)=='OK','Release command rejected') end)
        if ok then state.held[owner]=nil else errors[#errors+1]=tostring(why) end
    end
    if #errors>0 then Printf('Followspot release warning: %s',table.concat(errors,'; ')) end
end
local function Cleanup()
    local state=active;if not state then return end
    state.closed=true
    pcall(urgent,state,'shutdown')
    cleanup_releases(state)
    if state.ui and state.ui.root and IsObjectValid(state.ui.root) then pcall(function() state.ui.root:close() end) end
    active=nil
end
local function action(state,name,payload)
    state.ui.local_error=nil
    if name=='stop' then urgent(state,'stop');return end
    if name=='release' or name=='close' then
        if state.status.holding and state.ui.confirm~=name then
            state.ui.confirm=name;state.ui.local_error='Press again to end PSN streaming. The MArker may return to origin.'
            state.ui:render();return
        end
        state.ui.confirm=nil
        if name=='close' then
            if not state.root or state.status.exit_reason then state.closed=true else state.closing=true;urgent(state,'shutdown') end
        else urgent(state,'release') end
        return
    end
    if name=='cancel_confirm' then state.ui.confirm=nil;state.ui:render();return end
    if name=='reconnect' then
        assert(not state.status.running and not state.status.holding,'Stop output and Release PSN before reconnecting.')
        if state.root and not state.status.exit_reason then
            state.relaunch=true;urgent(state,'shutdown')
        else launch(state) end
        return
    end
    if name=='read_space' then
        assert(not state.status.running,'Stop output before changing setup.')
        local s=state.ui.draft.settings
        local list=ObjectList('MArker '..s.marker_id);assert(list and #list==1,'MArker not found')
        local space=list[1].MovementSpace;assert(space,'MArker has no Movement Space')
        local values={}
        for _,axis in ipairs({'X','Y','Z'}) do
            local low,high=tonumber(space['Min'..axis]),tonumber(space['Max'..axis])
            assert(low and high and low<high,'Cannot read Movement Space '..axis..'; use the saved bounds.')
            values['space_'..axis:lower()..'_min']=low;values['space_'..axis:lower()..'_max']=high
        end
        for key,value in pairs(values) do s[key]=value end
        state.ui.local_error='Movement Space read into draft; Save settings.';state.ui:render();return
    end
    if name=='ack_warning' then state.warning=nil end
    if name=='start' or name=='test' or name=='save' then
        assert(not state.status.running,'Stop output before applying settings.')
        do
            local e=state.ui.button_edit
            local nonempty=e.press~='' or e.release~='' or e.action~='command'
            assert(not nonempty or state.ui.mapping_saved==json.encode(e), 'Add/update or reload the button editor before saving.')
        end
        queue(state,'configure',{config=state.ui.draft},name~='save' and name or 'saved')
    elseif name=='reset_lock' then
        queue(state,'reset_lock',{locked=not state.ui.draft.settings.reset_locked},'saved')
    else queue(state,name,payload) end
end
local function pump(state)
    if UserVars()~=state.variables then
        urgent(state,'shutdown');state.closed=true;return
    end
    state.tick=state.tick+1
    if state.root then atomic(state.root..'/lease',state.token..':'..state.tick) end
    local status=state.root and data(state.root..'/status.json')
    if status then
        assert(status.protocol=='FOLLOWSPOT_PLUGIN_1' and status.token==state.token,'Unexpected helper owner or protocol')
        if status.heartbeat~=state.heartbeat then state.heartbeat=status.heartbeat;state.last_heartbeat=Time() end
        state.status=status
        if state.ignore_frames and (status.urgent_id or 0)>=state.urgent_id then
            state.blocked_generation=math.max(state.blocked_generation,status.frame and status.frame.generation or 0)
            state.ignore_frames=false
        end
        if state.pending and (status.request_id or 0)>=state.pending.id then
            local pending=state.pending;state.pending=nil
            if status.request_error and status.request_error~='' then state.ui.local_error=status.request_error
            else
                if pending.action=='configure' or pending.action=='reset_lock' then
                    save_config(state,status.config,pending.action=='reset_lock')
                end
                if pending.after=='start' or pending.after=='test' then
                    state.native=Output.new(status.config,state.held,state.last_event)
                    queue(state,pending.after)
                end
                if pending.action=='select' then state.ui.draft.settings.device_name=status.config.settings.device_name end
            end
        end
        -- Commands are durable and processed even after Stop to release owned actions.
        for _,event in ipairs(status.events or {}) do
            if event.id>state.last_event and not state.ignore_frames then
                if not state.native then state.native=Output.new(status.config,state.held,state.last_event) end
                local ok,why=true,nil
                if event.release or (event.generation or 0)>state.blocked_generation then
                    ok,why=pcall(function() state.native:command(event) end)
                end
                state.last_event=event.id
                if not ok then
                    if event.release then state.warning='MA release failed; release manually: '..event.command end
                    state.ui.local_error=tostring(why);urgent(state,'fault',tostring(why))
                end
            end
        end
        local frame=status.frame
        if not state.ignore_frames and frame and frame.seq>state.frame_seen and frame.generation>state.blocked_generation then
            state.generation=frame.generation
            local ok,why=pcall(function()
                if not state.native or state.native_generation~=frame.generation then
                    state.native=Output.new(status.config,state.held,state.last_event)
                    state.native_generation=frame.generation
                end
                state.native:apply(frame)
            end)
            state.frame_seen=frame.seq
            if not ok then state.ui.local_error=tostring(why);urgent(state,'fault',tostring(why)) end
        end
        atomic(state.root..'/ack.json',json.encode({token=state.token,event_id=state.last_event,frame_id=state.frame_seen}))
        if status.exit_reason then
            cleanup_releases(state)
            if state.relaunch then state.relaunch=nil;launch(state)
            elseif state.closing then state.closed=true
            else state.ui.local_error=status.fault or status.request_error or ('Helper stopped: '..status.exit_reason) end
        end
    end
    if state.root and not state.status.exit_reason and Time()-state.last_heartbeat>5 then
        urgent(state,'shutdown')
        state.status.ready=false
        state.ui.local_error='Helper is unresponsive. Check Diagnostics / Python path. '..(read(state.root..'/reader.log') or '')
    end
    if not state.pending and #state.queue>0 and state.status.ready then
        local item=table.remove(state.queue,1)
        state.request_id=state.request_id+1;item.id=state.request_id;state.pending=item
        atomic(state.root..'/request.json',json.encode({token=state.token,id=item.id,action=item.action,payload=item.payload}))
    end
    if state.warning then state.status.warning=state.warning end
    state.ui:refresh(state.status,state.pending~=nil or #state.queue>0)
end
local function Main()
    if active then active.ui.root.Visible=true;return end
    assert(HostType()=='onPC' and tostring(HostOS()):lower():find('mac',1,true),'Joystick Followspot requires macOS onPC.')
    local base=os.getenv('FOLLOWSPOT_PLUGIN_HOME') or assert(os.getenv('HOME'))..'/MALightingTechnology/gma3_library/joystick_followspot'
    assert(os.execute('/bin/mkdir -p '..quote(base)),'Cannot create plugin data folder')
    local saved=GetVar(UserVars(),config_variable)
    local config=defaults
    if type(saved)=='string' and saved~='' then config=json.decode(saved) end
    local state={base=base,queue={},held={},request_id=0,urgent_id=0,tick=0,last_event=0,
        frame_seen=0,status={ready=false},blocked_generation=-1,variables=UserVars()}
    active=state
    local function dispatch(name,payload)
        local ok,why=pcall(action,state,name,payload)
        if not ok then state.ui.local_error=tostring(why) end
    end
    state.ui=UI.new(signalTable,component,config,read(base..'/python.txt') or executable_default(),dispatch,state)
    local ok,why=pcall(launch,state)
    if not ok then state.ui.local_error=tostring(why) end
    while not state.closed and IsObjectValid(state.ui.root) do
        local success,error=xpcall(function() pump(state) end,debug.traceback)
        if not success then
            state.ui.local_error=tostring(error);pcall(urgent,state,'fault',tostring(error))
            Printf('Followspot: %s',tostring(error));state.ui:update_text()
        end
        coroutine.yield(1/30)
    end
    Cleanup()
end
local function Entry()
    local ok,why=xpcall(Main,debug.traceback)
    if not ok then pcall(Cleanup);active=nil;error(why) end
end
return Entry,Cleanup
