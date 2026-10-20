-- Native MA output. Position lookup never changes the console selection.
local Output = {}; Output.__index=Output
local function one(query)
    local objects=ObjectList(query)
    assert(objects and #objects==1,'Expected one target: '..query)
    return objects[1]
end
local function fader(page,number,token)
    local executor=one(string.format('Page %d.%d',page,number))
    local object=executor:GetAssignedObj()
    assert(object and IsObjectValid(object),'Executor has no assigned object')
    assert(type(object.SetFader)=='function','Assigned object cannot control a fader')
    return {executor=executor,object=object,token=token}
end
function Output.new(config,held,last_event)
    local s=config.settings
    local self=setmetatable({config=config,held=held or {},last_event=last_event or 0,channels={}},Output)
    if s.control_mode=='marker' then
        self.marker=one('MArker '..s.marker_id)
        self.subfixture=self.marker.SubfixtureIndex
        if config.output_mode=='direct' then
            assert(type(SetProgPhaser)=='function','MA SetProgPhaser API unavailable')
            for _,name in ipairs({s.attribute_x,s.attribute_y,s.attribute_z}) do
                local attr=GetAttributeIndex(name); assert(type(attr)=='number' and attr>=0,'Missing attribute '..name)
                local channel=GetUIChannelIndex(self.subfixture,attr)
                assert(type(channel)=='number' and channel>=0,'Missing channel '..name)
                for _,other in ipairs(self.channels) do assert(other.channel~=channel,'XYZ attributes resolve to the same channel') end
                self.channels[#self.channels+1]={attr=attr,channel=channel}
            end
        end
    else
        self.group=one('Group '..s.fixture_group)
    end
    self.brightness=fader(s.executor_page,s.executor_number,'FaderMaster')
    if s.zoom_enabled then self.zoom=fader(s.zoom_executor_page,s.zoom_executor_number,'FaderTemp') end
    return self
end
function Output:valid()
    if self.marker then
        assert(IsObjectValid(self.marker) and self.marker.SubfixtureIndex==self.subfixture
            and one('MArker '..self.config.settings.marker_id)==self.marker,'MArker patch/target changed; restart output')
        for _,item in ipairs(self.channels) do
            assert(GetUIChannelIndex(self.subfixture,item.attr)==item.channel,'MArker channel changed; restart output')
        end
    elseif self.group then
        assert(IsObjectValid(self.group) and one('Group '..self.config.settings.fixture_group)==self.group,
               'Pan/tilt group changed; restart output')
    end
    for _,role in ipairs({'brightness','zoom'}) do
        local f=self[role]
        if f then assert(IsObjectValid(f.object) and f.executor:GetAssignedObj()==f.object,
                         role..' executor assignment changed; restart output') end
    end
end
function Output:apply(frame)
    self:valid()
    if frame.force_position and frame.force_position~=self.last_force then
        for _,item in ipairs(self.channels) do item.value=nil end
        self.last_command=nil
        self.last_force=frame.force_position
    end
    local target=frame.target
    if target then
        if target.kind=='marker' then
            assert(self.config.output_mode=='direct' and #self.channels==3,'Output mode changed')
            for i,item in ipairs(self.channels) do
                local value=target.percent[i]
                assert(type(value)=='number' and value==value and value>=0 and value<=100,'Invalid XYZ percentage')
                if item.value~=value then SetProgPhaser(item.channel,{[1]={absolute=value}});item.value=value end
            end
        elseif target.kind=='pan_tilt' then
            assert(self.group,'Output mode changed')
            if self.last_command~=target.command then
                assert(Cmd(target.command)=='OK','Pan/tilt command rejected'); self.last_command=target.command
            end
        else assert(target.kind=='psn' and self.config.output_mode=='psn','Unknown position output') end
    end
    for _,role in ipairs({'brightness','zoom'}) do
        local value,f=frame[role],self[role]
        if value~=nil and f then
            assert(type(value)=='number' and value==value and value>=0 and value<=100,'Invalid fader level')
            if f.value~=value then
                f.object:SetFader({value=value,token=f.token}); f.value=value
                -- Readback can lag one or more frames; never assert it immediately.
            end
        end
    end
end
function Output:feedback()
    local result={}
    for _,role in ipairs({'brightness','zoom'}) do
        local f=self[role]
        if f and IsObjectValid(f.object) then
            local ok,value=pcall(function() return f.object:GetFader({token=f.token}) end)
            if ok and type(value)=='number' then result[role]=value end
        end
    end
    return result
end
function Output:command(event)
    if event.id<=self.last_event then return end
    if event.release and event.paired and not self.held[event.owner] then
        -- Stop cancelled this press before MA executed it; do not release an
        -- unrelated action even when another button has the same command text.
        self.last_event=event.id;return
    end
    assert(Cmd(event.command)=='OK','MA command rejected: '..event.command)
    if event.release then self.held[event.owner]=nil
    elseif event.release_command and event.release_command~='' then self.held[event.owner]=event.release_command end
    self.last_event=event.id
end
function Output:cleanup()
    local errors={}
    for owner,command in pairs(self.held) do
        local ok,why=pcall(function() assert(Cmd(command)=='OK','Release rejected') end)
        if ok then self.held[owner]=nil else errors[#errors+1]=tostring(why)..': '..command end
    end
    return errors
end
return Output
