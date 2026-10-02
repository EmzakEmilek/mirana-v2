# Architektúra Mirany

Ako do seba zapadajú časti programu a kam pridať novú funkciu. Používateľský popis je v [README](../README.md)
a [FUNKCIE.md](FUNKCIE.md).

## Procesy

```
ikona MIRANA ─► gui.py (ui/control.py) ── spustí ──► run.py (supervisor) ──► main.py ─► mirana/app.py
     ovládacie okno ◄──────── WebSocket :8080 (protokol) ────────► HUD server (mirana/outputs/overlay.py)
                                                                       ▲
OBS Browser Source (notebook) ── HTTP + WebSocket :8080 ───────────────┘
```

- **Ovládacie okno** (`ui/control.py`) spustí supervisor, pripojí sa na WebSocket ako ďalší klient HUD-u a
  posiela príkazy (stlmiť, vypnúť, otázka, hlasitosť, test HUD, úprava pamäte). Pri otvorení spraví
  diagnostiku (`mirana/diagnostics.py`) a aktualizuje mod v hre.
- **Supervisor** (`run.py`) reštartuje Miranu pri páde alebo zamrznutí (heartbeat `data/heartbeat`).
- **Mirana** (`main.py` → `mirana/app.py`) je jeden proces s vláknami; druhú inštanciu nepustí zámok.

## Jadro a funkcie

`mirana/app.py` (trieda `Mirana`) je **jadro**: fronta udalostí, stavový automat a otázky (Turn).
O poradí, prerušení, fallbackoch a krátkej pamäti rozhoduje len hlavná slučka.

```
IDLE ─PTT─► LISTENING ─pustenie─► PROCESSING ─prvá veta─► SPEAKING ─dohovorí─► IDLE
  ▲            │ barge-in (PTT počas PROCESSING/SPEAKING) zruší Turn a počúva znova
  └── panic mute (F11) z ktoréhokoľvek stavu; písaná otázka preruší rozbehnutú odpoveď
```

Všetko ostatné sú **funkcie** v `mirana/features/` (trieda `Feature`). Jadro volá ich metódy a chyba
jednej funkcie sa len zaloguje:

| funkcia | súbor | čo robí |
|---|---|---|
| `HighlightsFeature` | `highlights.py` | značka na strih, zápis udalostí z hry, riadok `[STREAM]` |
| `Hud` | `hud.py` | telemetria a efekty na HUD, test efektov z Nastavení |
| `LongTermFeature` | `longterm.py` | `[PAMÄŤ]`, `[DIVÁCI]`, „zabudni“, zhrnutie modelom, úpravy z okna |
| `WikiFeature` | `wiki.py` | predhľadanie článku `[WIKI …]` (nástroj `wiki` pre model je v `llm/brain.py`) |
| `VisionFeature` | `vision.py` | snímka okna hry `[OBRAZOVKA]` pri „čo je toto?“ |
| `IdleNudge` | `idle.py` | pripomienka po tichu |
| `Notes` | `notes.py` | „zapíš si do logu…“ → `logs/poznamky.md` |
| `LogArchive` | `archive.py` | staré logy do `logs/archive/<mesiac>.zip` |

Metódy funkcie (všetky voliteľné): `start`, `on_question(turn)`, `context(turn)`, `on_answer(turn, text)`,
`on_game_event(name, snap, text) -> text`, `on_snapshot(snap)`, `on_chat(msg)`, `on_command(cmd, text) -> bool`,
`tick` (každých 5 s ticha), `shutdown`. **Nová funkcia** = nový súbor v `mirana/features/` + jeden riadok
v `app.FEATURES` + test.

## Jedna otázka (Turn)

1. PTT → `Recording` do fronty → `_start_turn("voice")` → worker vlákno: Whisper (`llm/stt.py`).
   Písaná otázka: `Typed` → `_start_turn("typed")`. Udalosť z hry / pripomienka: `start_turn("game" | "idle")`.
2. `on_question` (poznámky, reset pripomienky), kontrola rozpočtu.
3. Kontext: jadro pridá `[HRA]` a `[CHAT]`, funkcie cez `context(turn)` ďalšie riadky. Poradie v správe je pevné
   (`turn.CONTEXT_ORDER`: HRA, STREAM, WIKI, OBRAZOVKA, CHAT, DIVÁCI, SYSTÉM), za ním `[ERIK] otázka`.
4. `Brain.ask_stream` (`llm/brain.py`): Claude so streamovaním, prompt cache (persona + `[PAMÄŤ]` + história),
   nástroj wiki. Hotové vety idú hneď do `Speaker` (`outputs/speaker.py`: syntéza Azure a prehrávanie vo
   vlastných vláknach, HUD píše v tempe hlasu).
5. `Answered` → zápis do `logs/rozhovor-<čas>.jsonl` (zdroj, otázka, kontext, časy, cena) → `Spoken` →
   do krátkej pamäte (`memory.py`) ide len otázka a to, čo Erik naozaj počul (pri prerušení len vyslovené vety).

Udalosti vo fronte sú dátové triedy v `mirana/events.py`: `Recording`, `Typed`, `GameEvent`, `Answered`,
`Spoken`, `Interrupted`, `Silent`, `Fallback`, `Quit`.

## Vlákna

| vlákno | čo v ňom beží |
|---|---|
| hlavná slučka | fronta udalostí, stavy, pamäť, `tick` funkcií |
| `turn-*` (worker) | prepis, kontext funkcií, stream modelu |
| `speaker-tts`, `speaker-play` | syntéza viet, prehrávanie |
| pynput | PTT, panic mute, značka (len krátke akcie, ťažká práca ide inam) |
| `game-state` | čítanie `state.json` z modu, udalosti z hry, `on_snapshot` |
| `twitch-chat` | IRC WebSocket (len čítanie), `on_chat` |
| `overlay` | asyncio server HUD-u a príkazov |
| `wiki-index`, `longterm`, `stream-clock`, `log-archive` | pozadie funkcií |

Stav zdieľaný medzi vláknami (`state`, `_gen`, `_turn`) chráni `Mirana._lock`.

## Protokol HUD / okno

`mirana/protocol.py` je jediné miesto s typmi správ a ich poľami (`EVENTS`), so zoznamom, kto ich spracúva
(`HUD` = `overlay/index.html`, `GUI` = `ui/control.py`), a s príkazmi z okna (`COMMANDS`). Príkazy sa berú
len z localhostu a bez hlavičky Origin (nie z prehliadača). Test kontroluje, že každý typ má príjemcu.

## Nastavenia

- `mirana/schema.py`: **každé nastavenie raz** — predvolená hodnota, typ, rozsah, voľby, popis a záložka pre okno.
- `mirana/config.py` → `load_config()`: `config.yaml` doplnený predvolenými hodnotami a skontrolovaný; zlá hodnota
  sa nahradí predvolenou a problém sa ukáže v diagnostike okna a v logu (Mirana nespadne na preklepe).
- `ui/settings_window.py`: políčka sa skladajú zo schémy; vlastné časti (testy zvuku, ukážka hlasu, mod, test HUD,
  pamäť, persona) sú metódy `_block_<názov>`. Ukladá len zmenené hodnoty cez ruamel (komentáre ostávajú).

## Súbory a dáta

| cesta | obsah | zapisuje |
|---|---|---|
| `config.yaml`, `persona.md` | nastavenia, osobnosť | okno Nastavenia (záloha v `data/*.bak`) |
| `data/memory.json` | dlhodobá pamäť | Mirana; okno cez príkaz `memory_edit` (keď Mirana nebeží, priamo) |
| `data/budget.json`, `data/stream_stats.json` | dnešná útrata, štatistiky dňa | Mirana (`store.DailyJson`) |
| `data/wiki_titles.json` | index názvov článkov wiki (obnova raz týždenne) | Mirana |
| `logs/mirana-*.log`, `logs/rozhovor-*.jsonl`, `logs/chat-*.jsonl` | beh, rozhovor, chat | Mirana |
| `logs/strih-*.md`, `logs/poznamky.md` | momenty na strih, poznámky | Mirana |
| `logs/archive/<rok-mesiac>.zip` | logy staršie ako `logging.archive_after_days` | Mirana pri štarte |

JSON súbory sa zapisujú atomicky (`mirana/store.py`: dočasný súbor + premenovanie), takže pád ani výpadok
prúdu nenechá napoly zapísaný súbor.

## Testy

```bat
venv\Scripts\pip install -r requirements-dev.txt
venv\Scripts\python -m pytest
```

`tests/` — bez siete, mikrofónu a modelu, nikdy nehrajú zvuk (`MIRANA_NO_AUDIO=1` v `conftest.py`: prehrávanie
len odmeria čas vety). Orchestrácia sa testuje so skutočným jadrom, Speakerom, pamäťou a protokolom a s náhradami
v `tests/fakes.py` (Brain, Voice, PTT, hra, chat). `test_intents.py` obsahuje skutočné otázky zo streamov —
nové kľúčové slovo pridaj aj s príkladmi.

## Kľúčové slová

`mirana/intents.py`: snímka obrazovky, „zabudni“, poznámka do logu, otázka na stream, lore otázka.
Regexy počítajú s prepisom reči bez diakritiky a s chybami („čuje toto“ = „čo je toto“).
