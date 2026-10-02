# MIRANA — POSTUP

Plán stavby. **[COWORK]** = Claude Cowork na hernom PC, **[CODE]** = Claude Code, **[ERIK]** = ty ručne.
✅ = hotové, ⏳ = zostáva. Stav k 2026-09-26.

---

## Rozdelenie strojov

| Herný PC (i7 10th, RTX 4060 Ti 16 GB, 32 GB) | Notebook (i5 9th, GTX 1660 Ti, 16 GB) |
|---|---|
| Cyberpunk 2077 (GOG) + CET + mod mirana_state | OBS + enkódovanie (NVENC) |
| Mirana (celý Python proces, ovládacie okno) | Browser Source: Mirana HUD |
| Whisper lokálne na GPU | Browser Source: donation bar |
| Efekty hlasu (v Mirane) → Voicemeeter | VoiceMeeter — príjem VBAN |
| Overlay server `:8080` | Capture karta (obraz hry) |
| Claude Code (vývoj) | |

Medzi strojmi vedú dve linky: **VBAN** (zvuk Mirany) a **WebSocket :8080** (dáta pre HUD).
Herný PC na kábli, nie Wi-Fi.

---

## Fáza 0 — Príprava ✅

1. ✅ **[COWORK]** Git, GitHub CLI, Python 3.12, VoiceMeeter Banana, Claude Code.
2. ✅ **[COWORK]** `C:\mirana-v2`, `git init`, `.gitignore`, `.env` šablóna, venv.
3. ✅ **[COWORK]** SPEC, persona, config, HUD na svojich miestach.
4. ✅ **[CODE]** CET 1.37.1 rozbalený do hry (GOG, hra 2.31).
5. ✅ **[COWORK]** Zoznam zvukových zariadení (`audio-devices.txt`).
6. ✅ **[ERIK]** `gh auth login`; repo je verejné: github.com/EmzakEmilek/mirana-v2.
7. ✅ **[ERIK]** API kľúče (Anthropic, Azure) v `.env`. OpenAI netreba (Whisper beží lokálne).
8. ⏳ **[ERIK]** Druhý mikrofón do herného PC (zatiaľ mikrofón slúchadiel G733).
9. ✅ **[ERIK]** Audio zariadenia vybrané v okne Nastavenia → Zvuk.
10. ✅ **[ERIK]** Cyberpunk beží, CET sa ozve, mod mirana_state zapisuje.

## Fáza 1 — Jadro ✅

11. ✅ **[CODE]** PTT → Whisper → Claude → Azure TTS → main (dnes Opus 5.5 low, streaming po vetách).
12. ✅ **[ERIK]** Testy tónu a výslovnosti (hlas Viktoria + fonetika anglických názvov).
13. ✅ **[CODE]** Repo na GitHube.

## Fáza 1b — Lokálny Whisper ✅

14. ✅ **[CODE]** `stt.provider: local|api`, faster-whisper `medium` na CUDA.
15. ✅ **[ERIK]** Slovenčina sedí, lokálny prepis natrvalo.

## Fáza 2 — Filler hlášky + barge-in ✅

16. ✅ **[CODE]** SPEC sekcia 3.
17. ✅ **[ERIK]** Po pustení tlačidla žiadne ticho; stlačenie uprostred odpovede ju preruší.

## Fáza 3 — Overlay ✅

18. ✅ **[CODE]** SPEC sekcia 4 — WebSocket server, HUD v4 (živé jadro).
19. ✅ **[ERIK]** `localhost:8080` v prehliadači.

## Fáza 4 — CET mod ✅ (okrem dlhodobej pamäte)

20. ✅ **[CODE]** SPEC sekcia 5, body 1–5 (mod v3, riadok [HRA], proaktívne hlášky).
21. ✅ **[ERIK]** Hra 2026-09-26: Mirana pozná quest, auto, políciu, cieľ; sama sa ozvala pri 3 hviezdach.
22. ⏳ **[ERIK]** Ďalšie hranie po oprave modu v3: skontrolovať liečenie („5 z 6"), počasie a log bez
    „CET mod: tieto udaje nejdu".
23. ⏳ **[CODE]** SPEC sekcia 5 bod 6 — `core/longterm.py` (po reštarte vie, kde Erik skončil).

## Fáza 5 — Kick chat ⏳

24. ⏳ **[COWORK]** Stiahne aktuálnu dokumentáciu z docs.kick.com do repa.
25. ⏳ **[ERIK]** Kick kľúče do `.env` (`KICK_CLIENT_ID`, `KICK_CLIENT_SECRET`, `KICK_CHANNEL_ID`).
26. ⏳ **[CODE]** SPEC sekcia 6.
27. ⏳ **[ERIK]** Test z druhého účtu — sub prejde, nesub dostane len vetu na HUD.

## Fáza 6 — Zvuk a napojenie notebooku (čiastočne)

28. ✅ **[CODE]** Efekty hlasu priamo v Mirane (`outputs/voice_fx.py`) — VST pluginy netreba.
    Preset sa vyberá v Nastaveniach → Hlas (teraz `robot`).
29. ✅ **[CODE]** Zvuk do streamu bez Voicemeeteru: Mirana hrá naraz do slúchadiel aj na predvolený výstup Windows
    (HDMI 24G1WG4 → strihová karta → notebook), `audio.stream_output_device: "default"`.
30. ⏳ **[ERIK]** Na notebooku overiť, že Miranu počuť v OBS (ide spolu so zvukom hry cez strihovú kartu).
31. ⏳ **[ERIK]** Notebook: OBS Browser Source na `http://192.168.1.110:8080` (herný PC, DHCP — ideálne rezervácia v routeri).
    **Shutdown source when not visible musí byť vypnuté** — inak zomrie WebSocket.
32. ✅ **[CODE]** Firewall na hernom PC: pravidlo „MIRANA HUD (TCP 8080)“, len LocalSubnet (2026-10-02). VBAN netreba.

## Fáza 7 — Hardening ✅ (okrem suchého behu)

33. ✅ **[CODE]** Budget cap, safety filter, supervisor, panic mute, logy, zámok proti 2 inštanciám.
34. ⏳ **[ERIK]** 8-hodinový suchý beh: Mirana + hra + mod + overlay (+ chat, ak bude). Sleduj RAM a chyby v logu.
35. ⏳ **[ERIK]** Prvý ostrý stream.

---

## Checklist pred každým streamom

- [ ] Herný PC: okno MIRANA svieti STANDBY, bez červených chýb; dnešná útrata ďaleko od stropu
- [ ] Cyberpunk beží, v okne je riadok „Hra: …" (mod posiela údaje)
- [ ] Testovacia otázka cez zadné bočné tlačidlo myši → počuť odpoveď s efektom
- [ ] Miranin hlas počuť aj na notebooku (OBS mixer, zvuk zo strihovej karty)
- [ ] Notebook: overlay v OBS svieti (stav STANDBY)
- [ ] V okne svieti „Chat: #kanál pripojený“ (Twitch)
- [ ] Vieš, kde je panic mute (predné bočné tlačidlo myši)

---

## Práca s Claude Code

1. Jeden prompt = jeden krok: „Postav len `inputs/kick_chat.py` podľa SPEC.md sekcia 6
   krok 1. Nič iné."
2. Po každom kroku to spustíš a overíš — Claude Code nepočuje reproduktory a nevidí hru.
3. Commit po každom funkčnom kroku.
4. Pri páde vkladaj celý traceback a log, alebo povedz „pozri log" (logs/ je v projekte).
5. Po každej fáze aktualizovať `PROGRESS.md`.
