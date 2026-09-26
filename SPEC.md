# MIRANA — SPEC

Zadanie pre Claude Code. Push-to-talk AI parťáčka pre Cyberpunk 2077 + Kick stream.
Stavia sa po fázach — každá je samostatne testovateľná a commitnutá.

---

## 0. Princípy

1. Push-to-talk na klávese F12.
2. Latenciu zakrýva filler hláška z lokálneho WAV + stav PROCESSING na HUD.
3. Denný strop nákladov v kóde, tvrdý.
4. Každý modul má vlastný try/except a smie zlyhať sám za seba. Supervisor
   reštartuje proces.
5. Vstupy hádžu eventy do fronty, o poradí rozhoduje jedine main.py.
6. Priorita: Erik (PTT) > herné eventy > chat.
7. Model pozná CP2077 z tréningu, lore databáza sa nepoužíva.
8. Konfigurácia patrí do config.yaml.

---

## 1. Štruktúra repa

```
mirana-v2/
├── run.py               # supervisor — spúšťa a reštartuje main.py, heartbeat
├── main.py              # orchestrátor: event loop, priority, stavový automat
├── config.yaml
├── requirements.txt
├── .env                 # API kľúče (necommitovať)
├── persona.md
├── phonetics.yaml       # anglicizmy → SK fonetika, len pre TTS
├── SPEC.md
│
├── inputs/
│   ├── ptt.py           # F12 → nahrávka
│   ├── game_state.py    # číta JSON z CET modu → eventy
│   └── kick_chat.py     # Kick WebSocket, sub filter, fronta
│
├── core/
│   ├── config.py        # načítanie config.yaml + .env, jediné miesto s cestami
│   ├── brain.py         # STT (core/stt.py) → LLM (Opus 5.5, streaming po vetách)
│   ├── stt.py           # Whisper: api (OpenAI) | local (faster-whisper, CUDA)
│   ├── memory.py        # posledných 8 výmen (RAM)
│   ├── longterm.py      # data/memory.json: Erik (postup, fakty) + diváci, medzi sessions
│   ├── budget.py        # denný strop (data/budget.json), cena každej odpovede
│   ├── session.py       # logy do logs/, záznam rozhovoru (jsonl), zámok proti 2. inštancii
│   └── safety.py        # výstupný filter pred TTS
│
├── outputs/
│   ├── voice.py         # TTS (s timeoutom), fonetika, prehrávanie, okamžitý stop
│   ├── speaker.py       # streaming reči: vety → TTS vlákno → prehrávacie vlákno
│   ├── fillers.py       # generovanie a prehrávanie filler hlášok
│   └── overlay.py       # WebSocket server pre OBS
│
├── fillers/             # predgenerované WAV, vznikne pri prvom spustení
├── data/                # memory.json, budget.json (necommitovať)
├── logs/                # mirana-<čas>.log, rozhovor-<čas>.jsonl (necommitovať)
├── overlay/
│   └── index.html       # diegetický HUD — HOTOVÝ, needituj vzhľad
└── mod/
    └── mirana_state/init.lua
```

---

## 2. Fáza 1 — Jadro (PTT → STT → LLM → TTS)

1. `inputs/ptt.py` — pynput + sounddevice: drž F12 → nahrávaj z konfigurovaného
   zariadenia (druhý mikrofón) → pusti → vráť WAV v pamäti.
2. `core/brain.py` — Whisper API (`whisper-1`, jazyk `sk`) → Claude Sonnet 5
   (`claude-sonnet-5`). System prompt = persona.md + riadok stavu hry + pamäť.
   **Personu posielaj ako cacheable blok** (prompt caching). Sonnet 5 neprijíma
   `temperature`; thinking má vždy zapnuté → `effort: low`, `max_tokens` ≥ 800.
   Každá správa od Erika nesie tag `[ERIK]` (kontrakt v persona.md).
3. `core/memory.py` — deque 8 výmen, vkladá sa do promptu.
4. `outputs/voice.py` — Azure TTS `sk-SK-ViktoriaNeural` → prehratie na
   konfigurovateľné zariadenie. Pred TTS sanitizuj text: preč `*`, `_`, emoji, markdown.
5. `main.py` — stavový automat IDLE → LISTENING → PROCESSING → SPEAKING.
6. Každé API volanie: timeout 20 s, 1 retry (rieši SDK cez `max_retries`, nie
   vlastná slučka), pri zlyhaní fallback hláška z config.yaml a návrat do IDLE.
   O fallbackoch rozhoduje main.py, moduly vracajú `None`. Proces nesmie skončiť na výnimke.

**Akceptácia:** hodinový beh, 30+ otázok, žiadny pád, žiadna odpoveď dlhšia
než ~15 s reči.

---

## 3. Fáza 2 — Filler hlášky a barge-in

1. `outputs/fillers.py` — pri prvom spustení vygeneruje cez TTS 8–12 krátkych
   hlášok zo zoznamu v config.yaml do `fillers/*.wav`. Ak súbory existujú,
   negeneruje nič.
   Príklady: „moment, Emzo", „nechaj ma pozrieť", „hmm", „počkaj", „idem na to".
2. Pri pustení F12 okamžite prehraj náhodnú hlášku a pošli na HUD `PROCESSING`.
   Nikdy tú istú dvakrát po sebe.
3. Ak odpoveď dorazí do 800 ms, filler nehraj.
4. Barge-in: stlačenie F12 počas SPEAKING → okamžitý stop prehrávania, zruš
   bežiaci request, prejdi do LISTENING.

**Akceptácia:** medzi pustením klávesy a prvým zvukom nie je ticho. Prerušenie
uprostred vety funguje okamžite.

---

## 4. Fáza 3 — Overlay

`outputs/overlay.py` — WebSocket server na `0.0.0.0:8080`, servíruje
`overlay/index.html`.

HTML je hotové a vystavuje tieto funkcie — napoj na ne WebSocket a **vzhľad neupravuj**:

| Funkcia | Volá sa keď |
|---|---|
| `setState('idle'\|'listening'\|'processing'\|'speaking')` | zmena stavu |
| `showQuestion(text)` | prepis Erikovej otázky alebo `[SYSTÉM]` / meno diváka |
| `typeAnswer(text, msPerChar)` | celá odpoveď naraz, HUD ju vypíše sám |
| `setTelemetry({hp, location, quest, combat})` | nový stav hry |
| `setQueue(n)` | zmena dĺžky chat fronty |

V `index.html` odstráň demo slučku na konci `<script>` a nahraď ju pripojením
na WebSocket. Doplň reconnect logiku.

OBS na notebooku: Browser Source na `http://IP-herného-PC:8080`.

---

## 5. Fáza 4 — Oči (CET mod + proaktívna Mirana)

1. `mod/mirana_state/init.lua` — každé 2 s zapíš `state.json` do priečinka modu (CET inam zapisovať nedovolí):
   HP %, level, street cred, eddies, quest, distrikt, in_combat, in_vehicle.
   Začni s HP + lokácia + quest.
2. `inputs/game_state.py` — čítaj JSON (mtime check), generuj eventy:
   `hp_low` (<25 %), `hp_critical` (<10 %), `district_change`, `level_up`,
   `quest_completed`, `combat_start/end`.
3. Do každej správy (nie do system promptu — rušilo by to cache) pridaj slovenský riadok, nikdy surový JSON:
   `[HRA] zdravie 87 % | Watson, Kabuki | úroveň 23, street cred 18 | quest Ghost Town, cieľ „…“ | mimo boja`
4. Proaktívne hlášky: max 1 / 5 min, nikdy počas SPEAKING. `hp_critical` má
   výnimku z cooldownu.
5. Keď mod nebeží, Mirana funguje ďalej bez kontextu.
6. `core/longterm.py` — dlhodobá pamäť o Erikovi v `data/memory.json` (necommitovať):
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
a lokácie bez toho, aby ich Erik povedal. Po reštarte vie, kde Erik skončil.

---

## 6. Fáza 5 — Kick chat

Pred písaním si načítaj aktuálnu dokumentáciu na docs.kick.com. Modul drž
izolovaný — jeho pád nesmie ovplyvniť zvyšok.

1. `inputs/kick_chat.py` — pripojenie, parsovanie správ a badges odosielateľa.
2. Sub / mod / OG → `!mira <otázka>` ide do fronty. Nesub → žiadne volanie API a žiadny
   hlas: približne každému desiatemu sa na HUD vypíše predvolená veta z config.yaml
   (`kick_chat.nesub_reply_text`), s jeho nickom v `showQuestion`. Nula kreditov.
3. Fronta max 10. Cooldown 30 s globálne, 3 min na diváka. Orchestrátor berie
   z fronty len v stave IDLE a mimo combatu.
4. Nick pred TTS prečisti (čísla, symboly, `xX...Xx`).
6. Hlasový prepínač: „Mirana, chat off" / „chat on" — Erik vypne a zapne spracovanie
   fronty uprostred streamu. Stav sa hlási na HUD (`setQueue`) a v logu.
7. Auto-mute chatu: fronta sa neberie pri HP < 25 %, v combate a 60 s po Erikovej
   otázke. Správy sa medzitým hromadia len do limitu fronty, staršie padajú.
5. Pamäť divákov (`core/longterm.py`, tá istá `data/memory.json`):
   `{nick: {prvýkrát, naposledy, počet návštev, posledné 2–3 témy}}`, trvá medzi
   sessions. Zápis deterministický, bez LLM, pri každej `[CHAT_SUB]` správe. Čítanie:
   pri správe od známeho nicku jeden riadok do promptu
   („Kubo: 3. návšteva, naposledy 21.9. sa pýtal na Sandevistan"). Ukladá sa len nick
   a téma, nič osobné (Kick TOS). „Mirana, zabudni Kuba" záznam zmaže.
   Simulácia 2026-09-21: 8-výmenové okno diváka zabudne za ~2 min.

---

## 7. Fáza 6 — Audio routing + DSP

1. `voice.py` prehráva do VoiceMeeter Input na hernom PC.
2. VST reťaz na tom kanáli: bitcrusher → ring mod → EQ (HP 180 Hz, LP 5200 Hz)
   → echo → limiter.
3. VBAN send `VoiceToStream` → notebook → OBS ako samostatná audio stopa.

---

## 8. Fáza 7 — Hardening

1. `core/budget.py` — počítaj tokeny a odhadovanú cenu za deň.
   HOTOVÉ 2026-09-23 (`limits.daily_usd_cap`, stav v data/budget.json, hláška budget_reached).
2. `core/safety.py` — výstupný filter pred TTS: blokuj obsah ohrozujúci Kick TOS HOTOVÉ 2026-09-26.
   a osobné údaje divákov. Pri zachytení preskoč vetu.
3. `run.py` — supervisor: sleduj heartbeat, pri páde alebo zamrznutí (>60 s) HOTOVÉ 2026-09-26 (start.bat).
   reštartuj. Max 5 reštartov za hodinu.
4. Panic mute na F11 — okamžite umlčí Miranu a pozastaví spracovanie. HOTOVÉ 2026-09-26.
5. Log per session. HOTOVÉ 2026-09-23 (logs/, core/session.py).
6. Pred prvým ostrým streamom 8-hodinový suchý beh. Sleduj RAM a počet API chýb.

---

## 9. Náklady

Model: Claude Opus 5.5 (`claude-opus-5-5`), effort `low`, $4/$20 za milión tokenov, cache read $0.20.
Opus 5.5 premýšľa vždy (aj na low) — prvý zvuk ~4,4 s po F12; Opus 5 ~3,6 s pri podobnej cene
(test 2026-09-23). Prepnutie = jeden riadok `llm.model` v config.yaml.

Merané 2026-09-23: **~0,6 c na otázku** → pri 40 otázkach/hod ~$0.25/hod streamu.
Chat divákov (Sonnet 5) ~0,4 c/správa, cooldown 30 s ⇒ najviac ~$0.45/hod.
`limits.daily_usd_cap: 5.00` vynucuje `core/budget.py` (stav prežije reštart, reset o polnoci).
`llm.fallbacks: "default"`: odmietnutie bezpečnostným filtrom sa zopakuje na inom modeli.

Rozpočet rozbije: effort nad low, pamäť nad 8 výmen, meniaca sa persona (zruší cache), bug v slučke.

---

## 10. Práca s Claude Code

Pozri POSTUP.md, sekcia „Práca s Claude Code“.
