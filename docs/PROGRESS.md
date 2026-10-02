# Mirana v2 - PROGRESS

Datum setupu: 2026-09-20 · Posledna aktualizacia: 2026-10-03
Projekt: C:\mirana-v2
Repo: https://github.com/EmzakEmilek/mirana-v2 (verejne)

## Aktualny stav (2026-10-03)

| faza | stav |
|---|---|
| 0 priprava | HOTOVA (okrem druheho mikrofonu) |
| 1 jadro + 1b lokalny Whisper | HOTOVA |
| 2 fillery + barge-in | HOTOVA |
| 3 HUD | HOTOVA (v4 + efekty, fit rezim pre OBS) |
| 4 telemetria z hry | HOTOVA (mod v5, proaktivne hlasky, dlhodoba pamat) |
| 5 chat | Twitch chat len na citanie HOTOVY; Kick zruseny (2026-10-03) |
| 6 zvuk | HOTOVA (efekty, HDMI do strihovej karty, firewall 8080); prvy stream 2026-10-02 |
| 7 hardening | HOTOVA; testy (89), diagnostika pri starte, bezpecne ukladanie |
| navyse | wiki, snimka hry, momenty na strih, pamat divakov, ovladacie okno + Nastavenia zo schemy |

Stavba programu: docs/ARCHITECTURE.md. Zmeny pre Erika: CHANGELOG.md.

## Aktualne nastavenie

- LLM: claude-sonnet-5-5, effort low, server-side fallbacks, cache persony, pamate a [PAMÄŤ]; pamat 30 -> 15 vymen
- STT: faster-whisper medium, cuda/float16, slovensky prefix + slovnik, filter halucinacie promptu (Azure STT vyradeny)
- TTS: Azure sk-SK-ViktoriaNeural + phonetics.yaml, rychlost +25 %, vyska +15 %, pauza 250 ms, efekt "robot"
- PTT: zadne bocne tlacidlo mysi (mouse_x1), znacka na strih: predne bocne (mouse_x2), panic mute: F11
- Audio: mikrofon Trust GXT 232, vystup = predvoleny vystup Windows (24G1WG4 HDMI -> strihova karta), hlasitost 150 %
- Fillery: len na HUD; wiki hlasky nahlas (7); pripomienka po 10 min ticha, max 3 za sebou
- Hra: Cyberpunk 2077 2.31 (GOG, cesky preklad), CET 1.37.1, mod mirana_state v5 (aktualizuje okno samo)
- Twitch chat: emzakemil, len citanie; dlhodoba pamat: Sonnet 5.5, zhrnutie kazdych 30 min
- Denny strop $5; logy starsie ako 14 dni do logs/archive/

## Verzie (2026-10-03)
- python 3.12.10; pevne verzie kniznic v requirements.txt (anthropic 1.8.0, faster-whisper 1.2.1, pedalboard 0.9.25,
  customtkinter 6.0.0, websockets 17.1, numpy 2.5.3, ...); testy: requirements-dev.txt (pytest 9.1.1)
- CET 1.37.1

## Caka na Erika
- [ ] dalsi stream po prestavbe (vlny 1-3): skontrolovat log a rozhovor (novy format zaznamu so zdrojom a kontextom)
- [ ] druhy mikrofon do herneho PC (odlozene)

## Dalsie kroky (navrh)
1. bod 10 z navrhu architektury (nastroje modelu ako register) — odlozeny
2. bod 22 z kontroly (dalsia faza) podla Erika
3. 8 h suchy beh

## Zname slabiny
- odozva v hre ~5-6 s (GPU vytazuje hra; Whisper v hre ~2.3 s); filler na HUD ju zakryje
- Whisper v akcii: skomoleniny; Mirana si vacsinou domysli alebo prizna, ze nerozumela
- ciel pod zameriavacom: civil, na ktoreho Erik zautocil, sa hlasi ako nepriatel (hra ho tak vedie)

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
- Wiki (2026-10-02): core/wiki.py = Cyberpunk Fandom MediaWiki API (search + wikitext, bez kluca, ~1 s), nastroj `wiki`
  pre model (max 2 hladania na otazku, potom tool_choice none), infobox bez status/dod/smrti, uvod + dalsie sekcie do 1800 zn.
  Pri zaciatku volania nastroja zaznie nahlas fillers.search_lines (7 hlasok, fillers/search_*.wav). Persona: pri "kto je /
  co je" z lore vzdy hladaj (Sonnet low si inak vymyslal, napr. Mox). Test Sonnet 5.5 low: Tanishi, Padre, Dum Dum, Scalpel,
  Mox, Royce, Dex spravne; spoilery (Jackie, Evelyn, Takemura) drzane; cena aj prva veta bez zmeny (~4.8 s median).
  Model prepnuty na Sonnet 5.5 low.
- KONTROLA A VYLEPSENIA (2026-10-02, body z kontroly podla Erikovho vyberu):
  * opravy: HUD fit glitch (animacia prepisovala transform), prikazy z prehliadaca (Origin) odmietnute, makky limiter
    nad 100 % hlasitosti, prerusena odpoved v rozpocte, aktualny riadok Hra v okne, requests v requirements, komentare
  * persona: rozpory (internet vs wiki, humor, neistota vs hladanie), [CHAT_SUB] prec, [STREAM], [WIKI], poradie smrti
  * pamat bez [HRA]/[CHAT] (85 % pamate) -> 30/15 vymen za rovnaku cenu
  * wiki predhladanie: index 17k nazvov, "kto je X" -> clanok v sprave; Padre 4.7->1.9 s, Tanishi 9.2->2.2 s, Royce 9.9->2.4 s
  * mod v5 kazdu 1 s, citanie 0.5 s; znacky na strih (mouse_x2, decapi.me uptime), automaticke momenty, [STREAM];
    panic mute presunuty na F11; HUD: databaza, bannery, hviezdy, pocitadlo smrti, kriticke HP, flatline
  * ZAMIETNUTE po merani: Azure STT (0.25 s, ale mena z hry zle: "mel strom", "rok" = Rogue; phrase list usekol vetu)
    -> ostava Whisper, Azure ako volba; TTS streaming (syntéza vety 0.25 s, zisk ~0.12 s); bez premyslania
    (Sonnet between_tools pomalsi 2.66 vs 2.15 s a cital nahlas vlastne uvahy)
  * namerane pre dalsiu fazu: obrazovka (vision) +0.24 c (Sonnet, 1280 px) a +0.17 s k prvej vete
- Vision + HUD testy (2026-10-02): core/vision.py — pri "co je toto / kto je to / vidis / pozri" snimka LEN okna hry
  (EnumWindows podla nazvu, klientska cast, DPI aware; ziadne okno / cierna snimka = nic sa neposle), 1280 px JPEG,
  [OBRAZOVKA] v sprave, do pamate nejde. Test na okne MIRANA: snimka 113 ms, model okno spravne opisal.
  HUD: databaza strieda hlasky kazde 2 s (nahlas len prva), vizualny sken; Nastavenia -> HUD -> Test efektov
  (odpoved, databaza, sken, level, quest, smrt, policia, kriticke HP — prikaz hud_test, len vizual).
- Dlhodoba pamat (2026-10-02, SPEC 5.6 + pamat divakov): core/longterm.py, data/memory.json — game (z telemetrie
  raz za 30 s), streams (statistiky + momenty), erik.facts (zhrnutie modelom, max 25), viewers (statistiky automaticky
  + 1-3 poznamky modelom, bez osobnych udajov). Zhrnutie Sonnet 5.5 low structured output kazdych 30 min, pri vypnuti
  (max 25 s, GUI caka 35 s) a pri starte nespracovane sessions; prvy beh spracoval stream 2026-10-02 (aj chat z riadkov
  [CHAT]) za 28 s. [PAMÄŤ] system blok s vlastnym cache breakpointom, [DIVÁCI] len pre divakov v chate/spomenutych,
  "zabudni X" (divak) / "zabudni, ze..." (model vyberie fakty). Nastavenia -> Pamat (fakty, poznamky "login: a | b",
  vymazat divakov, zabudnut vsetko -> memory_reload bez restartu). E2E test: pamat aj divaci spravne, zabudni funguje.
- PRESTAVBA (2026-10-03, navrh architektury, vlny 1-3 okrem bodov 10 a 18; 18 nahradeny archivom logov):
  * vlna 1: pytest (tests/), MIRANA_NO_AUDIO, pevne verzie, typove udalosti (events.py) + jeden _start_turn namiesto
    4 kopii, protokol HUD/okno (protocol.py, telemetria s menami poli, neznamy prikaz odmietnuty), atomicke ukladanie
    (store.py). Testy nasli: chybu v Nastaveniach (lambda s vynimkou), divak sa nenasiel vysklonovany ("Kuba") ani
    podla casti nicku (Kubo_SK), kolizia pola "kind" v protokole — opravene.
  * vlna 2: balik mirana/ (app = jadro; features: highlights, hud, longterm, wiki, vision, idle, notes, archive),
    ui/ (okno), docs/; Turn s kontextom v pevnom poradi; zaznam rozhovoru so zdrojom, otazkou a kontextom (pamat cita
    stary aj novy format); intents.py so vsetkymi klucovymi slovami — snimka hry 28 -> 14 zo 218 otazok (vsetky
    zostavajuce su naozaj o obrazovke).
  * vlna 3: schema.py (kazde nastavenie raz: default, typ, rozsah, popis) + kontrola pri nacitani (zla hodnota ->
    predvolena + problem do diagnostiky); okno Nastavenia skladane zo schemy (ulozenie bez zmien = identicky
    config.yaml, overene); diagnostika pri starte okna; automaticka aktualizacia modu (len ked hra nebezi);
    uprava pamate z okna cez prikaz memory_edit; Azure STT a Kick odstranene; archiv logov do ZIP (overeny pred
    zmazanim, poslednych 4 sessions ostava); ARCHITECTURE.md, FUNKCIE.md, CHANGELOG.md, kratsi README.

## Audio zariadenia (2026-10-02)
Vstup: Microphone (Trust GXT 232 Microphone), WASAPI.
Vystup: predvoleny vystup Windows = 24G1WG4 (NVIDIA High Definition Audio, HDMI) -> strihova karta -> notebook s OBS.
Druhy vystup vypnuty; sluchadla G733 odpojene. Indexy zariadeni sa menia; config pouziva tvar "nazov, Windows WASAPI".
