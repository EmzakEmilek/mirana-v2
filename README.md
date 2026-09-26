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

Dvojklik na **`start.bat`**. Spustí `run.py` (supervisor), ktorý Miranu pri páde alebo zamrznutí
reštartuje (najviac 5× za hodinu). Druhá inštancia sa nespustí.

Prvý štart stiahne Whisper model (~1,5 GB) a vygeneruje filler hlášky do `fillers/`.

## Konfigurácia

Všetko je v `config.yaml`, kód netreba meniť:

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
| `main.py` | stavový automat, poradie udalostí, pamäť |
| `run.py` | supervisor (reštart, heartbeat) |
| `core/brain.py` | Whisper → Claude, streaming po vetách |
| `core/stt.py` | lokálny faster-whisper alebo Whisper API |
| `core/budget.py`, `core/safety.py`, `core/session.py` | strop nákladov, filter, logy a zámok |
| `inputs/ptt.py` | F12 / F11 a nahrávanie |
| `outputs/speaker.py`, `outputs/voice.py` | TTS po vetách, prehrávanie, fonetika |
| `outputs/fillers.py`, `outputs/overlay.py` | filler hlášky, HUD server |
| `overlay/index.html` | HUD |

Plán a stav: [SPEC.md](SPEC.md), [PROGRESS.md](PROGRESS.md), [POSTUP.md](POSTUP.md).
