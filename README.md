# MIRANA

Hlasová AI parťáčka pre stream Cyberpunku 2077 na Kicku. Držíš F12, povieš otázku po slovensky, pustíš,
a Mirana odpovie hlasom do slúchadiel aj na HUD v OBS. Štýl Friday z Iron Mana: pokojná, bystrá,
s ľahkým suchým humorom, bez spoilerov.

```
F12 ─► mikrofón ─► Whisper (lokálne, GPU) ─► Claude Opus 5.5 (streaming) ─► po vetách ─► Azure TTS ─► slúchadlá / Voicemeeter
                                                                      └─► HUD (WebSocket, OBS Browser Source)
```

## Ovládanie

| kláves | čo robí |
|---|---|
| **F12** (drž) | nahrávanie otázky; pustenie = odoslanie |
| **F12** počas odpovede | preruší ju a počúva novú otázku |
| **F11** | panic mute: okamžite stíchne a ignoruje F12; znova F11 = späť |

HUD: `http://localhost:8080` (na notebooku v OBS: `http://IP-herného-PC:8080`).

## Inštalácia

Windows 11, Python 3.12, NVIDIA GPU (Whisper beží na CUDA; CUDA toolkit netreba, stačia pip balíky).

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Do `.env` doplň kľúče: `ANTHROPIC_API_KEY` (+ `ANTHROPIC_WORKSPACE_ID`, ak kľúč nie je vytvorený vo workspace),
`AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`. `OPENAI_API_KEY` treba len pri `stt.provider: api`.

Zvukové zariadenia nastav v `config.yaml` (`audio.input_device`, `audio.output_device`). Presné názvy
vypíše `venv\Scripts\python -m sounddevice`; odporúčaný tvar je `"názov, Windows WASAPI"`.

## Spustenie

**Ikona MIRANA na ploche alebo v Štart menu.** Otvorí ovládacie okno, ktoré Miranu samo spustí:

- stav (STANDBY / POČÚVAM / SPRACOVÁVAM / HOVORÍ / STLMENÁ), dnešná útrata so stropom,
- priebeh rozhovoru (tvoja otázka, Miranina odpoveď),
- tlačidlá **Vypnúť/Spustiť**, **Stlmiť (F11)**, **HUD**, **Logy**, **Nastavenia**.

**Nastavenia** (bez editovania súborov): mikrofón a výstup s testom, klávesy, hlas s ukážkou (rýchlosť, výška,
fonetika), model a effort, denný strop, pamäť, prepis reči, filler hlášky, HUD, bezpečnostný filter a persona.
„Uložiť a reštartovať“ ich hneď použije. Pred každým uložením sa zálohuje `data/config.yaml.bak` a `data/persona.md.bak`.

Zatvorenie okna Miranu vypne. Ikonu vytvoríš raz príkazom `venv\Scripts\python install_shortcut.py`.

Bez okna: **`start.bat`** (konzola s logom). Oboje spúšťa `run.py` (supervisor), ktorý Miranu pri páde
alebo zamrznutí reštartuje (najviac 5× za hodinu). Druhá inštancia sa nespustí.

Prvý štart stiahne Whisper model (~1,5 GB) a vygeneruje filler hlášky do `fillers/`.

## Telemetria z hry (CET)

Mirana vie z hry:

- **stav**: HP, nabitia liečenia a granátov, náboje v zásobníku, RAM, peniaze, či bojuješ, či si v scéne
- **svet**: štvrť, čas v hre, počasie, polícia (hviezdy)
- **quest**: sledovaný quest a cieľ; **príbeh**: dokončené hlavné questy (kam až si došiel, pre spoilery)
- **postava**: level, street cred, atribúty, nerozdelené body, voľná kapacita kybervýzbroje
- **výbava**: OS (cyberdeck/Sandevistan/Berserk), zbrane v slotoch, zbraň v ruke, brnenie
- **cieľ pod zameriavačom**: meno, nepriateľ/civil/boss, úroveň, zdravie
- **auto**: vozidlo, rýchlosť, rádio a skladba

Sama sa ozve pri kritickom HP, smrti, level-upe, novej štvrti, novom a dokončenom queste a keď ťa začne
hľadať polícia (najviac raz za 5 min, kritické HP hneď, počas rozhovorov a cutscén mlčí). Názvy z hry
prídu v jazyku hry (napr. po česky) a Mirana ich tak aj povie, reč okolo nich ostáva slovenská.

1. Nainštaluj [Cyber Engine Tweaks](https://github.com/maximegmd/CyberEngineTweaks/releases) (rozbaliť do priečinka hry).
2. Okno MIRANA → Nastavenia → **Hra** → **Nainštalovať mod** (skopíruje `mod/mirana_state` do CET).
3. Spusti hru. V hlavnom okne sa ukáže riadok „Hra: …". Ak niektorý údaj po patchi hry prestane chodiť,
   v `state.json` modu je v poli `errors`, ktorý (ostatné idú ďalej).

Mod zapisuje každé 2 s `state.json` do svojho priečinka; do promptu ide krátky slovenský riadok `[HRA]`,
nikdy surový JSON (v teste model zo surového JSON zle prepočítal HP).

Bez hry: `venv\Scripts\python tools\simulate_game.py` zapisuje falošný stav (jazda, cutscéna, boj, polícia, nízke HP, level, quest)
do `data/sim_state.json`; Miranu vtedy spusti s `set MIRANA_GAME_STATE_PATH=C:\mirana-v2\data\sim_state.json`.

## Konfigurácia

Všetko sa dá nastaviť v okne (Nastavenia) alebo priamo v `config.yaml`:

- `llm.model`: `claude-opus-5-5` (presnejší) alebo `claude-opus-5` (o ~1 s rýchlejší, podobná cena)
- `limits.daily_usd_cap`: tvrdý denný strop na LLM (predvolene $5)
- `fillers.lines`: hlášky, ktoré zakryjú pauzu pred odpoveďou (po zmene zmaž `fillers/*.wav`)
- `tts.voice`: Azure hlas; `phonetics.yaml`: ako vysloviť anglické názvy z hry
- `safety.blocked_words`: vety s týmito slovami sa nevyslovia

Osobnosť Mirany je v `persona.md`.

## Náklady

Merané na 4-hodinovom streame so 160 otázkami: **~$1,30** (Claude). Whisper beží lokálne a Azure TTS
je vo free tieri (500 000 znakov/mesiac, ~15 streamov). Podrobnosti v [SPEC.md](SPEC.md) § Náklady.

## Logy

- `logs/mirana-<čas>.log`: celý beh session
- `logs/rozhovor-<čas>.jsonl`: každá otázka s odpoveďou, časmi a cenou
- `logs/supervisor.log`: reštarty
- `data/budget.json`: dnešná útrata

## Štruktúra

| súbor | úloha |
|---|---|
| `gui.py`, `gui_settings.py` | ovládacie okno a nastavenia (ikona na ploche) |
| `core/settings.py` | zápis config.yaml a persona.md so zachovaním komentárov |
| `main.py` | stavový automat, poradie udalostí, pamäť |
| `run.py` | supervisor (reštart, heartbeat) |
| `core/brain.py` | Whisper → Claude, streaming po vetách |
| `core/stt.py` | lokálny faster-whisper alebo Whisper API |
| `core/budget.py`, `core/safety.py`, `core/session.py` | strop nákladov, filter, logy a zámok |
| `inputs/ptt.py` | F12 / F11 a nahrávanie |
| `inputs/game_state.py`, `mod/mirana_state/init.lua` | telemetria z hry (CET mod), udalosti, riadok [HRA] |
| `tools/simulate_game.py` | simulátor hry na testovanie bez Cyberpunku |
| `outputs/speaker.py`, `outputs/voice.py` | TTS po vetách, prehrávanie, fonetika |
| `outputs/fillers.py`, `outputs/overlay.py` | filler hlášky, HUD server |
| `overlay/index.html` | HUD |

Plán a stav: [SPEC.md](SPEC.md), [PROGRESS.md](PROGRESS.md), [POSTUP.md](POSTUP.md).
