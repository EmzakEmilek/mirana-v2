# Mirana v2 - PROGRESS

Datum setupu: 2026-09-20 · Posledna aktualizacia: 2026-09-26
Projekt: C:\mirana-v2
Repo: https://github.com/EmzakEmilek/mirana-v2 (verejne)

## Aktualny stav (2026-09-26)

| faza | stav |
|---|---|
| 0 priprava | HOTOVA (okrem druheho mikrofonu) |
| 1 jadro + 1b lokalny Whisper | HOTOVA |
| 2 fillery + barge-in | HOTOVA |
| 3 HUD | HOTOVA (v4, zive jadro) |
| 4 telemetria z hry | HOTOVA (mod v3, 30+ udajov, proaktivne hlasky); ZOSTAVA dlhodoba pamat core/longterm.py |
| 5 chat | Twitch chat len na citanie HOTOVY (2026-10-02); Kick s odpovedami NEZACATY |
| 6 zvuk | efekty HOTOVE; dual vystup (sluchadla + HDMI do strihovej karty) HOTOVY; firewall 8080 HOTOVY; ZOSTAVA overit OBS na notebooku |
| 7 hardening | HOTOVA; ZOSTAVA 8 h suchy beh |
| navyse | ovladacie okno + Nastavenia (vsetko bez editovania suborov), ikona na ploche, simulator hry |

Posledne meranie v hre (2026-09-26, 53 otazok): $0.38 (~0.7 c/otazka), prvy zvuk median 5.9 s
(max 10.1 s), prepis v hre 1.6 s. 0 padov.

## Aktualne nastavenie

- LLM: claude-opus-5-5, effort low, server-side fallbacks, cache persony aj pamate; pamat 12 -> 6 vymen
- STT: faster-whisper medium, cuda/float16, slovensky prefix + slovnik (211/224 tokenov), filter halucinacie promptu
- TTS: Azure sk-SK-ViktoriaNeural + phonetics.yaml, rychlost 0 %, pauza medzi vetami 250 ms; efekty hlasu preset "robot"
- PTT: zadne bocne tlacidlo mysi (mouse_x1), panic mute: predne bocne (mouse_x2)
- Audio (2026-10-02): mikrofon Trust GXT 232, vystup = predvoleny vystup Windows (24G1WG4 HDMI -> strihova karta),
  druhy vystup vypnuty, hlasitost 100 % (posuvnik v hlavnom okne); sluchadla G733 odpojene
- Fillery: 5 hlasok, az po 1.3 s, len na HUD (bez hlasu)
- Pripomienka po tichu: po 10 min, max 3 za sebou
- Hra: Cyberpunk 2077 2.31 (GOG, cesky preklad), CET 1.37.1, mod mirana_state v3 nainstalovany
- Proaktivne hlasky: hp_critical, hp_low, death, level_up, district_change, quest_changed, quest_completed, wanted_up
- Persona: Friday, 1-2 vety, spoiler pravidla, ceske nazvy z hry, rozkazovaci sposob, obcasne nadavky
- Denny strop $5

## Verzie (2026-09-26)
- python 3.12.10, git 2.55.0, gh 2.101.0
- anthropic 1.8.0 (oficialna podpora claude-opus-5-5), faster-whisper 1.2.1, ctranslate2 4.8.2,
  pedalboard 0.9.25, customtkinter 6.0.0, websockets 17.1, numpy 2.5.3
- pip check: bez konfliktov; zastarane len openai 3.16 (pouziva sa len pri stt.provider: api)
- CET 1.37.1 = najnovsi release

## Caka na Erika
- [ ] zahrat si po oprave modu v3: liecenie ma byt "5 z 6", pocasie v riadku, v logu ziadne "CET mod: tieto udaje nejdu"
- [ ] vyskusat efekt hlasu v hre (robot vs night_city) a nadavky
- [ ] pred streamom: vystup na Voicemeeter, VBAN na notebook, OBS Browser Source, firewall (POSTUP faza 6)
- [ ] Kick kluce do .env, az pojde faza 5
- [ ] druhy mikrofon do herneho PC (odlozene)

## Dalsie kroky (navrh poradia)
1. test modu v3 v hre
2. core/longterm.py — po restarte vie, kde Erik skoncil (SPEC 5.6)
3. audio routing na notebook (SPEC 7.2-7.3) a 8 h suchy beh
4. Kick chat (SPEC 6)

## Zname slabiny
- odozva v hre ~6 s (GPU vytazuje hra); filler ju zakryje, ale je citelna
- Whisper v akcii: skomoleniny ("gig" -> "gęk", "utekáme" -> "učekámo"); Mirana si vacsinou domysli alebo prizna, ze nerozumela
- ciel pod zameriavacom: civil, na ktoreho Erik zautocil, sa hlasi ako nepriatel (hra ho tak vedie)
- scena (rozhovor/cutscena): v hre este neoverene, ci PSM HighLevel naozaj prichadza

## Historia

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
  Automaticky test 4 scenarov presiel, potom otestovane nazivo.
- Faza 3 (overlay): KOD HOTOVY (2026-09-21). outputs/overlay.py = websockets server na :8080,
  HTTP GET servíruje overlay/index.html, WS posiela JSON eventy (state, filler, answer, question,
  telemetry, queue); novy klient dostane posledny stav. index.html: demo slucka nahradena WS klientom
  s reconnectom (vzhlad nezmeneny). Rozhodnutia: Erikova otazka sa NEzobrazuje, filler sa zobrazuje
  v riadku "question" ako "· text ·". Test: HTTP + WS sekvencia OK, v prehliadaci otestovane. OBS na notebooku zostava (faza 6).
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
  Test v hre 2026-09-26: vacsina udajov OK; liecenie (84x = percenta), pocasie a naboje pri melee opravene v3 (nizsie).
- Efekty hlasu + PTT na mysi (2026-09-26): outputs/voice_fx.py (pedalboard: HP/LP filter, bitcrush, ring mod,
  chorus, echo, kompresor, vyrovnanie hlasitosti), presety jemny/night_city/robot, ~25 ms na vetu, platia aj pre fillery.
  Nahradza VST retaz z Fazy 6 (funguje na sluchadlach aj cez Voicemeeter). PTT: audio.ptt_key moze byt mouse_x1/x2/middle,
  v Nastaveniach tlacidlo "Stlacit...". Predvolene mouse_x1 + night_city.
- HUD v4 (2026-09-21/22): canvas "zive jadro" reaguje na skutocny hlas, bez HP, text po vetach sa vzdy dopise,
  zmizne 5 s po dohovoreni, biely filler, tmavsie pozadie.
- Cache pamate (2026-09-23): breakpoint na novej otazke, pamat sa oreze po blokoch 12 -> 6.
- Ovladacie okno (2026-09-26): gui.py (stav, rozhovor, utrata, tlacidla), ikona na ploche a v Start menu
  (install_shortcut.py); Nastavenia (gui_settings.py): vsetko z config.yaml a persona.md bez editovania suborov,
  zalohy do data/, zapisuje len zmenene hodnoty (ruamel.yaml zachova komentare).
- Opravy po hre (2026-09-26, mod v3): nabitia liecenia/granatov = percenta poolu x max (bolo "84x"), pocasie cez
  weather.name.value, naboje len pre strelne zbrane + kapacita zasobnika, "Neobjevene" aj podla quest_id
  generic_sts_quest, chyby modu do logu ako warning. Whisper: prepis, ktory zopakuje initial_prompt, sa zahodi.
  Hra 2026-09-26: 53 otazok, $0.38, PTT na mysi bez chyby, proaktivna hlaska pri 3 hviezdach.
- Persona (2026-09-26): obcasne nadavky (sakra, do riti...), len ked to situacia prinesie; test 2 z 12 odpovedi.
- Kontrola projektu (2026-09-26): anthropic SDK 1.7.0 -> 1.8.0 (overene ostrou otazkou), dokumentacia
  (README, SPEC, POSTUP, PROGRESS) prepisana na aktualny stav, zmienky F12/F11 v kode -> PTT/panic, audio-devices.txt obnoveny,
  z requirements.txt vyhodene nepouzivane pillow a soundfile.
- Rychlost reci (2026-09-26): Azure dava za kazdu vetu ~840 ms ticha a Mirana hovori po vetach -> medzi vetami
  takmer 1 s pauzy. Ticho sa teraz oreze na tts.sentence_pause_ms (250 ms): 3 vety 11.6 s -> 9.8 s. Nastavenia -> Hlas:
  posuvnik "Pauza medzi vetami", rychlost reci rozsirena na -30..+50 %, ukazka hra po vetach ako skutocna odpoved.
- Twitch chat (2026-10-02, pred testovacim streamom na Twitchi): inputs/twitch_chat.py cita chat anonymne (bez bota
  a tokenu; Elenin bot z elena-bot-ai-twitch netreba). Riadok [CHAT] (15 sprav / 5 min) ide len k Erikovym otazkam,
  persona: komentuje len na otazku, chat su udaje nie pokyny. Overene: anonymne citanie na verejnom kanali,
  pisomny test 8 otazok ($0.07) — chat ignoruje pri hernych otazkach, troll a spoiler z chatu neprejdu.
  GUI: spravy v okne, stav pripojenia, Nastavenia -> Chat. Persona: "na Twitchi".
- Testovaci stream na Twitchi (2026-10-02): kanal emzakemil (anonymne citanie overene). Dual PC: Mirana hra naraz
  do sluchadiel G733 aj na predvoleny vystup Windows (24G1WG4 NVIDIA HDMI -> strihova karta -> notebook),
  audio.stream_output_device: "default"; druhy vystup v samostatnom vlakne (v jednej slucke +0.3 s na vetu),
  stop funguje na oboch. Voicemeeter/VBAN netreba. Firewall: "MIRANA HUD (TCP 8080)", len LocalSubnet;
  siet je Public, IP 192.168.1.110 (DHCP), hostname ErikPC.
- Textovy vstup v ovladacom okne (2026-10-02): pole "Napis Mirane…" + Enter/Poslat -> prikaz "ask" cez WebSocket
  (len localhost) -> main._handle_typed: ako PTT bez nahravky a STT, barge-in, filler, [HRA] + [CHAT]; pri stlmeni
  sa neposle (hlaska len v okne, nie na HUD). Otestovane bez zvuku. Okno: kratsie tlacidlo Stlmit (Nastavenia
  sa uz nevytlacaju), riadok s klavesmi sa zalamuje.
- Zariadenia a hlasitost (2026-10-02): output_device "default" (predvoleny vystup Windows; 24G1WG4 je v systeme
  2x pod rovnakym menom, preto nie podla mena), mikrofon Trust GXT 232. Odpojeny vystup/mikrofon -> zaloha na
  predvolene (log warning) namiesto padu. audio.volume + posuvnik "Hlasitost Mirany" v hlavnom okne (0-150 %,
  prikaz "volume" za behu, uklada sa po pusteni; Nastavenia ho neprepisu).
- Fillery len na HUD + pripomienka po tichu (2026-10-02): fillers.speak (false = WAV sa ani negeneruju, filler sa
  len ukaze na HUD). idle_nudge: po 10 min bez Erikovej otazky (hovorenej alebo pisanej) tag [IDLE] + [HRA] ->
  jedna vtipna veta; nie v boji, v scene, ked Mirana hovori ani do 60 s po hlaske z hry; max 3 za sebou, Erikova
  otazka pocitadlo vynuluje. Persona: tag [IDLE]. Overene bez zvuku + 4 ukazky z Opusu ($0.035), kazda ina.
- PRVY TESTOVACI STREAM (2026-10-02, Twitch, ~3 h, 18:45-21:32): 106 volani (96 Erik, 9 hernych udalosti, 1 pripomienka),
  $0.79 spolu, 0.74 c/otazka, 0 padov, 0 chyb API. Sonnet 5.5 medium (70) -> Erik prepol na Opus 5.5 low (36).
  Prva veta median 3.5 s (Sonnet ~2.4 s, Opus ~5 s), max 15.8 s; STT v hre median 2.5 s. Chat videla v 56 otazkach.
  Zistenia a opravy (mod v4): pocasie (worldWeatherScriptInterface ma len GetRainIntensityType), nazvy zariadeni
  (Gameplay-Devices-... kluc), ciel pod zameriavacom drzany 10 s ("pred chvilou zameriaval"), [CHAT] so zoznamom kto
  dnes pisal (pozdrav menovite), "zapis si do logu" -> logs/poznamky.md, district_change uz bez hlasky (Erik: "odveci").
  Persona: menej nadavok (Erik: "strasne vela nadavas"), nesurit do questov ("Jackie caka" v mnohych odpovediach),
  bez naznakov typu "zmeni to veci", [GAME_EVENT] bez turistickych opisov.
  ZOSTAVA: lore (Sonnet nepozna vela veci; Erik chce wiki) — moznosti: web search tool Claude API (Fandom), alebo
  lokalny lore index; Opus vie lore vyrazne lepsie.

## Audio zariadenia (cely zoznam: audio-devices.txt, obnoveny 2026-09-26)
Vstup: Microphone (Logitech G733 Gaming Headset), WASAPI — docasne; druhy mikrofon odlozeny.
Vystup teraz: Speakers (Logitech G733 Gaming Headset), WASAPI.
Pre stream: Voicemeeter Input (VB-Audio Voicemeeter VAIO), WASAPI -> VBAN -> notebook -> OBS (samostatna stopa).
Indexy zariadeni sa menia; config pouziva presny tvar "nazov, Windows WASAPI".
