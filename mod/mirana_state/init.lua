--[[
MIRANA state — CET mod. Kazde 2 s zapise stav hraca do state.json vo svojom priecinku
(CET dovoli modu zapisovat len do vlastneho priecinka). Mirana (inputs/game_state.py) subor cita.

Instalacia: priecinok mirana_state skopiruj do
  <Cyberpunk 2077>\bin\x64\plugins\cyber_engine_tweaks\mods\
(okno MIRANA -> Nastavenia -> Hra -> "Nainstalovat mod" to spravi samo).

Volania hry su prevzate z overenych modov (CP77-DiscordRPC2). Kazdy udaj sa cita cez pcall,
takze ked jeden po patchi hry prestane fungovat, ostatne idu dalej a v "errors" je, ktory.
]]

local INTERVAL = 2.0          -- sekundy medzi zapismi
local elapsed = 0
local lastError = {}

local function safe(name, fn)
    local ok, value = pcall(fn)
    if ok then
        lastError[name] = nil
        return value
    end
    lastError[name] = tostring(value)
    return nil
end

local function loc(key)
    if key == nil then return nil end
    local text = GetLocalizedText(key)
    if text == nil or text == "" then return nil end
    return text
end

-- Minimalny JSON encoder (CET ma vstavany json, ale nechceme od neho zavisiet)
local function encode(value)
    local t = type(value)
    if t == "nil" then return "null" end
    if t == "boolean" then return value and "true" or "false" end
    if t == "number" then
        if value ~= value or value == math.huge or value == -math.huge then return "null" end
        return string.format("%.14g", value)
    end
    if t == "string" then
        local escaped = value:gsub('[%c"\\]', function(c)
            local map = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
            return map[c] or string.format("\\u%04x", c:byte())
        end)
        return '"' .. escaped .. '"'
    end
    if t == "table" then
        local parts = {}
        for k, v in pairs(value) do
            parts[#parts + 1] = encode(tostring(k)) .. ":" .. encode(v)
        end
        return "{" .. table.concat(parts, ",") .. "}"
    end
    return "null"
end

local function collect()
    local player = Game.GetPlayer()
    local state = { ts = os.time(), mod_version = 1, in_game = player ~= nil }
    if not player then return state end
    local id = player:GetEntityID()

    safe("health", function()
        local current = Game.GetStatPoolsSystem():GetStatPoolValue(id, gamedataStatPoolType.Health, false)
        local max = Game.GetStatsSystem():GetStatValue(id, gamedataStatType.Health)
        state.hp_max = math.floor(max + 0.5)
        state.hp = max > 0 and math.floor(current / max * 100 + 0.5) or nil
    end)
    safe("level", function()
        local stats = Game.GetStatsSystem()
        state.level = math.floor(stats:GetStatValue(id, gamedataStatType.Level) + 0.5)
        state.street_cred = math.floor(stats:GetStatValue(id, gamedataStatType.StreetCred) + 0.5)
    end)
    safe("money", function()
        state.money = Game.GetTransactionSystem():GetItemQuantity(player, MarketSystem.Money())
    end)
    safe("lifepath", function()
        local dev = Game.GetScriptableSystemsContainer():Get("PlayerDevelopmentSystem"):GetDevelopmentData(player)
        state.lifepath = dev and dev:GetLifePath().value or nil
    end)
    safe("district", function()
        local manager = Game.GetScriptableSystemsContainer():Get("PreventionSystem").districtManager
        local current = manager and manager:GetCurrentDistrict()
        if not current then return end
        local record = current:GetDistrictRecord()
        local parent = record:ParentDistrict()
        if parent then
            state.district = loc(parent:LocalizedName())
            state.subdistrict = loc(record:LocalizedName())
        else
            state.district = loc(record:LocalizedName())
        end
    end)
    safe("quest", function()
        local journal = Game.GetJournalManager()
        local objective = journal:GetTrackedEntry()
        if not objective then return end
        state.objective = loc(objective:GetDescription())
        local phase = journal:GetParentEntry(objective)
        local quest = phase and journal:GetParentEntry(phase)
        if quest then
            state.quest = loc(quest:GetTitle(journal))
            state.quest_id = quest:GetId()
        end
    end)
    safe("combat", function() state.combat = player:IsInCombat() end)
    safe("vehicle", function()
        local vehicle = Game.GetMountedVehicle(player)
        if vehicle then
            local record = vehicle:GetRecord()
            state.vehicle = record and Game.GetLocalizedTextByKey(record:DisplayName()) or "auto"
        end
    end)
    safe("weapon", function()
        local weapon = player:GetActiveWeapon()
        local record = weapon and weapon:GetWeaponRecord()
        state.weapon = record and Game.GetLocalizedTextByKey(record:DisplayName()) or nil
    end)

    local errors = {}
    for name, message in pairs(lastError) do errors[name] = message end
    if next(errors) then state.errors = errors end
    return state
end

local function write(state)
    -- zapis do docasneho suboru a premenovanie: Mirana nikdy neprecita napoly zapisany JSON
    local file = io.open("state.tmp", "w")
    if not file then return end
    file:write(encode(state))
    file:close()
    os.remove("state.json")
    os.rename("state.tmp", "state.json")
end

registerForEvent("onInit", function()
    print("[MIRANA] mod nacitany, zapisujem state.json kazde " .. INTERVAL .. " s")
end)

registerForEvent("onUpdate", function(delta)
    elapsed = elapsed + delta
    if elapsed < INTERVAL then return end
    elapsed = 0
    local ok, err = pcall(function() write(collect()) end)
    if not ok then print("[MIRANA] chyba: " .. tostring(err)) end
end)

registerForEvent("onShutdown", function()
    pcall(function() write({ ts = os.time(), in_game = false, shutdown = true }) end)
end)
