-- Experimental macOS onPC diagnostic. No Cmd, OSC, PSN, HID or fixture access.
-- The generated single XML includes the emulator source below.
local emulator_source = __EMULATOR_SOURCE__
local active = nil
local title = 'Followspot Diagnostic - SYNTHETIC ONLY'

local function quote(value)
    return "'" .. value:gsub("'", "'\\''") .. "'"
end

local function read(path)
    local file = io.open(path, 'rb')
    if not file then return nil end
    local text = file:read('*a')
    file:close()
    return text
end

local function write(path, text)
    local file = assert(io.open(path, 'wb'))
    assert(file:write(text))
    assert(file:close())
end

local function atomic(path, text)
    write(path .. '.lua.tmp', text)
    assert(os.rename(path .. '.lua.tmp', path))
end

local function message(text)
    Printf('FS Diagnostic: %s', text)
    MessageBox({title=title, message=text, commands={{value=0, name='Close'}}})
end

local function python_default()
    local candidates = {
        '/Library/Frameworks/Python.framework/Versions/Current/bin/python3',
        '/opt/homebrew/bin/python3', '/usr/local/bin/python3'
    }
    for _, path in ipairs(candidates) do
        local file = io.open(path, 'rb')
        if file then file:close(); return path end
    end
    return ''
end

local function fields(text)
    local result = {}
    for part in (text .. '\t'):gmatch('(.-)\t') do result[#result + 1] = part end
    return result
end

local function capabilities()
    local result = {'Lua=' .. tostring(_VERSION), 'HostOS=' .. tostring(HostOS()),
                    'HostType=' .. tostring(HostType()), 'os.execute=' .. type(os.execute),
                    'io.popen=' .. type(io.popen)}
    local ok, loader, why, stage = pcall(function()
        return package.loadlib('/nonexistent/followspot-diagnostic.dylib', 'luaopen_probe')
    end)
    result[#result + 1] = 'loadlib=' .. tostring(ok) .. '|' .. tostring(loader)
                         .. '|' .. tostring(why) .. '|' .. tostring(stage)
    return table.concat(result, '\n')
end

local function Cleanup()
    if active then
        local owned = active
        pcall(write, owned.root .. '/stop', owned.token)
        pcall(write, owned.root .. '/report.txt',
            'STOP REQUESTED by MA cleanup.\nCheck helper-report.txt for actual exit reason.\n'
            .. owned.capabilities)
        Printf('FS Diagnostic: cleanup requested; results: %s', owned.root)
        active = nil
    end
end

local function run(mode, python)
    assert(python:sub(1, 1) == '/' and not python:find('[%z\r\n]'),
           'Enter an absolute path to a Python 3.10+ executable.')
    local report_base = os.getenv('FOLLOWSPOT_DIAGNOSTIC_REPORTS')
    if not report_base then
        local operator_home = assert(os.getenv('HOME'), 'Cannot locate the user home folder')
        report_base = operator_home .. '/MALightingTechnology/gma3_library/followspot_diagnostics'
    end
    assert(os.execute('/bin/mkdir -p ' .. quote(report_base)), 'Cannot create report folder')
    local handle = assert(io.popen('/usr/bin/mktemp -d ' .. quote(report_base .. '/run.XXXXXXXX')))
    local root = assert(handle:read('*l'), 'Cannot create private run folder')
    assert(handle:close())
    local token = assert(root:match('([^/]+)$'))
    active = {root=root, token=token, capabilities=capabilities()}
    write(root .. '/capabilities.txt', active.capabilities)
    write(root .. '/report.txt', 'RUNNING: ' .. mode .. '\n' .. active.capabilities)
    write(root .. '/emulator.py', emulator_source)
    write(root .. '/lease', token .. ':0')
    Printf('FS Diagnostic: mode=%s; results: %s', mode, root)
    local command = quote(python) .. ' ' .. quote(root .. '/emulator.py')
                    .. ' ' .. quote(root) .. ' ' .. quote(token) .. ' ' .. quote(mode)
                    .. ' < /dev/null > ' .. quote(root .. '/reader.log') .. ' 2>&1 &'
    assert(os.execute(command), 'The shell could not launch the emulator')
    local updates, last_sequence, ready, reason = 0, 0, false, nil
    for tick = 1, 360 do
        if mode ~= 'watchdog' or tick <= 15 then
            atomic(root .. '/lease', token .. ':' .. tick)
        end
        if not ready then
            local raw = read(root .. '/ready')
            if raw then
                local hello = fields(raw)
                assert(hello[1] == 'FS_DIAGNOSTIC_1' and hello[2] == token,
                       'Unexpected emulator handshake')
                ready = true
                Printf('FS Diagnostic: helper ready; Python %s; PID %s', hello[3], hello[4])
            end
        end
        local raw_sample = read(root .. '/sample')
        if raw_sample then
            local sample = fields(raw_sample)
            local sequence = tonumber(sample[2])
            assert(sample[1] == token and sequence, 'Malformed emulator sample')
            if sequence > last_sequence then
                updates, last_sequence = updates + 1, sequence
                if updates == 1 or tick % 15 == 0 then
                    Printf('FS Diagnostic: #%d X=%+.2f Y=%+.2f slider=%.0f%% zoom=%+.2f buttons=%s',
                        sequence, tonumber(sample[4]), tonumber(sample[5]),
                        tonumber(sample[6]), tonumber(sample[7]), sample[8])
                end
            end
        end
        local finished = read(root .. '/exit')
        if finished then
            local exit = fields(finished)
            assert(exit[1] == token, 'Unexpected emulator exit owner')
            reason = exit[2]
            break
        end
        coroutine.yield(1 / 30)
    end
    if not reason then
        write(root .. '/stop', token)
        for _ = 1, 60 do
            local finished = read(root .. '/exit')
            if finished then reason = fields(finished)[2]; break end
            coroutine.yield(1 / 30)
        end
    end
    local expected = ({normal='completed', watchdog='lease_expired', fault='injected_fault'})[mode]
    local passed = ready and updates >= 3 and reason == expected
    local summary = (passed and 'PASS' or 'FAIL') .. ': ' .. mode
                    .. '\nReady=' .. tostring(ready) .. '; sample updates=' .. updates
                    .. '\nreason=' .. tostring(reason) .. '; expected=' .. expected
                    .. '\nSynthetic input only. No lighting output.'
                    .. '\n\nReport: ' .. root .. '/report.txt'
    local details = active.capabilities
    write(root .. '/report.txt', summary .. '\n\n' .. details)
    active = nil
    message(summary)
end

local function Main()
    if active then message('A diagnostic is already running.'); return end
    if HostType() ~= 'onPC' or not tostring(HostOS()):lower():find('mac', 1, true) then
        message('This experimental diagnostic requires grandMA3 onPC on macOS.'); return
    end
    local choice = MessageBox({
        title=title,
        message='Emulates axes, slider, zoom and buttons. No joystick needed.\n'
                .. 'Open System Monitor to watch the samples.\n'
                .. 'Requires Python 3.10+; reports are saved under gma3_library/followspot_diagnostics.',
        autoCloseOnInput=false,
        inputs={{name='Python executable', value=python_default(), maxTextLength=512}},
        commands={{value=1, name='1 Run emulation'}, {value=2, name='2 Watchdog test'},
                  {value=3, name='3 Reader fault test'}, {value=0, name='Close'}}
    })
    local modes = {[1]='normal', [2]='watchdog', [3]='fault'}
    if not choice.success or not modes[choice.result] then return end
    local python = choice.inputs['Python executable']
    local ok, why = xpcall(function() run(modes[choice.result], python) end, debug.traceback)
    if not ok then
        local root = active and active.root
        Cleanup()
        local text = 'Diagnostic error:\n' .. tostring(why)
        if root then
            text = text .. '\n\nReports: ' .. root
            pcall(write, root .. '/report.txt', text .. '\n' .. (read(root .. '/reader.log') or ''))
        end
        message(text)
    end
end

return Main, Cleanup
