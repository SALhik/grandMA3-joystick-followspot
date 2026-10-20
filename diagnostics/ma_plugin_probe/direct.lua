-- Finite native MA API experiment. Motion frames are built with the app core.
local config = __CONFIG__
local active = nil
local title = 'Followspot Direct Test - REAL OUTPUT'
local probe_version = '0.3.1.0'

local function quote(value)
    return "'" .. value:gsub("'", "'\\''") .. "'"
end

local function write(path, text)
    local file = assert(io.open(path, 'wb'))
    assert(file:write(text)); assert(file:close())
end

local function message(text)
    Printf('FS Direct: %s', text)
    MessageBox({title=title, message=text, commands={{value=0, name='Close'}}})
end

local function address(object)
    if object == nil then return '(none)' end
    local ok, value = pcall(function() return object:ToAddr() end)
    return ok and tostring(value) or tostring(object)
end

local function describe(value, depth)
    depth = depth or 0
    if type(value) ~= 'table' then return tostring(value) end
    if depth > 3 then return '{...}' end
    local keys, parts = {}, {}
    for key in pairs(value) do keys[#keys + 1] = key end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    for _, key in ipairs(keys) do
        parts[#parts + 1] = tostring(key) .. '=' .. describe(value[key], depth + 1)
    end
    return '{' .. table.concat(parts, ', ') .. '}'
end

local function selection()
    local parts, seen = {}, {}
    local index, x, y, z = SelectionFirst()
    while index do
        assert(not seen[index], 'Selection traversal repeated a fixture')
        seen[index] = true
        parts[#parts + 1] = table.concat({index, x or '-', y or '-', z or '-'}, ':')
        index, x, y, z = SelectionNext(index)
    end
    return table.concat(parts, ';')
end

local function encoders()
    return address(GetSelectedAttribute()) .. ';' .. address(SelectedFeature())
end

local function check_context(state)
    state.selection_after = selection()
    state.encoders_after = encoders()
    if state.selection_after ~= state.selection_before then
        state.selection_preserved = false
        error('Fixture selection/grid changed; further output stopped')
    end
    if state.encoders_after ~= state.encoders_before then
        state.encoders_preserved = false
        error('Encoder feature/attribute changed; further output stopped')
    end
end

local function finish(state, reason, detail)
    if state.done then return end
    state.done, state.reason = true, reason
    if active == state then active = nil end
    if state.log then state.log:close(); state.log = nil end
    -- A host write can raise after changing state; do not report an older
    -- successful observation as the final selection or encoder result.
    for _, item in ipairs({{'selection', selection}, {'encoders', encoders}}) do
        local key, observe = item[1], item[2]
        if state[key .. '_before'] ~= nil then
            local ok, value = pcall(observe)
            if ok then
                state[key .. '_after'] = value
                if value ~= state[key .. '_before'] then state[key .. '_preserved'] = false end
            elseif state[key .. '_preserved'] ~= false then
                state[key .. '_preserved'] = 'unverified'
                state.lines[#state.lines + 1] = key .. '_observation_error=' .. tostring(value)
            end
        end
    end
    state.lines[#state.lines + 1] = 'reason=' .. reason
    state.lines[#state.lines + 1] = 'detail=' .. tostring(detail or '')
    state.lines[#state.lines + 1] = 'frames_written=' .. state.frames
    state.lines[#state.lines + 1] = 'channel_writes=' .. state.writes
    for _, key in ipairs({'selection_preserved', 'encoders_preserved', 'readback_matches',
                         'selection_before', 'selection_after', 'encoders_before', 'encoders_after'}) do
        state.lines[#state.lines + 1] = key .. '=' .. tostring(state[key])
    end
    for index, phaser in ipairs(state.last_phasers or {}) do
        state.lines[#state.lines + 1] = config.attributes[index] .. ' last_readback=' .. phaser
    end
    if state.brightness_attempted then
        state.lines[#state.lines + 1] = 'brightness_requested=' .. config.brightness
        state.lines[#state.lines + 1] = 'brightness_readback=' .. tostring(state.brightness_readback)
        state.lines[#state.lines + 1] = 'brightness_wait_elapsed=' .. tostring(state.brightness_wait_elapsed)
    end
    if state.started then state.lines[#state.lines + 1] = 'elapsed=' .. (Time() - state.started) end
    state.lines[#state.lines + 1] = 'visible_movement=operator_check_required'
    state.lines[#state.lines + 1] = 'Last XYZ / optional brightness retained. No restore or blackout.'
    write(state.root .. '/report.txt', table.concat(state.lines, '\n') .. '\n')
    Printf('FS Direct: reason=%s; frames=%d; reports: %s', reason, state.frames, state.root)
end

local function Cleanup()
    if active then
        local state = active
        local ok, why = pcall(finish, state, 'requested_stop', 'MA cleanup requested Stop')
        if not ok then Printf('FS Direct: cleanup report error: %s', tostring(why)) end
    end
end

local function one(query)
    local objects = ObjectList(query)
    assert(objects and #objects == 1, 'Expected exactly one target for ' .. query)
    return objects[1]
end

local function prepare(state, brightness)
    for _, name in ipairs({'ObjectList', 'GetAttributeIndex', 'GetUIChannelIndex',
                          'GetProgPhaser', 'SetProgPhaser', 'SelectionFirst', 'SelectionNext',
                          'GetSelectedAttribute', 'SelectedFeature', 'IsObjectValid', 'Time'}) do
        assert(type(_G[name]) == 'function', 'MA API unavailable: ' .. name)
    end
    state.selection_before, state.encoders_before = selection(), encoders()
    state.selection_preserved, state.encoders_preserved = true, true
    state.readback_matches = 'not_written'
    state.marker = one('MArker ' .. config.marker_id)
    state.subfixture = state.marker.SubfixtureIndex
    assert(type(state.subfixture) == 'number', 'MArker has no SubfixtureIndex')
    local ok, space = pcall(function() return state.marker.MovementSpace end)
    state.lines[#state.lines + 1] = 'marker=' .. address(state.marker)
    state.lines[#state.lines + 1] = 'movement_space=' .. (ok and address(space) or tostring(space))
    state.channels = {}
    for index, attribute in ipairs(config.attributes) do
        local attr = GetAttributeIndex(attribute)
        assert(type(attr) == 'number' and attr >= 0, 'Attribute unavailable: ' .. attribute)
        local channel = GetUIChannelIndex(state.subfixture, attr)
        assert(type(channel) == 'number' and channel >= 0, 'Channel unavailable: ' .. attribute)
        for _, other in ipairs(state.channels) do
            assert(other.channel ~= channel, 'XYZ attributes resolved to the same channel')
        end
        state.channels[index] = {channel=channel, attribute=attribute, attr=attr}
        state.lines[#state.lines + 1] = attribute .. ' channel=' .. channel
            .. ' before=' .. describe(GetProgPhaser(channel, false))
    end
    -- The optional fader is resolved after every XYZ channel, before any output.
    if brightness then
        state.executor = one(string.format('Page %d.%d', config.page, config.executor))
        state.assigned = state.executor:GetAssignedObj()
        assert(state.assigned and IsObjectValid(state.assigned), 'Brightness executor has no assigned object')
        assert(type(state.assigned.SetFader) == 'function' and type(state.assigned.GetFader) == 'function',
               'Assigned brightness object has no fader API')
        state.lines[#state.lines + 1] = 'brightness_object=' .. address(state.assigned)
        state.lines[#state.lines + 1] = 'brightness_before='
            .. tostring(state.assigned:GetFader({token='FaderMaster'}))
    end
    check_context(state)
end

local function check_target(state)
    assert(IsObjectValid(state.marker) and state.marker.SubfixtureIndex == state.subfixture,
           'MArker target changed or became invalid')
    assert(one('MArker ' .. config.marker_id) == state.marker, 'MArker target was replaced')
    for _, item in ipairs(state.channels) do
        assert(GetUIChannelIndex(state.subfixture, item.attr) == item.channel,
               'MArker target channel changed: ' .. item.attribute)
    end
end

local function check_readback(state, frame)
    state.last_phasers = state.last_phasers or {}
    for index, item in ipairs(state.channels) do
        local phaser = GetProgPhaser(item.channel, false)
        state.last_phasers[index] = describe(phaser)
        local got = phaser and phaser[1] and phaser[1].absolute
        if type(got) ~= 'number' or got ~= got or math.abs(got - frame[index + 4]) > 0.001 then
            state.readback_matches = false
            error(item.attribute .. ' programmer readback mismatch: expected '
                .. frame[index + 4] .. ', got ' .. tostring(got) .. '; phaser=' .. describe(phaser))
        end
    end
    state.readback_matches = true
end

local function apply_brightness(state)
    state.brightness_attempted, state.brightness_readback = true, 'pending'
    local started = Time()
    state.assigned:SetFader({value=config.brightness, token='FaderMaster'})
    -- MA applies fader changes asynchronously. Observe them after yielding;
    -- never re-send the level or allow this bounded wait to start XYZ early.
    for attempt = 1, 31 do
        if state.done then return false end
        local now = Time()
        assert(type(now) == 'number' and now == now and now >= started, 'Invalid MA clock')
        state.brightness_wait_elapsed = now - started
        if state.brightness_wait_elapsed > 1 then break end
        check_context(state)
        check_target(state)
        assert(IsObjectValid(state.assigned) and state.executor:GetAssignedObj() == state.assigned,
               'Brightness target changed while waiting for readback')
        local got = state.assigned:GetFader({token='FaderMaster'})
        state.brightness_readback = got
        if type(got) == 'number' and got == got and math.abs(got - config.brightness) <= 0.1 then
            return true
        end
        if attempt < 31 then coroutine.yield(1 / 30) end
    end
    error('Brightness Master readback did not settle within 1 s: requested '
        .. config.brightness .. '%, last observed ' .. tostring(state.brightness_readback) .. '%')
end

local function run(state, brightness)
    prepare(state, brightness)
    state.started = Time()
    state.log = assert(io.open(state.root .. '/writes.tsv', 'wb'))
    state.log:write('elapsed\tx_m\ty_m\tz_m\tx_percent\ty_percent\tz_percent\n')
    if brightness and not apply_brightness(state) then return end
    -- Brightness settling must not skip the initial target or shorten the lap.
    local motion_started = Time()
    local previous, last_index = motion_started, 0
    for _ = 1, math.ceil(config.period * 60) + 60 do
        if state.done then return end
        local now = Time()
        assert(type(now) == 'number' and now == now and now >= previous, 'Invalid MA clock')
        if now - previous > 0.25 then
            finish(state, 'timing_gap', 'MA scheduler gap exceeded 0.25 s; no position jump sent')
            return
        end
        previous = now
        local elapsed = now - motion_started
        local index = math.min(math.floor(elapsed * 30 + 1e-7) + 1, #config.frames)
        check_context(state)
        check_target(state)
        if index ~= last_index then
            local frame = config.frames[index]
            state.readback_matches = 'pending'
            for axis, item in ipairs(state.channels) do
                SetProgPhaser(item.channel, {[1]={absolute=frame[axis + 4]}})
                state.writes = state.writes + 1
            end
            state.frames = state.frames + 1
            state.log:write(string.format('%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\n',
                elapsed, table.unpack(frame, 2, 7))); state.log:flush()
            check_context(state)
            last_index = index
        end
        -- Yield once before reading programmer state, allowing MA to apply it.
        coroutine.yield(1 / 30)
        if state.done then return end
        local resumed = Time()
        assert(type(resumed) == 'number' and resumed == resumed and resumed >= previous, 'Invalid MA clock')
        if resumed - previous > 0.25 then
            finish(state, 'timing_gap', 'MA scheduler gap exceeded 0.25 s before readback')
            return
        end
        previous = resumed
        check_context(state)
        check_target(state)
        check_readback(state, config.frames[last_index])
        if index == #config.frames then
            finish(state, 'completed', 'Direct API writes and readback completed; observe 3D separately')
            return
        end
    end
    finish(state, 'timing_gap', 'MA clock did not complete the finite cycle')
end

local function Main()
    if active then message('A direct test is already running.'); return end
    if HostType() ~= 'onPC' or not tostring(HostOS()):lower():find('mac', 1, true) then
        message('This research probe is for grandMA3 onPC on macOS.'); return
    end
    local choice = MessageBox({title=title, message=config.preview, commands={
        {value=1, name='Run XYZ only'}, {value=2, name='Run XYZ + brightness'},
        {value=3, name='Inspect only'}, {value=0, name='Cancel'}}})
    if not choice.success or not ({[1]=true, [2]=true, [3]=true})[choice.result] then return end
    local state = {lines={config.preview, 'probe_version=' .. probe_version, 'Lua=' .. tostring(_VERSION),
        'onPC_version=' .. (type(Version) == 'function' and tostring(Version()) or 'unknown')},
        writes=0, frames=0}
    local ok, why = xpcall(function()
        local base = os.getenv('FOLLOWSPOT_DIRECT_REPORTS') or
            (assert(os.getenv('HOME')) .. '/MALightingTechnology/gma3_library/followspot_direct_tests')
        assert(os.execute('/bin/mkdir -p ' .. quote(base)), 'Cannot create report folder')
        local handle = assert(io.popen('/usr/bin/mktemp -d ' .. quote(base .. '/run.XXXXXXXX')))
        state.root = assert(handle:read('*l')); assert(handle:close())
        active = state
        write(state.root .. '/report.txt', 'RUNNING\n' .. config.preview)
        if choice.result == 3 then
            prepare(state, false)
            finish(state, 'inspected', 'Read-only target inspection; no output')
        else
            run(state, choice.result == 2)
        end
    end, debug.traceback)
    if not ok then
        if state.root then
            local saved, error = pcall(finish, state, 'error', why)
            if not saved then why = tostring(why) .. '\nReport error: ' .. tostring(error) end
        end
        message('Direct test error:\n' .. tostring(why) .. '\nReports: ' .. tostring(state.root))
    elseif state.done then
        message('reason=' .. tostring(state.reason) .. '; frames=' .. state.frames
            .. '\nSelection preserved: ' .. tostring(state.selection_preserved)
            .. '; encoder context preserved: ' .. tostring(state.encoders_preserved)
            .. '\nProgrammer readback matches: ' .. tostring(state.readback_matches)
            .. '\nReadback is not proof of visible movement. Watch 3D separately.'
            .. '\nLast output retained; Inspect only sends no output.\nReports: ' .. state.root)
    end
end

return Main, Cleanup
