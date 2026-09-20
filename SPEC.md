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
├── .env                 # API kľúče (necommitovať)
├── persona.md
├── SPEC.md
│
├── inputs/
│   ├── ptt.py           # F12 → nahrávka
│   ├── game_state.py    # číta JSON z CET modu → eventy
│   └── kick_chat.py     # Kick WebSocket, sub filter, fronta
│
├── core/
│   ├── brain.py         # STT (Whisper) → LLM (Sonnet) → text
│   ├── memory.py        # posledných 8 výmen (RAM)
│   ├── budget.py        # denný strop, počítadlo tokenov
│   └── safety.py        # výstupný filter pred TTS
│
├── outputs/
│   ├── voice.py         # TTS, prehrávanie, okamžitý stop
│   ├── fillers.py       # generovanie a prehrávanie filler hlášok
│   └── overlay.py       # WebSocket server pre OBS
│
├── fillers/             # predgenerované WAV, vznikne pri prvom spustení
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
   **Personu posielaj ako cacheable blok** (prompt caching).
3. `core/memory.py` — deque 8 výmen, vkladá sa do promptu.
4. `outputs/voice.py` — Azure TTS `sk-SK-ViktoriaNeural` → prehratie na
   konfigurovateľné zariadenie. Pred TTS sanitizuj text: preč `*`, `_`, emoji, markdown.
5. `main.py` — stavový automat IDLE → LISTENING → PROCESSING → SPEAKING.
6. Každé API volanie: timeout 20 s, 1 retry, pri zlyhaní fallback hláška
   z config.yaml a návrat do IDLE. Proces nesmie skončiť na výnimke.

**Akceptácia:** hodinový beh, 30+ otázok, žiadny pád, žiadna odpoveď dlhšia
než ~15 s reči.

---

## 3. Fáza 2 — Filler hlášky a barge-in

1. `outputs/fillers.py` — pri prvom spustení vygeneruje cez TTS 8–12 krátkych
   hlášok zo zoznamu v config.yaml do `fillers/*.wav`. Ak súbory existujú,
   negeneruje nič.
   Príklady: „moment, chum", „nechaj ma pozrieť", „hmm", „počkaj", „idem na to".
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

1. `mod/mirana_state/init.lua` — každé 2 s zapíš do `%TEMP%/mirana_state.json`:
   HP %, level, street cred, eddies, quest, distrikt, in_combat, in_vehicle.
   Začni s HP + lokácia + quest.
2. `inputs/game_state.py` — čítaj JSON (mtime check), generuj eventy:
   `hp_low` (<25 %), `hp_critical` (<10 %), `district_change`, `level_up`,
   `quest_completed`, `combat_start/end`.
3. Do každého promptu pridaj jeden riadok kontextu:
   `HP 87% | Watson/Kabuki | lvl 23 | quest: Ghost Town | combat: nie`
4. Proaktívne hlášky: max 1 / 5 min, nikdy počas SPEAKING. `hp_critical` má
   výnimku z cooldownu.
5. Keď mod nebeží, Mirana funguje ďalej bez kontextu.

**Akceptácia:** „Mirana, čo mám robiť?" → odpoveď vychádza z aktívneho questu
a lokácie bez toho, aby ich Erik povedal.

---

## 6. Fáza 5 — Kick chat

Pred písaním si načítaj aktuálnu dokumentáciu na docs.kick.com. Modul drž
izolovaný — jeho pád nesmie ovplyvniť zvyšok.

1. `inputs/kick_chat.py` — pripojenie, parsovanie správ a badges odosielateľa.
2. Sub / mod / OG → `!mira <otázka>` ide do fronty. Nesub → ignoruj, približne
   každú desiatu krátko odmietni v charaktere.
3. Fronta max 10. Cooldown 30 s globálne, 3 min na diváka. Orchestrátor berie
   z fronty len v stave IDLE a mimo combatu.
4. Nick pred TTS prečisti (čísla, symboly, `xX...Xx`).

---

## 7. Fáza 6 — Audio routing + DSP

1. `voice.py` prehráva do VoiceMeeter Input na hernom PC.
2. VST reťaz na tom kanáli: bitcrusher → ring mod → EQ (HP 180 Hz, LP 5200 Hz)
   → echo → limiter.
3. VBAN send `VoiceToStream` → notebook → OBS ako samostatná audio stopa.

---

## 8. Fáza 7 — Hardening

1. `core/budget.py` — počítaj tokeny a odhadovanú cenu za deň.
   `limits.daily_usd_cap: 1.00`. Pri dosiahnutí prestaň volať API, Mirana povie
   hlášku v charaktere, zaloguj varovanie. Reset o polnoci.
2. `core/safety.py` — výstupný filter pred TTS: blokuj obsah ohrozujúci Kick TOS
   a osobné údaje divákov. Pri zachytení preskoč vetu.
3. `run.py` — supervisor: sleduj heartbeat, pri páde alebo zamrznutí (>60 s)
   reštartuj. Max 5 reštartov za hodinu.
4. Panic mute na F11 — okamžite umlčí Miranu a pozastaví spracovanie.
5. Log per session.
6. Pred prvým ostrým streamom 8-hodinový suchý beh. Sleduj RAM a počet API chýb.

---

## 9. Náklady

Sadzby (september 2026): Claude Sonnet 5 $2/$10 za milión tokenov, cache hit
10 % ceny inputu, Whisper $0.006/min, Azure TTS Free F0 500K znakov/mesiac.

Pri 800 výmenách na 100 hodín streamu: **~2,40 USD**. Limit je 10 € / 100 h.

Rozpočet rozbije: Opus namiesto Sonnetu, pamäť nad 8 výmen, nezacachovaná
persona, alebo bug v slučke.

---

## 10. Práca s Claude Code

1. Jeden prompt = jeden krok: „Postav len `inputs/ptt.py` podľa sekcie 2 kroku 1.
   Nič iné."
2. Po každom kroku to Erik reálne spustí a overí — Claude Code nepočuje reproduktory.
3. Commit po každom funkčnom kroku, tag po fáze (`v0.1-core`, `v0.2-fillers`…).
4. Pri páde vkladaj celý traceback a log, nie parafrázu.
