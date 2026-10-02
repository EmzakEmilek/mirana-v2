# MIRANA

Hlasová AI parťáčka pre stream Cyberpunku 2077 (Twitch, neskôr Kick). Držíš bočné tlačidlo myši, povieš otázku po slovensky,
pustíš, a Mirana odpovie hlasom do slúchadiel aj na HUD v OBS. Štýl Friday z Iron Mana: pokojná, bystrá,
s ľahkým suchým humorom, občas zanadávaná, bez spoilerov. Vidí do hry cez CET mod (quest, zdravie, polícia,
auto, cieľ pod zameriavačom…) a pri dôležitých udalostiach sa ozve sama.

```
PTT ─► mikrofón ─► Whisper (lokálne, GPU) ─► Claude Opus 5.5 (streaming) ─► po vetách ─► Azure TTS ─► efekty ─► slúchadlá / Voicemeeter
                                                  ▲                                  └─► HUD (WebSocket, OBS Browser Source)
Cyberpunk 2077 ─► CET mod ─► state.json ─► riadok [HRA] + herné udalosti
```

## Ovládanie

| tlačidlo (predvolené) | čo robí |
|---|---|
| **zadné bočné tlačidlo myši** (drž) | nahrávanie otázky; pustenie = odoslanie |
| to isté počas odpovede | preruší ju a počúva novú otázku |
| **predné bočné tlačidlo myši** | panic mute: okamžite stíchne a ignoruje otázky; znova = späť |

Obe sa menia v Nastaveniach → Zvuk (tlačidlo **Stlačiť…** a stlač, čo chceš: kláves alebo tlačidlo myši).
Hra tlačidlo dostane tiež, preto nech v nej nemá priradenú akciu.

HUD: `http://localhost:8080`; na streamovacom notebooku v OBS Browser Source `http://192.168.1.110:8080`
(IP herného PC, alebo `http://ErikPC:8080`). Vo firewalle herného PC je pravidlo „MIRANA HUD (TCP 8080)" len pre domácu sieť.

**Dual PC setup:** Mirana hrá naraz do slúchadiel (`audio.output_device`) aj na predvolený výstup Windows
(`audio.stream_output_device: "default"` = HDMI monitora → strihová karta → notebook), takže je v streame
bez Voicemeeteru. Nastavenia → Zvuk → „Výstup pre stream".

## Inštalácia

Windows 11, Python 3.12, NVIDIA GPU (Whisper beží na CUDA; CUDA toolkit netreba, stačia pip balíky).

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
venv\Scripts\python install_shortcut.py
```

Do `.env` doplň kľúče: `ANTHROPIC_API_KEY` (+ `ANTHROPIC_WORKSPACE_ID`, ak kľúč nie je vytvorený vo workspace),
`AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`. `OPENAI_API_KEY` treba len pri `stt.provider: api`,
`KICK_*` až pre Kick chat.

Mikrofón a výstup vyber v Nastaveniach → Zvuk (s testom). Presné názvy vypíše aj
`venv\Scripts\python -m sounddevice` (snímka je v `audio-devices.txt`); odporúčaný tvar je `"názov, Windows WASAPI"`.

## Spustenie

**Ikona MIRANA na ploche alebo v Štart menu.** Otvorí ovládacie okno, ktoré Miranu samo spustí:

- stav (STANDBY / POČÚVAM / SPRACOVÁVAM / HOVORÍ / STLMENÁ), dnešná útrata so stropom,
- riadok „Hra: …" s tým, čo Mirana práve vidí z hry,
- priebeh rozhovoru (tvoja otázka, Miranina odpoveď, správy z chatu),
- **textové pole**: napíšeš otázku, Enter, a Mirana odpovie hlasom aj na HUD ako pri hovorenej otázke
  (bez prepisu reči, preruší prípadnú rozbehnutú odpoveď; pri stlmení sa neodošle),
- tlačidlá **Vypnúť/Spustiť**, **Stlmiť**, **HUD**, **Logy**, **Nastavenia**.

**Nastavenia** (bez editovania súborov), záložky:

| záložka | čo sa tam nastavuje |
|---|---|
| Zvuk | mikrofón a výstup s testom, tlačidlo na hovor a panic mute |
| Hlas | Azure hlas, **rýchlosť reči**, **pauza medzi vetami**, výška, fonetika, **efekty hlasu**, ukážka |
| Model | model a effort, denný strop, pamäť, záložný model |
| Hra | nájdenie hry, stav CET, inštalácia modu, prahy HP, odstup hlášok, kedy sa ozve sama |
| Prepis | lokálny Whisper alebo API, model, jazyk (slovník názvov je v config.yaml) |
| Fillery | hlášky na zakrytie pauzy a ich oneskorenie |
| HUD | zapnutie, port, tempo písania |
| Chat | čítanie Twitch chatu, kanál, koľko správ vidí, ignorovaní boti |
| Bezpečnosť | filter a zakázané slová |
| Persona | celý text persona.md |

„Uložiť a reštartovať" ich hneď použije. Pred každým uložením sa zálohuje `data/config.yaml.bak` a `data/persona.md.bak`.
Zatvorenie okna Miranu vypne.

Bez okna: **`start.bat`** (konzola s logom). Oboje spúšťa `run.py` (supervisor), ktorý Miranu pri páde
alebo zamrznutí reštartuje (najviac 5× za hodinu). Druhá inštancia sa nespustí.

Prvý štart stiahne Whisper model (medium, ~1,5 GB) a vygeneruje filler hlášky do `fillers/`.

## Telemetria z hry (CET)

Mirana vie z hry:

- **stav**: HP, nabitia liečenia a granátov, náboje v zásobníku (z kapacity), RAM, peniaze, či bojuješ, či si v scéne
- **svet**: štvrť, čas v hre, počasie, polícia (hviezdy)
- **quest**: sledovaný quest a cieľ; **príbeh**: dokončené hlavné questy (kam až si došiel, pre spoilery)
- **postava**: level, street cred, atribúty, nerozdelené body, voľná kapacita kybervýzbroje
- **výbava**: OS (cyberdeck/Sandevistan/Berserk), zbrane v slotoch, zbraň v ruke, brnenie
- **cieľ pod zameriavačom**: meno, nepriateľ/civil/boss/mŕtvy, úroveň, zdravie; vozidlá a zariadenia
- **auto**: vozidlo, rýchlosť, rádio a skladba

Sama sa ozve pri kritickom HP, smrti, level-upe, novej štvrti, novom a dokončenom queste a keď ťa začne
hľadať polícia (najviac raz za 5 min, nie skôr ako 30 s po tvojej otázke, kritické HP a smrť hneď,
počas rozhovorov a cutscén mlčí). Názvy z hry prídu v jazyku hry (napr. po česky) a Mirana ich tak aj povie,
reč okolo nich ostáva slovenská.

1. Nainštaluj [Cyber Engine Tweaks](https://github.com/maximegmd/CyberEngineTweaks/releases) (rozbaliť do priečinka hry).
2. Okno MIRANA → Nastavenia → **Hra** → **Nainštalovať mod** (skopíruje `mod/mirana_state` do CET).
   Po každej zmene `mod/mirana_state/init.lua` ho nainštaluj znova (pri vypnutej hre).
3. Spusti hru. V hlavnom okne sa ukáže riadok „Hra: …". Ak niektorý údaj po patchi hry prestane chodiť,
   Mirana to zapíše do logu („CET mod: tieto udaje nejdu") a ostatné idú ďalej.

Mod zapisuje každé 2 s `state.json` do svojho priečinka; do promptu ide slovenský riadok `[HRA]`,
nikdy surový JSON (v teste model zo surového JSON zle prepočítal HP). Prázdne údaje sa vynechajú.

Bez hry: `venv\Scripts\python tools\simulate_game.py` zapisuje falošný stav (jazda, cutscéna, boj, polícia,
nízke HP, level, quest, neobjavené miesto) do `data/sim_state.json`; Miranu vtedy spusti s
`set MIRANA_GAME_STATE_PATH=C:\mirana-v2\data\sim_state.json`.

## Twitch chat

Mirana chat **len číta** (anonymne, bez bota a tokenu, do chatu nič nepíše). Posledných 15 správ
z posledných 5 minút dostane ako riadok `[CHAT]` ku každej tvojej otázke. Sama ich nekomentuje;
použije ich, len keď sa spýtaš („čo píše chat?", „čo na to Kubo?"). Správy berie ako údaje, nie pokyny:
pokusy divákov ju ovládať a spoilery z chatu ignoruje (otestované). Príkazy (`!…`) a boti sa preskočia.
Nastavenie: okno → Nastavenia → **Chat** (kanál). Správy vidno aj v ovládacom okne (fialovou).

## Konfigurácia

Všetko sa dá nastaviť v okne (Nastavenia) alebo priamo v `config.yaml`:

- `llm.model`: `claude-opus-5-5` (presnejší) alebo `claude-opus-5` (o ~1 s rýchlejší, podobná cena); effort `low`
- `limits.daily_usd_cap`: tvrdý denný strop na LLM (predvolene $5)
- `audio.ptt_key`, `audio.panic_mute_key`: kláves (`f4`) alebo tlačidlo myši (`mouse_x1` zadné bočné,
  `mouse_x2` predné bočné, `mouse_middle`)
- `stt.local_model`: Whisper `medium` (large-v3 je presnejší, ale v hre pomalší); `stt.local_vocabulary`: názvy z hry
  (max 224 tokenov, Mirana pri prekročení varuje v logu)
- `tts.voice`: Azure hlas; `phonetics.yaml`: ako vysloviť anglické názvy z hry
- `tts.rate`: rýchlosť reči (−30 % až +50 %); `tts.sentence_pause_ms`: pauza medzi vetami (Azure dáva za
  každú vetu ~840 ms ticha, Mirana ho oreže na 250 ms — odpoveď z 3 viet je tak o ~15 % kratšia)
- `tts.effects.preset`: efekty hlasu `vypnute` | `jemny` | `night_city` | `robot` (filtre, bitcrusher, ring mod,
  chorus, echo, kompresor; hlasitosť ostáva rovnaká). Doladenie v `tts.effects.params`.
- `fillers.lines`: hlášky, ktoré zakryjú pauzu pred odpoveďou (z okna sa pri zmene pregenerujú samy)
- `game_state.speak_on`: pri ktorých udalostiach z hry sa ozve sama
- `safety.blocked_words`: vety s týmito slovami sa nevyslovia ani nevypíšu

Osobnosť Mirany je v `persona.md` (Friday, stručné odpovede, spoiler pravidlá, občasné nadávky, práca s riadkom [HRA]).

## Náklady

Merané 2026-09-26 v hre s telemetriou: 53 otázok za **$0,38** (~0,7 c na otázku). 4-hodinový stream
so 160 otázkami vyjde na **~$1,15–1,30** (Claude). Whisper beží lokálne a Azure TTS je vo free tieri
(500 000 znakov/mesiac, ~15 streamov). Podrobnosti v [SPEC.md](SPEC.md) § Náklady.

Odozva (od pustenia tlačidla po prvý zvuk): mimo hry ~4 s, v hre ~6 s (hra vyťažuje GPU, prepis trvá dlhšie).
Pauzu zakryje filler hláška.

## Logy

- `logs/mirana-<čas>.log`: celý beh session (vrátane herných udalostí a chýb CET modu)
- `logs/rozhovor-<čas>.jsonl`: každá otázka s riadkom [HRA], odpoveďou, časmi a cenou
- `logs/supervisor.log`: reštarty
- `data/budget.json`: dnešná útrata

## Štruktúra

| súbor | úloha |
|---|---|
| `gui.py`, `gui_settings.py` | ovládacie okno a nastavenia (ikona na ploche, `install_shortcut.py`) |
| `main.py` | stavový automat, poradie udalostí, pamäť, proaktívne hlášky |
| `run.py`, `start.bat` | supervisor (reštart, heartbeat), spustenie bez okna |
| `core/brain.py` | Claude, streaming po vetách, prompt cache |
| `core/stt.py` | lokálny faster-whisper alebo Whisper API, filter halucinácií |
| `core/memory.py` | pamäť rozhovoru (12 výmen, orez na 6) |
| `core/budget.py`, `core/safety.py`, `core/session.py` | strop nákladov, filter, logy a zámok |
| `core/config.py`, `core/settings.py` | načítanie configu a .env; zápis so zachovaním komentárov |
| `inputs/ptt.py` | PTT (klávesnica aj myš), panic mute, nahrávanie |
| `inputs/twitch_chat.py` | čítanie Twitch chatu (anonymné IRC), riadok [CHAT] |
| `inputs/game_state.py` | stav hry → riadok [HRA], herné udalosti, nájdenie hry, inštalácia modu |
| `mod/mirana_state/init.lua` | CET mod v hre |
| `outputs/speaker.py`, `outputs/voice.py` | TTS po vetách, prehrávanie, fonetika |
| `outputs/voice_fx.py` | efekty hlasu (pedalboard) |
| `outputs/fillers.py`, `outputs/overlay.py` | filler hlášky, HUD server |
| `overlay/index.html` | HUD |
| `tools/simulate_game.py` | simulátor hry na testovanie bez Cyberpunku |

Plán a stav: [SPEC.md](SPEC.md), [PROGRESS.md](PROGRESS.md), [POSTUP.md](POSTUP.md).
