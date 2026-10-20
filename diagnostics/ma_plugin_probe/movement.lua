-- Experimental finite OSC movement test; embedded helper and app core.
local movement_source = __MOVEMENT_SOURCE__
local core_source = __CORE_SOURCE__
local settings_json = __SETTINGS_JSON__
local preview = __PREVIEW__
local duration = __DURATION__
local active = nil
local title = 'Followspot Movement Test - REAL OUTPUT'

local function quote(value)
    return "'" .. value:gsub("'", "'\\''") .. "'"
end

local function read(path)
    local file = io.open(path, 'rb')
    if not file then return nil end
    local text = file:read('*a'); file:close(); return text
end

local function write(path, text)
    local file = assert(io.open(path, 'wb'))
    assert(file:write(text)); assert(file:close())
end

local function atomic(path, text)
    write(path .. '.lua.tmp', text)
    assert(os.rename(path .. '.lua.tmp', path))
end

local function fields(text)
    local result = {}
    for part in (text .. '\t'):gmatch('(.-)\t') do result[#result + 1] = part end
    return result
end

local function message(text)
    Printf('FS Movement: %s', text)
    MessageBox({title=title, message=text, commands={{value=0, name='Close'}}})
end

local function python_default()
    for _, path in ipairs({
        '/Library/Frameworks/Python.framework/Versions/Current/bin/python3',
        '/opt/homebrew/bin/python3', '/usr/local/bin/python3'
    }) do
        local file = io.open(path, 'rb')
        if file then file:close(); return path end
    end
    return ''
end

local function Cleanup()
    if active then
        pcall(write, active.root .. '/stop', active.token)
        pcall(write, active.root .. '/report.txt',
            'STOP REQUESTED by MA cleanup. Check helper-report.txt for actual exit.\n' .. preview)
        Printf('FS Movement: stop requested; reports: %s', active.root)
        active = nil
    end
end

local function run(python)
    assert(python:sub(1, 1) == '/' and not python:find('[%z\r\n]'),
           'Enter an absolute path to a Python 3.10+ executable.')
    local base = os.getenv('FOLLOWSPOT_MOVEMENT_REPORTS') or
        (assert(os.getenv('HOME')) .. '/MALightingTechnology/gma3_library/followspot_movement_tests')
    assert(os.execute('/bin/mkdir -p ' .. quote(base)), 'Cannot create report folder')
    local handle = assert(io.popen('/usr/bin/mktemp -d ' .. quote(base .. '/run.XXXXXXXX')))
    local root = assert(handle:read('*l')); assert(handle:close())
    local token = assert(root:match('([^/]+)$'))
    active = {root=root, token=token}
    write(root .. '/report.txt', 'RUNNING\n' .. preview)
    write(root .. '/movement.py', movement_source)
    write(root .. '/followspot_core.py', core_source)
    write(root .. '/settings.json', settings_json)
    write(root .. '/lease', token .. ':0')
    Printf('FS Movement: %s\nReports: %s', preview, root)
    local command = quote(python) .. ' ' .. quote(root .. '/movement.py') .. ' '
        .. quote(root) .. ' ' .. quote(token)
        .. ' < /dev/null > ' .. quote(root .. '/reader.log') .. ' 2>&1 &'
    assert(os.execute(command), 'Could not launch movement helper')
    local ready, reason, updates, last_sequence = false, nil, 0, 0
    for tick = 1, math.ceil((duration + 8) * 30) do
        atomic(root .. '/lease', token .. ':' .. tick)
        local hello = read(root .. '/ready')
        if hello and not ready then
            local parts = fields(hello)
            assert(parts[1] == 'FS_MOVEMENT_1' and parts[2] == token, 'Unexpected helper handshake')
            ready = true
            Printf('FS Movement: helper ready; Python %s; PID %s', parts[3], parts[4])
        end
        local sample = read(root .. '/sample')
        if sample then
            local parts = fields(sample)
            local sequence = tonumber(parts[2])
            assert(parts[1] == token and sequence, 'Malformed movement sample')
            if sequence > last_sequence then
                updates, last_sequence = updates + 1, sequence
                if updates == 1 or tick % 15 == 0 then
                    Printf('FS Movement: t=%.2fs X=%+.2f Y=%+.2f Z=%.2fm; sent=%s',
                        tonumber(parts[3]), tonumber(parts[4]), tonumber(parts[5]), tonumber(parts[6]), parts[7])
                end
            end
        end
        local finished = read(root .. '/exit')
        if finished then
            local parts = fields(finished)
            assert(parts[1] == token, 'Unexpected helper exit owner')
            reason = parts[2]; break
        end
        coroutine.yield(1 / 30)
    end
    if not reason then
        write(root .. '/stop', token)
        for _ = 1, 60 do
            local finished = read(root .. '/exit')
            if finished then
                local parts = fields(finished)
                assert(parts[1] == token, 'Unexpected helper exit owner')
                reason = parts[2]; break
            end
            coroutine.yield(1 / 30)
        end
    end
    local sent = ready and updates >= 3 and reason == 'completed'
    local summary = (sent and 'SENT: figure-eight cycle completed.' or 'STOPPED / FAILED: movement test.')
        .. '\nreason=' .. tostring(reason) .. '; observed updates=' .. updates
        .. '\nThis confirms sends only. Check MA reception and visible 3D movement.'
        .. '\nMA retains the last target and brightness.'
        .. '\nReports: ' .. root
    write(root .. '/report.txt', summary .. '\n\n' .. preview .. '\nLua=' .. tostring(_VERSION)
        .. '\nHostOS=' .. tostring(HostOS()) .. '\nHostType=' .. tostring(HostType())
        .. '\n\n' .. (read(root .. '/helper-report.txt') or read(root .. '/reader.log') or ''))
    active = nil
    message(summary)
end

local function Main()
    if active then message('A movement test is already running.'); return end
    if HostType() ~= 'onPC' or not tostring(HostOS()):lower():find('mac', 1, true) then
        message('This experimental test requires grandMA3 onPC on macOS.'); return
    end
    local choice = MessageBox({title=title, message=preview, autoCloseOnInput=false,
        inputs={{name='Python executable', value=python_default(), maxTextLength=512}},
        commands={{value=1, name='Run movement test'}, {value=0, name='Cancel'}}})
    if not choice.success or choice.result ~= 1 then return end
    local ok, why = xpcall(function() run(choice.inputs['Python executable']) end, debug.traceback)
    if not ok then
        local root = active and active.root
        Cleanup()
        local text = 'Movement test error:\n' .. tostring(why)
        if root then
            text = text .. '\nReports: ' .. root
            pcall(write, root .. '/report.txt', text .. '\n' .. (read(root .. '/reader.log') or ''))
        end
        message(text)
    end
end

return Main, Cleanup
