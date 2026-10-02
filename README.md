# MIRANA

Hlasová AI parťáčka pre stream Cyberpunku 2077 na Twitchi. Držíš bočné tlačidlo myši, povieš otázku po slovensky,
pustíš, a Mirana odpovie hlasom aj na HUD v OBS. Štýl Friday z Iron Mana: pokojná, bystrá, so suchým humorom,
občas zanadávaná, bez spoilerov. Vidí do hry cez CET mod, pozrie sa na obrazovku, hľadá vo wiki, pamätá si
streamy aj divákov a pri dôležitých udalostiach sa ozve sama.

```
PTT ─► mikrofón ─► Whisper (lokálne, GPU) ─► Claude Sonnet 5.5 (streaming) ─► po vetách ─► Azure TTS ─► efekty ─► výstup
                     [HRA] [WIKI] [OBRAZOVKA] [CHAT] [PAMÄŤ] ─┘                          └─► HUD (OBS Browser Source)
```

## Ovládanie

| tlačidlo (predvolené) | čo robí |
|---|---|
| **zadné bočné tlačidlo myši** (drž) | nahrávanie otázky; pustenie = odoslanie; počas odpovede ju preruší |
| **predné bočné tlačidlo myši** (ťuk) | značka na strih: čas vo VOD-ke do `logs/strih-<dátum>.md` |
| **F11** | panic mute: okamžite stíchne a ignoruje otázky; znova = späť |

Mení sa v Nastaveniach → Zvuk. Otázka sa dá aj napísať do ovládacieho okna.

## Inštalácia

Windows 11, Python 3.12, NVIDIA GPU (Whisper na CUDA; toolkit netreba, stačia pip balíky).

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
venv\Scripts\python install_shortcut.py
```

Do `.env` doplň `ANTHROPIC_API_KEY` (+ `ANTHROPIC_WORKSPACE_ID`, ak kľúč nie je vytvorený vo workspace),
`AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`; `OPENAI_API_KEY` len pri `stt.provider: api`.
Pre telemetriu nainštaluj [Cyber Engine Tweaks](https://github.com/maximegmd/CyberEngineTweaks/releases) a v okne
Nastavenia → Hra **Nainštalovať mod**.

## Spustenie

**Ikona MIRANA** otvorí ovládacie okno, ktoré skontroluje nastavenia, kľúče, zvuk, grafiku a hru (problémy vypíše
s „⚠“) a Miranu spustí. Zatvorenie okna ju vypne. Bez okna: `start.bat`. Oboje ide cez `run.py`, ktorý Miranu pri
páde alebo zamrznutí reštartuje. Prvý štart stiahne Whisper model (~1,5 GB) a vygeneruje filler hlášky.

**Dual PC stream:** Mirana hrá na predvolený výstup Windows (HDMI → strihová karta → notebook s OBS), takže je
v streame bez Voicemeeteru. HUD v OBS na notebooku: Browser Source `http://<IP herného PC>:8080`.

## Čo vie

- **hra** (CET mod): zdravie, quest, príbeh, postava, výbava, cieľ pod zameriavačom, polícia, auto; sama sa ozve pri smrti, kritickom HP, leveli…
- **wiki**: pri „kto je X?“ článok z Cyberpunk Fandom wiki ešte pred odpoveďou
- **obrazovka**: pri „čo je toto?“ snímka len okna hry
- **pamäť**: postup v hre, streamy, fakty o tebe, diváci z chatu („zabudni Kuba“)
- **chat**: číta Twitch chat, komentuje ho len na otázku
- **momenty na strih**, štatistiky streamu, pripomienka po 10 min ticha, poznámky „zapíš si do logu…“
- **HUD** s efektmi (databáza, sken, level, smrť, polícia), test efektov v Nastaveniach

Podrobnosti: [docs/FUNKCIE.md](docs/FUNKCIE.md).

## Náklady

4-hodinový stream so Sonnet 5.5 low ~**$1** (Claude), zhrnutie do pamäte ~2–5 c. Whisper beží lokálne, Azure TTS
je vo free tieri. Denný strop `limits.daily_usd_cap` (predvolene $5). Odozva: mimo hry ~3–4 s, v hre ~5–6 s
(hra vyťažuje GPU); pauzu zakryje filler na HUD.

## Pre vývoj

```bat
venv\Scripts\pip install -r requirements-dev.txt
venv\Scripts\python -m pytest
```

Testy nehrajú zvuk ani nevolajú API. Stavba programu: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
zmeny: [CHANGELOG.md](CHANGELOG.md), plán a stav: [docs/SPEC.md](docs/SPEC.md), [docs/PROGRESS.md](docs/PROGRESS.md).
