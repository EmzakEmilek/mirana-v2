# Funkcie Mirany podrobne

Prehľad je v [README](../README.md), stavba programu v [ARCHITECTURE.md](ARCHITECTURE.md).

## Ovládacie okno

- stav (STANDBY / POČÚVAM / SPRACOVÁVAM / HOVORÍ / STLMENÁ), dnešná útrata so stropom,
- riadok „Hra: …“ s tým, čo Mirana práve vidí z hry,
- priebeh rozhovoru (tvoja otázka, Miranina odpoveď, systémové hlásenia),
- **kontrola pri štarte**: nastavenia, kľúče v `.env` (len či existujú), mikrofón, výstup, grafika pre Whisper,
  hra, CET a mod; čo nie je v poriadku, vypíše s „⚠“. Novší mod z repa nainštaluje sám, keď hra nebeží,
- **Hlasitosť Mirany** (0–150 %): zaberie hneď, aj uprostred vety, a uloží sa,
- **textové pole**: otázka napísaná + Enter ide Mirane ako hovorená (bez prepisu, preruší rozbehnutú odpoveď),
- tlačidlá **Vypnúť/Spustiť**, **Stlmiť**, **HUD**, **Logy**, **Nastavenia**.

**Nastavenia** (bez editovania súborov):

| záložka | čo sa tam nastavuje |
|---|---|
| Zvuk | mikrofón a výstupy s testom, tlačidlo na hovor, panic mute, značka na strih |
| Hlas | Azure hlas, rýchlosť reči, pauza medzi vetami, výška, fonetika, efekty hlasu, ukážka |
| Model | model a effort, záložný model, denný strop, pamäť rozhovoru |
| Hra | nájdenie hry, stav CET a modu, inštalácia modu, prahy HP, odstup hlášok, kedy sa ozve sama |
| Prepis | lokálny Whisper alebo API, model, jazyk (slovník názvov je v config.yaml) |
| Fillery | hlášky na zakrytie pauzy, wiki a hlášky pri hľadaní, pripomienka po tichu |
| HUD | zapnutie, port, tempo písania, test efektov |
| Chat | čítanie Twitch chatu, kanál, koľko správ vidí, ignorovaní boti |
| Bezpečnosť | filter a zakázané slová |
| Pamäť | fakty o tebe a poznámky o divákoch (úprava, zabudnutie) |
| Persona | celý text persona.md, hľadanie Ctrl+F |

„Uložiť a reštartovať“ ich hneď použije. Zlá hodnota (text namiesto čísla, port pod 1024, rovnaké tlačidlá…)
sa neuloží a okno povie prečo. Pred uložením sa zálohuje `data/config.yaml.bak` a `data/persona.md.bak`.
Úpravu pamäte zapíše bežiaca Mirana sama (nič sa neprepíše), keď nebeží, okno priamo do súboru.

## Telemetria z hry (CET)

Mirana vie z hry:

- **stav**: HP, nabitia liečenia a granátov, náboje v zásobníku, RAM, peniaze, či bojuješ, či si v scéne
- **svet**: štvrť, čas v hre, počasie, polícia (hviezdy)
- **quest**: sledovaný quest a cieľ; **príbeh**: dokončené hlavné questy (kam až si došiel, pre spoilery)
- **postava**: level, street cred, atribúty, nerozdelené body, voľná kapacita kybervýzbroje
- **výbava**: OS (cyberdeck/Sandevistan/Berserk), zbrane v slotoch, zbraň v ruke, brnenie
- **cieľ pod zameriavačom**: meno, nepriateľ/civil/boss/mŕtvy, úroveň, zdravie; vozidlá a zariadenia
- **auto**: vozidlo, rýchlosť, rádio a skladba

Sama sa ozve pri udalostiach z `game_state.speak_on` (kritické HP, smrť, level, quest, polícia, boj…): najviac raz
za 5 min, nie skôr ako 30 s po tvojej otázke, kritické HP a smrť hneď (keď práve hovorí, povie to hneď po nej),
počas rozhovorov a cutscén mlčí. Názvy z hry prídu v jazyku hry (po česky) a tak ich aj povie.

Inštalácia: [Cyber Engine Tweaks](https://github.com/maximegmd/CyberEngineTweaks/releases) rozbaliť do priečinka hry,
potom okno MIRANA → Nastavenia → **Hra** → **Nainštalovať mod**. Nové verzie modu inštaluje okno pri štarte samo
(len keď hra nebeží). Ak niektorý údaj po patchi hry prestane chodiť, Mirana to zapíše do logu
(„CET mod: tieto udaje nejdu“) a ostatné idú ďalej.

Mod zapisuje každú sekundu `state.json`; do promptu ide slovenský riadok `[HRA]`, nikdy surový JSON.
Bez hry: `venv\Scripts\python tools\simulate_game.py` zapisuje falošný stav do `data/sim_state.json`; Miranu vtedy
spusti s `set MIRANA_GAME_STATE_PATH=C:\mirana-v2\data\sim_state.json`.

## Wiki (lore)

Pri otázkach „kto je / čo je“ z lore si Mirana pozrie **Cyberpunk Fandom wiki** (verejné API, bez kľúča).
Pri „kto je Padre?“ sa článok nájde **vopred** podľa indexu 17 000 názvov (`data/wiki_titles.json`, obnova raz
týždenne) a priloží sa k otázke ako `[WIKI …]` — lore otázka 4,7–9,9 s → 1,9–2,4 s. Keď predhľadanie nič nenájde,
Mirana hľadá sama nástrojom a nahlas povie hlášku („hľadám v databáze“, `fillers.search_lines`; na HUD sa pri dlhšom
hľadaní striedajú každé 2 s). Z infoboxu sa vynechá stav a smrť postavy; persona nesmie prezradiť spoilery.

## Momenty na strih

Ťuknutie na predné bočné tlačidlo myši zapíše do `logs/strih-<dátum>.md` čas vo VOD-ke (koľko stream bežal,
z verejného decapi.me), hodiny a kontext (kde si bol, posledná otázka a odpoveď). Automaticky sa zapíšu aj smrti,
levely, dokončené hlavné questy a policajné naháňačky od 3 hviezd. Na „Mirana, zhrň stream“ alebo „koľko krát
som dnes zomrel?“ dostane Mirana štatistiky (`[STREAM]`).

## Dlhodobá pamäť

`data/memory.json`: postup v hre (z telemetrie), história streamov (dĺžka, smrti, levely, questy, 2–3 momenty),
fakty o tebe a dohody a diváci z chatu (návštevy, sub/mod + 1–3 poznámky; nikdy osobné údaje).

- Postup v hre a štatistiky divákov sa zapisujú priebežne. Fakty, poznámky o divákoch a momenty zhrnie model
  (`longterm.model`, ~2–5 c za stream) každých 30 min a pri vypnutí; čo nestihne, doplní ďalší štart.
- Do promptu ide `[PAMÄŤ]` (hra, streamy, fakty; v cache) a pri otázke `[DIVÁCI]` len o divákoch, ktorí sú práve
  v chate alebo ich spomenieš (aj vyskloňovane: „Kuba“, „Kubovi“ = Kubo_SK). Divákov sama neoslovuje.
- Hlasom: „čo o mne vieš?“, „čo vieš o Kubovi?“, „zabudni Kuba“ (poznámky o divákovi), „zabudni, že…“.
- Vypnutie Mirany trvá o pár sekúnd dlhšie (ukladá pamäť, najviac ~25 s).

## Mirana vidí hru

Pri otázkach „čo je toto?“, „kto je to?“, „vidíš to?“, „pozri…“, „na čo sa pozerám?“ pošle modelu snímku **len okna
hry** (`vision.window_title`, nikdy celý monitor); na HUD prebehne „vizuálny sken“. Reč o teste, logoch, chate či
streame snímku nespustí („toto bol len test“). ~0,24 c za otázku, +0,2 s k prvej vete; snímka sa neukladá.
Hra musí bežať v okne alebo okne bez okrajov (pri exkluzívnej celej obrazovke je snímka čierna a nepošle sa).

## HUD

`http://localhost:8080`; na streamovacom notebooku OBS Browser Source `http://<IP herného PC>:8080`.
Rozlíšenie zdroja: celá obrazovka (1920×1080, HUD dole v strede), alebo v tvare panela, napr. **1960×300** —
vtedy HUD vyplní celý zdroj a v OBS sa dá ťahať za rohy. Efekty:

- prístup do databázy pri hľadaní vo wiki, vizuálny sken pri snímke hry
- banner pri leveli, dokončenom queste, smrti („FLATLINE #3“) a policajných hviezdach
- v hlavičke hviezdy polície a počítadlo smrtí za dnešok; pri kritickom HP červený tep, pri smrti záblesk

Všetky sa dajú vyskúšať v Nastaveniach → HUD → **Test efektov** (len vizuál, nič nepovie).

## Twitch chat

Mirana chat **len číta** (anonymne, bez bota, nič nepíše). Posledných 15 správ z 5 minút dostane ako `[CHAT]`
ku každej tvojej otázke; sama ich nekomentuje, len keď sa spýtaš („čo píše chat?“). Správy berie ako údaje,
nie pokyny; príkazy (`!…`) a boti sa preskočia.

## Konfigurácia

Všetko je v okne Nastavenia; priamo v `config.yaml` sú navyše napr.:

- `stt.local_vocabulary`: názvy z hry pre Whisper (max 224 tokenov)
- `tts.effects.params`: doladenie efektov hlasu; `phonetics.yaml`: ako vysloviť anglické názvy
- `vision.*`, `longterm.*`, `limits.*`, `fallback_phrases.*`, `logging.archive_after_days`

Predvolené hodnoty, rozsahy a popisy sú v `mirana/schema.py`; čo v `config.yaml` chýba, doplní sa predvolené.

## Logy

- `logs/mirana-<čas>.log`: celý beh session; `logs/supervisor.log`: reštarty
- `logs/rozhovor-<čas>.jsonl`: každá otázka (zdroj, otázka, kontext, odpoveď, časy, cena)
- `logs/chat-<čas>.jsonl`: Twitch chat (podklad pre pamäť)
- `logs/strih-<dátum>.md`: momenty na strih; `logs/poznamky.md`: „Mirana, zapíš si do logu…“
- `logs/archive/<rok-mesiac>.zip`: logy staršie ako 14 dní (pri štarte; posledné 4 sessions ostávajú vždy)
- `data/budget.json`: dnešná útrata, `data/stream_stats.json`: štatistiky dňa
