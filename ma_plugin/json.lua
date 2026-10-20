-- Small data-only JSON codec; never evaluates incoming text as Lua.
local json = {null={}}
local escapes = {['"']='\\"', ['\\']='\\\\', ['\b']='\\b', ['\f']='\\f',
                 ['\n']='\\n', ['\r']='\\r', ['\t']='\\t'}
local function quoted(s)
    return '"' .. s:gsub('[%z\1-\31\\"]', function(c)
        return escapes[c] or string.format('\\u%04x', c:byte())
    end) .. '"'
end
function json.encode(value)
    local seen = {}
    local function emit(v, depth)
        assert(depth < 64, 'JSON nesting limit')
        if v == json.null or v == nil then return 'null' end
        local kind = type(v)
        if kind == 'string' then return quoted(v) end
        if kind == 'boolean' then return tostring(v) end
        if kind == 'number' then
            assert(v == v and v ~= math.huge and v ~= -math.huge, 'Non-finite JSON number')
            return string.format('%.17g', v)
        end
        assert(kind == 'table' and not seen[v], 'Invalid or cyclic JSON value')
        seen[v] = true
        local count, array = 0, true
        for key in pairs(v) do
            count = count + 1
            if type(key) ~= 'number' or key % 1 ~= 0 or key < 1 then array = false end
        end
        array = array and count > 0 and count == #v
        local parts = {}
        if array then
            for _, item in ipairs(v) do parts[#parts+1] = emit(item, depth+1) end
        else
            local keys = {}
            for key in pairs(v) do assert(type(key)=='string', 'JSON object key must be text'); keys[#keys+1]=key end
            table.sort(keys)
            for _, key in ipairs(keys) do parts[#parts+1] = quoted(key)..':'..emit(v[key],depth+1) end
        end
        seen[v] = nil
        return (array and '[' or '{') .. table.concat(parts, ',') .. (array and ']' or '}')
    end
    return emit(value,0)
end
function json.decode(text)
    assert(type(text)=='string' and #text<=1048576, 'Invalid JSON input size')
    local at = 1
    local function skip() at = text:find('[^ \t\r\n]', at) or (#text+1) end
    local function hex()
        local s=text:sub(at,at+3); assert(#s==4 and s:match('^%x%x%x%x$'), 'Invalid Unicode escape')
        at=at+4; return tonumber(s,16)
    end
    local function string_value()
        assert(text:sub(at,at)=='"','Expected JSON string'); at=at+1
        local parts={}
        while at<=#text do
            local c=text:sub(at,at); at=at+1
            if c=='"' then return table.concat(parts) end
            if c=='\\' then
                local e=text:sub(at,at); at=at+1
                local basic={['"']='"',['\\']='\\',['/']='/',b='\b',f='\f',n='\n',r='\r',t='\t'}
                if e=='u' then
                    local code=hex()
                    if code>=0xd800 and code<=0xdbff then
                        assert(text:sub(at,at+1)=='\\u','Missing Unicode surrogate'); at=at+2
                        local low=hex(); assert(low>=0xdc00 and low<=0xdfff,'Invalid Unicode surrogate')
                        code=0x10000+(code-0xd800)*1024+low-0xdc00
                    else assert(code<0xdc00 or code>0xdfff,'Invalid Unicode surrogate') end
                    parts[#parts+1]=utf8.char(code)
                else assert(basic[e], 'Invalid JSON escape'); parts[#parts+1]=basic[e] end
            else assert(c:byte()>=32,'Control character in JSON string'); parts[#parts+1]=c end
        end
        error('Unclosed JSON string')
    end
    local parse
    parse=function(depth)
        assert(depth<64,'JSON nesting limit'); skip()
        local c=text:sub(at,at)
        if c=='"' then return string_value() end
        if c=='{' or c=='[' then
            local object=c=='{'; local close=object and '}' or ']'; at=at+1; skip()
            local result,seen={},{}
            if text:sub(at,at)==close then at=at+1; return result end
            while true do
                skip(); local key=#result+1
                if object then
                    key=string_value(); assert(not seen[key],'Duplicate JSON key'); seen[key]=true
                    skip(); assert(text:sub(at,at)==':','Expected colon'); at=at+1
                end
                result[key]=parse(depth+1); skip()
                c=text:sub(at,at); at=at+1
                if c==close then return result end
                assert(c==',','Expected comma')
            end
        end
        for word,value in pairs({['true']=true,['false']=false,['null']=json.null}) do
            if text:sub(at,at+#word-1)==word then at=at+#word; return value end
        end
        local begin=at
        if c=='-' then at=at+1 end
        if text:sub(at,at)=='0' then at=at+1
        else
            assert(text:sub(at,at):match('[1-9]'),'Invalid JSON number')
            repeat at=at+1 until not text:sub(at,at):match('%d')
        end
        if text:sub(at,at)=='.' then
            at=at+1; assert(text:sub(at,at):match('%d'),'Invalid JSON fraction')
            repeat at=at+1 until not text:sub(at,at):match('%d')
        end
        if text:sub(at,at):match('[eE]') then
            at=at+1
            if text:sub(at,at):match('[+-]') then at=at+1 end
            assert(text:sub(at,at):match('%d'),'Invalid JSON exponent')
            repeat at=at+1 until not text:sub(at,at):match('%d')
        end
        local n=tonumber(text:sub(begin,at-1))
        assert(n and n==n and n~=math.huge and n~=-math.huge,'Invalid JSON number')
        return n
    end
    local value=parse(0); skip(); assert(at>#text,'Trailing JSON data'); return value
end
return json
