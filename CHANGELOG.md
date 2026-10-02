# Zmeny

Podrobný denník práce je v [docs/PROGRESS.md](docs/PROGRESS.md), tu len čo sa zmenilo pre Erika.

## 2026-10-03 — prestavba programu (tri vlny)

**Spoľahlivosť**
- Kontrola pri štarte v ovládacom okne: nastavenia, kľúče, mikrofón, výstup, grafika, hra, CET a mod.
- Mod v hre sa aktualizuje sám, keď je v repe novší a hra nebeží.
- Zlá hodnota v `config.yaml` Miranu nezhodí: použije sa predvolená a okno povie, čo je zle.
- Úpravy pamäte z Nastavení zapíše bežiaca Mirana sama (predtým ich mohla prepísať).
- Súbory (rozpočet, štatistiky, pamäť, config, persona) sa zapisujú bezpečne aj pri páde.
- Logy staršie ako 14 dní idú pri štarte do `logs/archive/<mesiac>.zip` (nič sa nemaže).
- Opravená chyba v Nastaveniach: pri zlyhaní testu mikrofónu, výstupu alebo ukážky hlasu sa nezobrazila chyba.

**Správanie**
- Snímka obrazovky sa pýta polovicu zbytočných razov menej (28 → 14 z 218 otázok): „toto bol len test“,
  „pozri sa do chatu“ či „čo je to chladná hlava“ ju už nespustia.
- Divák sa nájde aj vyskloňovaný („zabudni Kuba“ = Kubo) a podľa časti nicku (Kubo_SK).
- „Napíš si do logu…“ sa zapíše do poznámok rovnako ako „zapíš si…“.
- „Koľko krát som dnes zomrel?“ dostane štatistiky streamu.
- Okno Nastavenia kontroluje všetky hodnoty podľa jedného zoznamu (rozsahy, voľby, rôzne tlačidlá).

**Odstránené**
- Azure Speech ako prepis reči (mená z hry prepisoval zle) a pripravené veci pre Kick chat.

**Pre vývoj**
- Balík `mirana/` (jadro + funkcie), `ui/` (okno), `docs/`; `main.py` a `gui.py` sú len spúšťače.
- 89 testov (`python -m pytest`), režim bez zvuku `MIRANA_NO_AUDIO=1`, pevné verzie knižníc.
- Popis stavby: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 2026-10-02 — Twitch a prvý stream

- Twitch chat len na čítanie, dual PC stream (HDMI → strihová karta), textová otázka v okne, posúvač hlasitosti.
- Fillery len na HUD, vtipná pripomienka po 10 min ticha, HUD priehľadný a ťahateľný v OBS.
- Hlas: robot efekt, rýchlosť +25 %, výška +15 %, poľské hlasy pre srandu; prirodzená slovenčina a nadávky v persone.
- Sonnet 5.5 low ako hlavný model (rýchlejší a lacnejší), wiki s predhľadaním článku (lore 2× rýchlejšie).
- Značky na strih (bočné tlačidlo), štatistiky streamu, efekty HUD (databáza, level, smrť, polícia, kritické HP).
- Mirana vidí hru (snímka okna hry pri „čo je toto?“).
- Dlhodobá pamäť: hra, streamy, fakty o Erikovi, diváci z chatu.

## 2026-09-26 — hra a okno

- Ovládacie okno s ikonou na ploche a Nastaveniami bez editovania súborov, supervisor s reštartom, panic mute.
- CET mod a telemetria (stav, svet, quest, príbeh, postava, výbava, cieľ, polícia, auto), hlášky pri udalostiach.
- Efekty hlasu, PTT na bočnom tlačidle myši, rýchlejšia reč (orezané ticho medzi vetami).

## 2026-09-20 až 23 — základ

- PTT → Whisper → Claude → Azure TTS, streaming po vetách, filler hlášky, barge-in, HUD v OBS.
- Persona (Friday), prompt cache, denný strop nákladov, logy rozhovorov.
