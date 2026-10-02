--[[
MIRANA state — CET mod. Kazdu 1 s zapise stav hraca do state.json vo svojom priecinku
(CET dovoli modu zapisovat len do vlastneho priecinka). Mirana (inputs/game_state.py) subor cita.

Instalacia: priecinok mirana_state skopiruj do
  <Cyberpunk 2077>\bin\x64\plugins\cyber_engine_tweaks\mods\
(okno MIRANA -> Nastavenia -> Hra -> "Nainstalovat mod" to spravi samo).

Volania hry su prevzate z overenych modov (CP77-DiscordRPC2, CETBridge) a z dekompilovanych
skriptov hry. Kazdy udaj sa cita cez pcall, takze ked jeden po patchi hry prestane fungovat,
ostatne idu dalej a v "errors" je, ktory.

Texty z hry (questy, stvrte, veci) su v jazyku hry — Mirana ich berie ako vlastne mena.
]]

local VERSION = 5
local INTERVAL = 1.0          -- sekundy medzi zapismi (rychla reakcia na kriticke HP)
local STORY_INTERVAL = 30.0   -- zoznam dokoncenych questov je drahsi, staci raz za 30 s
local elapsed = 0
local storyElapsed = STORY_INTERVAL
local story = nil             -- posledny vysledok, posiela sa v kazdom zapise
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

local function locKey(cname)
    if cname == nil then return nil end
    local text = Game.GetLocalizedTextByKey(cname)
    if text == nil or text == "" then return nil end
    return text
end

local function round(x) return math.floor(x + 0.5) end

-- Enum z hry ako text ("MainQuest"); CET vracia enum objekt s .value
local function enumName(e)
    if type(e) == "userdata" or type(e) == "table" then return e.value end
    return e
end

-- Nazov predmetu (zbran, OS) z ItemID
local function itemName(itemID)
    if not itemID then return nil end
    local tdbid = itemID.id or ItemID.GetTDBID(itemID)
    local record = tdbid and TweakDBInterface.GetItemRecord(tdbid)
    return record and locKey(record:DisplayName()) or nil
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
        -- len ASCII riadiace znaky: %c podla locale zachytí aj bajty UTF-8 diakritiky
        local escaped = value:gsub('[\1-\31"\\]', function(c)
            local map = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
            return map[c] or string.format("\\u%04x", c:byte())
        end)
        return '"' .. escaped .. '"'
    end
    if t == "table" then
        local parts = {}
        if #value > 0 then  -- pole
            for _, v in ipairs(value) do parts[#parts + 1] = encode(v) end
            return "[" .. table.concat(parts, ",") .. "]"
        end
        for k, v in pairs(value) do
            parts[#parts + 1] = encode(tostring(k)) .. ":" .. encode(v)
        end
        return "{" .. table.concat(parts, ",") .. "}"
    end
    return "null"
end

local function collect()
    local player = Game.GetPlayer()
    local state = { ts = os.time(), mod_version = VERSION, in_game = player ~= nil }
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
            state.quest_type = enumName(journal:GetQuestType(quest))
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

    -- zasoby: nabitia liecenia a granatov, naboje v zasobniku, RAM
    -- Pool nabiti je v percentach z maxima (hra ho tak zobrazuje v dpadHintItem): nabitia = floor(% * max)
    safe("supplies", function()
        local pools, stats = Game.GetStatPoolsSystem(), Game.GetStatsSystem()
        local function charges(pool, maxStat)
            local max = round(stats:GetStatValue(id, maxStat))
            local perc = pools:GetStatPoolValue(id, pool, true)
            return math.floor(perc / 100 * max + 0.001), max
        end
        state.heal_charges, state.heal_max = charges(gamedataStatPoolType.HealingItemsCharges, gamedataStatType.HealingItemMaxCharges)
        state.grenade_charges, state.grenade_max = charges(gamedataStatPoolType.GrenadesCharges, gamedataStatType.GrenadesMaxCharges)
    end)
    safe("ram", function()
        state.ram = round(Game.GetStatPoolsSystem():GetStatPoolValue(id, gamedataStatPoolType.Memory, false))
        state.ram_max = round(Game.GetStatsSystem():GetStatValue(id, gamedataStatType.Memory))
    end)
    safe("ammo", function()
        local weapon = player:GetActiveWeapon()
        if not weapon or not weapon:IsRanged() then return end  -- kudlanky, katany: ziadne naboje
        state.ammo = WeaponObject.GetMagazineAmmoCount(weapon)
        state.ammo_max = WeaponObject.GetMagazineCapacity(weapon)
        state.ammo_reserve = WeaponObject.HasAvailableAmmoInInventory(weapon)
    end)

    -- rozvoj postavy: atributy, nerozdelene body, kapacita kybervyzbroje
    safe("attributes", function()
        local stats = Game.GetStatsSystem()
        state.attributes = {
            body = round(stats:GetStatValue(id, gamedataStatType.Strength)),
            reflexes = round(stats:GetStatValue(id, gamedataStatType.Reflexes)),
            tech = round(stats:GetStatValue(id, gamedataStatType.TechnicalAbility)),
            intelligence = round(stats:GetStatValue(id, gamedataStatType.Intelligence)),
            cool = round(stats:GetStatValue(id, gamedataStatType.Cool)),
        }
    end)
    safe("dev_points", function()
        local dev = Game.GetScriptableSystemsContainer():Get("PlayerDevelopmentSystem"):GetDevelopmentData(player)
        state.perk_points = dev:GetDevPoints(gamedataDevelopmentPointType.Primary)
        state.attribute_points = dev:GetDevPoints(gamedataDevelopmentPointType.Attribute)
    end)
    safe("cyberware", function()
        local stats = Game.GetStatsSystem()
        state.cyberware_capacity = round(stats:GetStatValue(id, gamedataStatType.Humanity))
        state.cyberware_free = round(stats:GetStatValue(id, gamedataStatType.HumanityAvailable))
    end)

    -- vybavenie: operacny system (kyberdeck/Sandevistan/Berserk), zbrane v slotoch, brnenie
    safe("equipment", function()
        local data = Game.GetScriptableSystemsContainer():Get("EquipmentSystem"):GetPlayerData(player)
        state.os = itemName(data:GetItemInEquipSlot(gamedataEquipmentArea.SystemReplacementCW, 0))
        local weapons = {}
        for slot = 0, 2 do
            local name = itemName(data:GetItemInEquipSlot(gamedataEquipmentArea.Weapon, slot))
            if name then weapons[#weapons + 1] = name end
        end
        state.weapons = weapons
        state.armor = round(Game.GetStatsSystem():GetStatValue(id, gamedataStatType.Armor))
    end)

    -- ciel pod zameriavacom
    safe("target", function()
        local target = Game.GetTargetingSystem():GetLookAtObject(player, false, false)
        if not target then return end
        local kind = target:IsNPC() and "npc" or target:IsVehicle() and "vehicle" or target:IsDevice() and "device" or nil
        if not kind then return end
        local name = target:GetDisplayName()
        if name == nil or name == "" then return end
        if name:find("^Gameplay%-") or name:find("^LocKey#") then  -- zariadenia vracaju kluc, nie text
            name = loc(name) or name
        end
        local t = { name = name, kind = kind }
        if kind == "npc" then
            local tid = target:GetEntityID()
            pcall(function() t.hostile = target:IsHostile() end)
            pcall(function() t.dead = target:IsDead() end)
            pcall(function() t.level = round(Game.GetStatsSystem():GetStatValue(tid, gamedataStatType.PowerLevel)) end)
            pcall(function() t.civilian = target:IsCharacterCivilian() end)
            pcall(function() t.boss = target:IsBoss() end)
            pcall(function()  -- posledny parameter true = hodnota v percentach
                t.hp = round(Game.GetStatPoolsSystem():GetStatPoolValue(tid, gamedataStatPoolType.Health, true))
            end)
        end
        state.target = t
    end)

    -- policia: 0 = cisto, 1-5 hviezd
    safe("police", function()
        state.wanted = Game.GetScriptableSystemsContainer():Get("PreventionSystem"):GetHeatStageAsInt()
    end)

    -- svet: cas v hre, pocasie, sceny (rozhovor, cutscena)
    safe("world", function()
        local now = Game.GetTimeSystem():GetGameTime()
        state.time = string.format("%02d:%02d", GameTime.Hours(now), GameTime.Minutes(now))
    end)
    safe("weather", function()
        -- worldWeatherScriptInterface ma len dazd: NoRain / LightRain / HeavyRain
        state.weather = enumName(Game.GetWeatherSystem():GetRainIntensityType())
    end)
    safe("scene", function()
        local defs = GetAllBlackboardDefs().PlayerStateMachine
        local bb = Game.GetBlackboardSystem():GetLocalInstanced(id, defs)
        state.scene_tier = bb:GetInt(defs.HighLevel)
    end)

    -- auto: rychlost a radio
    safe("drive", function()
        local vehicle = Game.GetMountedVehicle(player)
        if not vehicle then return end
        local speed = math.abs(vehicle:GetCurrentSpeed())
        local mult = Game.GetStatsDataSystem():GetValueFromCurve(CName.new("vehicle_ui"), speed, CName.new("speed_to_multiplier"))
        state.speed_kmh = round(speed * mult * 1.609)  -- krivka hry dava mph ako tachometer
        state.driver = vehicle:IsPlayerDriver()
    end)
    safe("radio", function()
        local vehicle = Game.GetMountedVehicle(player)
        if vehicle and vehicle:IsRadioReceiverActive() then
            state.radio = locKey(vehicle:GetRadioReceiverStationName())
            state.song = locKey(vehicle:GetRadioReceiverTrackName())
            return
        end
        local pocket = player:GetPocketRadio()
        if pocket and pocket:IsActive() then
            state.radio = locKey(pocket:GetStationName())
            state.song = locKey(pocket:GetTrackName())
        end
    end)

    -- postup v pribehu (zbiera sa raz za 30 s, pozri collectStory)
    if story then state.story = story end

    local errors = {}
    for name, message in pairs(lastError) do errors[name] = message end
    if next(errors) then state.errors = errors end
    return state
end

-- Dokoncene questy: hlavne s id (poradie pribehu sa da odvodit z id q000..q116), ostatne len pocet
local function collectStory()
    local journal = Game.GetJournalManager()
    local filter = gameJournalRequestStateFilter.new()
    filter.succeeded = true
    local context = gameJournalRequestContext.new()
    context.stateFilter = filter
    local main, side = {}, 0
    for _, quest in ipairs(journal:GetQuests(context) or {}) do
        local qtype = journal:GetQuestType(quest)
        if qtype == gameJournalQuestType.MainQuest or enumName(qtype) == "MainQuest" then
            main[#main + 1] = { id = quest:GetId(), title = loc(quest:GetTitle(journal)) }
        else
            side = side + 1
        end
    end
    return { main_done = main, side_done = side }
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
    storyElapsed = storyElapsed + delta
    if elapsed < INTERVAL then return end
    elapsed = 0
    if storyElapsed >= STORY_INTERVAL and Game.GetPlayer() then
        storyElapsed = 0
        local ok, value = pcall(collectStory)
        if ok then
            story = value
            lastError.story = nil
        else
            lastError.story = tostring(value)
        end
    end
    local ok, err = pcall(function() write(collect()) end)
    if not ok then print("[MIRANA] chyba: " .. tostring(err)) end
end)

registerForEvent("onShutdown", function()
    pcall(function() write({ ts = os.time(), in_game = false, shutdown = true }) end)
end)
