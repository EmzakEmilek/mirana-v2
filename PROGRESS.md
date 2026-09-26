# Mirana v2 - PROGRESS

Datum setupu: 2026-09-20
Projekt: C:\mirana-v2
Repo: https://github.com/EmzakEmilek/mirana-v2 (privatne)

## Nainstalovane / verzie
- git: 2.55.0.windows.3
- gh: 2.101.0
- python: 3.12.10
- Voicemeeter Banana: nainstalovany a bezi (zariadenia viditelne)
- Claude Code: nainstalovany, `claude --version` v starej session nenajdene (neriesime)

## Struktura
C:\mirana-v2\
  inputs/ core/ outputs/ overlay/ mod/ fillers/
  .gitignore, .env (prazdna sablona), venv/, audio-devices.txt

venv balicky: pozri requirements.txt (pip install -r requirements.txt)

## Audio zariadenia (cely zoznam: audio-devices.txt)
Vstup (mikrofon):
- Microphone (Logitech G733 Gaming Headset) - MME #8, DirectSound #32, WASAPI #67
- Druhy mikrofon do herneho PC: zatial nie je pripojeny (odlozene)

Vystup pre Miranin hlas:
- Voicemeeter Input (VAIO)      - MME #20, WASAPI #57
- Voicemeeter AUX Input (VAIO2) - MME #15, WASAPI #52
- Voicemeeter VAIO3 Input       - MME #11, WASAPI #51  <- navrh: samostatna linka pre Miranu

Navrh routingu (na potvrdenie):
  Mirana TTS -> VAIO3 Input -> Voicemeeter B1/B2 -> capture karta / notebook -> OBS

## Cyberpunk 2077 / CyberEngineTweaks
- Hra zatial NENAINSTALOVANA. Krok 8 odlozeny.
- Po instalacii: najst ...\Cyberpunk 2077\bin\x64\ a rozbalit tam najnovsi release
  z https://github.com/maximegmd/CyberEngineTweaks/releases

## Stav faz
- Faza 0 (priprava): HOTOVA (2026-09-20), okrem hry/CET a druheho mikrofonu
- Faza 1 (jadro PTT -> Whisper -> Sonnet 5 -> Azure TTS): HOTOVA (2026-09-21).
  5 testovacich kol, ~25 otazok, 0 padov, 0 chyb. Od pustenia F12 po hlas 3-5 s.
  Cena ~0.3 c/otazka (Sonnet 5, effort medium, persona 2658 tok cachovana) => ~$0.20-0.25/hod streamu.
- Faza 1b (lokalny Whisper): HOTOVA (2026-09-21). core/stt.py, faster-whisper medium/cuda/float16,
  prepis 0.5-1.0 s, slovencina presna. Anglicke nazvy: stt.local_vocabulary (initial_prompt, max 224 tok)
  + persona vie, ze prepis je foneticky (skalpel = Scalpel). OpenAI ucet uz nie je potrebny (provider api = zaloha).
- Ladenie po testoch (2026-09-21): oslovenie "Emzo" (nie chum), odpovede max 2 vety/35 slov,
  sarkazmus ako korenie nie zaklad, sekcia "Prirodzena rec" v persona.md.
  TTS: en-US-EmmaMultilingualNeural + phonetics.yaml (anglicizmy -> SK fonetika len pre TTS).
  Audio docasne na Logitech G733 (WASAPI, nativna frekvencia, sample_rate: null); pre stream prepnut
  output_device spat na Voicemeeter Input.
  Znama slabina: Sonnet obcas vymysli lore detail (Scalpel = katana, nie noz) — kandidat na Opus 5.
- Persona v3 "Jarvis/Friday" (2026-09-21): sekcia Charakter (pokoj, suchy humor, lojalita
  s nazorom, predvidavost, zdrzanlivost), register namiesto hotovych replik, zensky rod,
  spoiler ani naznakom. 2612 tok. Pisomny test 24 promptov (vratane [GAME_EVENT], [CHAT_*],
  telemetria, mimo hry) na Opus 5 low: 0.93 c/otazka, ton sedi, 0 unikov spoilerov.
  LLM finalne: claude-opus-5, effort low (Sonnet 5 high = 3 halucinacie + jazykove artefakty).
  Whisper: medium + slovensky prefix promptu (large-v3-turbo prekladal do anglictiny).
  Zname slabiny modelu: Padre (El Coyote Cojo — zle), obcas prijme chybny predpoklad otazky.
- ROZHODNUTIE 2026-09-21: Kick chat (Faza 5) ostava v plane, ale zatial VYPNUTY
  (kick_chat.enabled: false). Persona, routing na Sonnet a pamat divakov v SPEC ostavaju.
- Faza 2 (fillery + barge-in): KOD HOTOVY (2026-09-21). outputs/fillers.py (8 WAV, generuju sa
  pri prvom starte), main.py prepisany: STT+LLM vo worker vlakne, generacia ulohy, filler z casovaca
  po 800 ms, barge-in z PTT vlakna (stop < 100 ms). voice.py: vlastny OutputStream po 50 ms kusoch
  (sd.stop z ineho vlakna padal, WASAPI z ineho vlakna potrebuje CoInitializeEx).
  Automaticky test 4 scenarov presiel. CAKA NA TEST cez F12 (krok 17).
- Faza 3 (overlay): KOD HOTOVY (2026-09-21). outputs/overlay.py = websockets server na :8080,
  HTTP GET servíruje overlay/index.html, WS posiela JSON eventy (state, filler, answer, question,
  telemetry, queue); novy klient dostane posledny stav. index.html: demo slucka nahradena WS klientom
  s reconnectom (vzhlad nezmeneny). Rozhodnutia: Erikova otazka sa NEzobrazuje, filler sa zobrazuje
  v riadku "question" ako "· text ·". Test: HTTP + WS sekvencia OK. CAKA NA TEST v prehliadaci
  (localhost:8080) a neskor OBS na notebooku (firewall: povolit TCP 8080 na hernom PC).
- Review + opravy (2026-09-23):
  * phonetics.yaml kazil SK slova ("ostatni" -> "ó estatni", ~9 % odpovedi) — teraz cele slova,
    kratke kluce len presne; "Chaos" vyhodeny
  * Opus 5.5 low + server-side fallbacks, osetrenie stop_reason (refusal/max_tokens/prazdne)
  * streaming: vety idu do outputs/speaker.py hned, ako vzniknu; prvy zvuk ~4 s (predtym 5-7 s)
  * denny strop naozaj vynuteny (core/budget.py), logy + rozhovor do logs/, zamok proti 2 instanciam,
    TTS timeout (veta sa aspon vypise na HUD), barge-in bez race, do pamate len vypocuta cast
  * persona v4: menej pravidiel, ziadne "senzory", neistotu priznava nahlas; telemetriu doplni Erik
    (persona ocakava riadok zacinajuci "[HRA]")
- Hardening (2026-09-26): panic mute F11 (HUD 'STLMENA'), supervisor run.py (restart pri pade alebo zamrznuti,
  heartbeat data/heartbeat, max 5/h), core/safety.py (osobne udaje + safety.blocked_words), start.bat, README. Otestovane.
- Faza 4 (telemetria) KOD HOTOVY (2026-09-26): mod/mirana_state/init.lua (API z CP77-DiscordRPC2, pcall na kazdy udaj),
  inputs/game_state.py (riadok [HRA] po slovensky, udalosti, auto-najdenie hry, instalacia modu), proaktivne hlasky
  (cooldown 300 s, 30 s po Erikovi ticho, kriticke HP/smrt hned a pockaju, kym dohovori), HUD + okno + Nastavenia -> Hra.
  Otestovane so simulatorom (tools/simulate_game.py). A/B: slovensky riadok OK, surovy JSON zle citaL HP (74 -> 'stvrtina').
  Hra sa instaluje cez GOG (C:\Program Files (x86)\GOG Galaxy\Games\Cyberpunk 2077). CET 1.37.1 nainstalovany,
  mod v1 overeny v hre (hra 2.31, cesky preklad — Erik ho necha).
- Telemetria v2 (2026-09-26): mod posiela aj zasoby, postavu, vybavu, ciel pod zameriavacom, policiu, cas, pocasie,
  scenu, rychlost/radio a dokoncene hlavne questy. Nove udalosti quest_completed, wanted_up, wanted_clear;
  pocas sceny ziadne proaktivne hlasky; "Neobjevene" sa neberie ako quest. Persona: ceske nazvy z hry,
  rozkazovaci sposob namiesto neurcitku. Whisper slovnik + gig/gigy (211/224 tokenov).
  Overene: mock hry v Lua (lupa), simulator, pisomny test Opus low (14 otazok, $0.12, slovencina OK).
  CAKA NA: test v hre — skontrolovat pole "errors" v state.json (API volania v2 su z dekompilovanych skriptov).
- Faza 4-7: nezacate

## Podklady (HOTOVE, 2026-09-20)
- SPEC.md, persona.md, config.yaml, POSTUP.md ulozene v korene (COWORK-FAZA-0.md splneny a zmazany)
- overlay/index.html (diegeticky HUD) ulozeny
- .gitignore prepisany na plnu verziu (+ *.pyc, mirana_state.json)
- .env.example ulozeny (obsahuje aj KICK_* pre Fazu 5)
- config.yaml: audio.output_device = "Voicemeeter Input (VB-Audio Voicemeeter VAIO), Windows WASAPI"
  (presny match nazov+hostapi, index 57 sa moze menit); input_device ostava null

## Caka na Erika
- [x] gh auth login + repo vytvorene
- [ ] pridat do .env riadky KICK_CLIENT_ID / KICK_CLIENT_SECRET / KICK_CHANNEL_ID
      (rucne - .env sa neda zapisovat vzdialene; predloha je v .env.example)
- [ ] doplnit API kluce do .env (ANTHROPIC_API_KEY, OPENAI_API_KEY, AZURE_SPEECH_KEY)
- [ ] nainstalovat Cyberpunk 2077, potom CyberEngineTweaks
- [ ] pripojit druhy mikrofon do herneho PC (odlozene)
- [ ] potvrdit audio routing vyssie
