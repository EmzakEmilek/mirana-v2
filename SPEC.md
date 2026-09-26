# MIRANA — SPEC

Zadanie pre Claude Code. Push-to-talk AI parťáčka pre Cyberpunk 2077 + Kick stream.
Stavia sa po fázach — každá je samostatne testovateľná a commitnutá.
Stav k 2026-09-26: fázy 1–3 a 7 hotové, fáza 4 okrem dlhodobej pamäte, fáza 6 len efekty hlasu,
fáza 5 nezačatá (podrobne v PROGRESS.md).

---

## 0. Princípy

1. Push-to-talk: drž tlačidlo (`audio.ptt_key`, predvolene zadné bočné tlačidlo myši).
2. Latenciu zakrýva filler hláška z lokálneho WAV + stav PROCESSING na HUD; odpoveď ide po vetách (streaming).
3. Denný strop nákladov v kóde, tvrdý.
4. Každý modul má vlastný try/except a smie zlyhať sám za seba. Supervisor
   reštartuje proces.
5. Vstupy hádžu eventy do fronty, o poradí rozhoduje jedine main.py.
6. Priorita: Erik (PTT) > herné eventy > chat.
7. Model pozná CP2077 z tréningu, lore databáza sa nepoužíva.
8. Konfigurácia patrí do config.yaml; všetko bežné sa dá nastaviť v okne (gui_settings.py).
9. Do promptu ide len slovenský text, nikdy surový JSON ani anglické kľúče (drží to čistú slovenčinu).

---

## 1. Štruktúra repa

```
mirana-v2/
├── gui.py               # ovládacie okno (ikona na ploche), spúšťa run.py
├── gui_settings.py      # okno Nastavenia — zapisuje config.yaml a persona.md
├── install_shortcut.py  # ikona na plochu a do Štart menu
├── run.py               # supervisor — spúšťa a reštartuje main.py, heartbeat
├── start.bat            # spustenie bez okna (konzola)
├── main.py              # orchestrátor: event loop, priority, stavový automat
├── config.yaml
├── requirements.txt
├── .env                 # API kľúče (necommitovať), šablóna .env.example
├── persona.md
├── phonetics.yaml       # anglicizmy → SK fonetika, len pre TTS
│
├── inputs/
│   ├── ptt.py           # PTT (klávesnica aj myš) → nahrávka, panic mute
│   ├── game_state.py    # state.json z CET modu → riadok [HRA] + eventy
│   └── kick_chat.py     # PLÁN (fáza 5): Kick WebSocket, sub filter, fronta
│
├── core/
│   ├── config.py        # načítanie config.yaml + .env, jediné miesto s cestami
│   ├── settings.py      # zápis config.yaml / persona.md so zachovaním komentárov (ruamel.yaml)
│   ├── brain.py         # LLM (Opus 5.5, streaming po vetách, prompt cache)
│   ├── stt.py           # Whisper: local (faster-whisper, CUDA) | api (OpenAI), filter halucinácií
│   ├── memory.py        # pamäť rozhovoru: 12 výmen, orez naraz na 6 (kvôli cache)
│   ├── longterm.py      # PLÁN: data/memory.json — Erik (postup, fakty) + diváci, medzi sessions
│   ├── budget.py        # denný strop (data/budget.json), cena každej odpovede
│   ├── session.py       # logy do logs/, záznam rozhovoru (jsonl), zámok proti 2. inštancii
│   └── safety.py        # výstupný filter pred TTS
│
├── outputs/
│   ├── voice.py         # Azure TTS (s timeoutom), fonetika, prehrávanie, okamžitý stop
│   ├── voice_fx.py      # efekty hlasu (pedalboard): filtre, bitcrusher, ring mod, chorus, echo
│   ├── speaker.py       # streaming reči: vety → TTS vlákno → prehrávacie vlákno
│   ├── fillers.py       # generovanie a prehrávanie filler hlášok
│   └── overlay.py       # HTTP + WebSocket server pre HUD
│
├── tools/simulate_game.py  # falošný state.json na testovanie bez hry
├── assets/              # ikona
├── fillers/             # predgenerované WAV, vznikne pri prvom spustení (necommitovať)
├── data/                # budget.json, heartbeat, zálohy nastavení, sim_state.json (necommitovať)
├── logs/                # mirana-<čas>.log, rozhovor-<čas>.jsonl, supervisor.log (necommitovať)
├── overlay/index.html   # HUD (živé jadro, písanie po vetách)
└── mod/mirana_state/init.lua  # CET mod
```

---

## 2. Fáza 1 — Jadro (PTT → STT → LLM → TTS) — HOTOVÁ

1. `inputs/ptt.py` — pynput + sounddevice: drž PTT → nahrávaj z `audio.input_device`
   (stream je otvorený stále) → pusti → WAV v pamäti. PTT aj panic mute môžu byť kláves alebo
   tlačidlo myši (`mouse_x1`, `mouse_x2`, `mouse_middle`); spracovanie nahrávky beží mimo hooku.
2. `core/stt.py` — lokálny faster-whisper `medium` na CUDA, jazyk `sk`, `initial_prompt` = slovenský
   prefix + slovník názvov z hry (max 224 tokenov). Prepis, ktorý len zopakuje prompt, sa zahodí.
   `stt.provider: api` = OpenAI Whisper ako záloha.
3. `core/brain.py` — Claude Opus 5.5 (`claude-opus-5-5`), effort `low`, streaming, vety idú do TTS
   hneď, ako vzniknú. Persona je cacheable system blok, breakpoint aj na novej otázke (cache pamäte).
   Server-side fallback (`llm.fallbacks: "default"`), ošetrené `stop_reason` (refusal, max_tokens, prázdne).
   Každá správa od Erika nesie tag `[ERIK]`, pred ním riadok `[HRA]`, ak hra beží.
4. `core/memory.py` — 12 výmen, pri prekročení orez naraz na 6; do pamäte ide len vypočutá časť odpovede.
5. `outputs/voice.py` — Azure TTS `sk-SK-ViktoriaNeural` + `phonetics.yaml` (celé slová) →
   `outputs/voice_fx.py` → prehratie po 50 ms kusoch (stop z ktoréhokoľvek vlákna).
6. `main.py` — stavový automat IDLE → LISTENING → PROCESSING → SPEAKING.
7. Každé API volanie: timeout 20 s, 1 retry (SDK), pri zlyhaní fallback hláška z config.yaml a návrat do IDLE.
   O fallbackoch rozhoduje main.py, moduly vracajú `None`. Proces nesmie skončiť na výnimke.

**Akceptácia:** hodinový beh, 30+ otázok, žiadny pád, žiadna odpoveď dlhšia než ~15 s reči. Splnené.

---

## 3. Fáza 2 — Filler hlášky a barge-in — HOTOVÁ

1. `outputs/fillers.py` — z `fillers.lines` vygeneruje cez TTS `fillers/*.wav`; existujúce negeneruje.
   Po zmene hlasu alebo hlášok v okne sa staré WAV zmažú a vzniknú znova. Efekty hlasu sa aplikujú pri načítaní.
2. Filler zaznie, len ak odpoveď nepríde do `fillers.skip_if_faster_than_ms` (1300 ms). Nikdy
   tú istú dvakrát po sebe. Na HUD je filler odlíšený (biely, v riadku otázky).
3. Barge-in: PTT počas PROCESSING/SPEAKING → okamžitý stop, zrušenie úlohy, LISTENING.

---

## 4. Fáza 3 — Overlay — HOTOVÁ

`outputs/overlay.py` — HTTP + WebSocket na `0.0.0.0:8080`, servíruje `overlay/index.html`.
Nový klient dostane posledný stav.

| udalosť | kedy |
|---|---|
| `state` | idle / listening / processing / speaking / muted |
| `filler` | zaznel filler |
| `answer_start`, `answer_append` | začiatok odpovede, ďalšia vypočutá veta (tempo podľa dĺžky audia) |
| `question` | text v riadku otázky (Erikova otázka sa nezobrazuje) |
| `telemetry` | lokalita, quest, boj |
| `level` | hlasitosť (Erik aj Mirana) — živé jadro reaguje |
| `erik`, `budget`, `game`, `info` | pre ovládacie okno |
| `queue` | PLÁN (fáza 5): dĺžka chat fronty |

Príkazy (`mute`, `quit`) prijíma server len z localhostu (ovládacie okno). HUD v4: canvas „živé jadro",
text sa píše po vetách, 5 s po dohovorení zmizne; HP nezobrazuje (vidno ho v hre).

OBS na notebooku: Browser Source na `http://IP-herného-PC:8080`.

---

## 5. Fáza 4 — Oči (CET mod + proaktívna Mirana) — HOTOVÁ okrem bodu 6

1. `mod/mirana_state/init.lua` (v3) — každé 2 s zapíše `state.json` do priečinka modu (CET inam zapisovať
   nedovolí), atomicky cez `state.tmp`. Každý údaj cez `pcall`, chyby v poli `errors`:
   HP, nabitia liečenia/granátov (percentá poolu × max), náboje a kapacita zásobníka (len strelné zbrane), RAM,
   level, street cred, eddies, lifepath, štvrť, quest + cieľ (+ typ, id), boj, vozidlo, rýchlosť, rádio a skladba,
   zbraň v ruke, atribúty, nerozdelené body, kapacita kybervýzbroje, OS, zbrane v slotoch, brnenie,
   cieľ pod zameriavačom, polícia (heat 0–5), čas, počasie, scéna (PSM HighLevel ≥ 3 = rozhovor/cutscéna),
   dokončené hlavné questy (raz za 30 s).
2. `inputs/game_state.py` — číta JSON (mtime), generuje eventy:
   `hp_low` (<25 %), `hp_critical` (<10 %), `death`, `district_change`, `level_up`, `quest_changed`,
   `quest_completed`, `wanted_up`, `wanted_clear`, `combat_start/end`. „Neobjevené" (`generic_sts_quest`,
   neobjavené miesto na mape) nie je quest; návrat z neho na ten istý quest nie je nový quest.
   Chyby modu loguje ako warning pri zmene.
3. Do každej správy (nie do system promptu — rušilo by to cache) ide slovenský riadok, prázdne časti sa vynechajú:
   `[HRA] zdravie 88 % (liečenie 5 z 6, granáty 1 z 2) | Heywood, Glen, 01:44, dážď | v boji, polícia ho hľadá (3 hviezdy) | …`
   Názvy z hry sú v jazyku hry (Erik hrá po česky); persona ich povie tak, reč okolo po slovensky.
4. Proaktívne hlášky (`game_state.speak_on`): max 1 / 5 min, nie skôr ako 30 s po Erikovej otázke,
   nikdy počas SPEAKING ani počas scény v hre. `hp_critical` a `death` majú výnimku z cooldownu
   a počkajú, kým Mirana dohovorí.
5. Keď mod nebeží (hra vypnutá, menu, starší stav ako 10 s), Mirana funguje ďalej bez riadku [HRA].
6. **ZOSTÁVA:** `core/longterm.py` — dlhodobá pamäť o Erikovi v `data/memory.json` (necommitovať):
   - **Herný postup** z telemetrie, bez LLM: level, lifepath, štvrť, aktívny quest,
     zoznam dokončených questov. Slúži aj spoiler pravidlu — čo Erik dokončil,
     spoiler nie je.
   - **Osobné fakty** (čo o sebe povie v rozhovore): na konci session jedno volanie
     Haiku 4.5 nad výmenami → 5–15 riadkov. Voliteľné,
     `memory.longterm.extract_facts: true|false`.
   - Do promptu ide ako **samostatný system blok za personou** (~150 tokenov), nie
     do persony, aby sa nerušil jej cache.
   - Hlasové príkazy „Mirana, zabudni to" / „čo o mne vieš?" — druhý číta záznam
     doslovne. Súbor je čitateľný JSON, Erik ho môže upraviť ručne.

**Akceptácia:** „Mirana, čo mám robiť?" → odpoveď vychádza z aktívneho questu
a lokácie bez toho, aby ich Erik povedal (splnené v hre 2026-09-26). Po reštarte vie, kde Erik skončil (bod 6).

---

## 6. Fáza 5 — Kick chat — NEZAČATÁ (zatiaľ vypnutá, `kick_chat.enabled: false`)

Pred písaním si načítaj aktuálnu dokumentáciu na docs.kick.com. Modul drž
izolovaný — jeho pád nesmie ovplyvniť zvyšok. Nastavenia sú už v `config.yaml` (`kick_chat`).

1. `inputs/kick_chat.py` — pripojenie, parsovanie správ a badges odosielateľa.
2. Sub / mod / OG → `!mira <otázka>` ide do fronty. Nesub → žiadne volanie API a žiadny
   hlas: približne každému desiatemu sa na HUD vypíše predvolená veta z config.yaml
   (`kick_chat.nesub_reply_text`), s jeho nickom v riadku otázky. Nula kreditov.
3. Fronta max 10. Cooldown 30 s globálne, 3 min na diváka. Orchestrátor berie
   z fronty len v stave IDLE a mimo combatu. Divákom odpovedá `llm.chat_model` (Sonnet 5).
4. Nick pred TTS prečisti (čísla, symboly, `xX...Xx`).
5. Pamäť divákov (`core/longterm.py`, tá istá `data/memory.json`):
   `{nick: {prvýkrát, naposledy, počet návštev, posledné 2–3 témy}}`, trvá medzi
   sessions. Zápis deterministický, bez LLM, pri každej `[CHAT_SUB]` správe. Čítanie:
   pri správe od známeho nicku jeden riadok do promptu
   („Kubo: 3. návšteva, naposledy 21.9. sa pýtal na Sandevistan"). Ukladá sa len nick
   a téma, nič osobné (Kick TOS). „Mirana, zabudni Kuba" záznam zmaže.
   Simulácia 2026-09-21: 8-výmenové okno diváka zabudne za ~2 min.
6. Hlasový prepínač: „Mirana, chat off" / „chat on" — Erik vypne a zapne spracovanie
   fronty uprostred streamu. Stav sa hlási na HUD (`queue`) a v logu.
7. Auto-mute chatu: fronta sa neberie pri HP < 25 %, v combate a 60 s po Erikovej
   otázke. Správy sa medzitým hromadia len do limitu fronty, staršie padajú.

---

## 7. Fáza 6 — Audio routing + DSP — ČIASTOČNE

1. **HOTOVÉ 2026-09-26:** efekty hlasu robí Mirana sama (`outputs/voice_fx.py`, pedalboard) namiesto
   VST reťaze vo Voicemeeteri: HP/LP filter → bitcrusher → ring mod → chorus → echo → kompresor
   → vyrovnanie hlasitosti (špičky max −1 dBFS). Presety `jemny` / `night_city` / `robot`, ~25 ms na vetu.
   Fungujú na slúchadlách aj cez Voicemeeter, platia aj pre fillery.
2. **ZOSTÁVA:** `audio.output_device` prepnúť zo slúchadiel na Voicemeeter Input na hernom PC.
3. **ZOSTÁVA:** VBAN send `VoiceToStream` → notebook → OBS ako samostatná audio stopa.

---

## 8. Fáza 7 — Hardening — HOTOVÁ okrem suchého behu

1. `core/budget.py` — denný strop `limits.daily_usd_cap`, stav v data/budget.json, hláška budget_reached. HOTOVÉ.
2. `core/safety.py` — výstupný filter pred TTS: e-maily, telefóny, IP, odkazy, `safety.blocked_words`;
   zachytená veta sa preskočí. HOTOVÉ.
3. `run.py` — supervisor: heartbeat, reštart pri páde alebo zamrznutí (>60 s), max 5 za hodinu. HOTOVÉ.
4. Panic mute (`audio.panic_mute_key`) — okamžite umlčí Miranu a pozastaví spracovanie. HOTOVÉ.
5. Log per session + záznam rozhovoru. HOTOVÉ.
6. **ZOSTÁVA:** pred prvým ostrým streamom 8-hodinový suchý beh. Sleduj RAM a počet API chýb.

---

## 9. Náklady

Model: Claude Opus 5.5 (`claude-opus-5-5`), effort `low`, $4/$20 za milión tokenov, cache read $0.20.
Opus 5.5 premýšľa vždy (aj na low). Opus 5 je o ~1 s rýchlejší pri podobnej cene (test 2026-09-23).
Prepnutie = `llm.model` v config.yaml alebo v okne.

Merané 2026-09-26 v hre s telemetriou: 53 otázok za $0.38 → **~0,7 c na otázku** (riadok [HRA]
pridáva ~250 tokenov), pri 40 otázkach/hod ~$0.30/hod streamu, 4 h ~$1.15–1.30.
Chat divákov (Sonnet 5) ~0,4 c/správa, cooldown 30 s ⇒ najviac ~$0.45/hod.
`limits.daily_usd_cap: 5.00` vynucuje `core/budget.py` (stav prežije reštart, reset o polnoci).
`llm.fallbacks: "default"`: odmietnutie bezpečnostným filtrom sa zopakuje na inom modeli.

Odozva (pustenie PTT → prvý zvuk): mimo hry ~4 s, v hre medián 5,9 s (prepis 1,6 s namiesto ~0,7 s,
lebo hra vyťažuje GPU; prvá veta z Opusu 3–4 s).

Rozpočet rozbije: effort nad low, dlhšia pamäť, meniaca sa persona (zruší cache), bug v slučke.

---

## 10. Práca s Claude Code

Pozri POSTUP.md, sekcia „Práca s Claude Code“.
