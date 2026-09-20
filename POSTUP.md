# MIRANA — POSTUP

Finálny plán stavby. **[COWORK]** = Claude Cowork na hernom PC,
**[CODE]** = Claude Code, **[ERIK]** = ty ručne.

---

## Rozdelenie strojov

| Herný PC (i7 10th, RTX 4060 Ti 16 GB, 32 GB) | Notebook (i5 9th, GTX 1660 Ti, 16 GB) |
|---|---|
| Cyberpunk 2077 + CET mod | OBS + enkódovanie (NVENC) |
| Mirana (celý Python proces) | Browser Source: Mirana HUD |
| Druhý mikrofón (PTT) | Browser Source: donation bar |
| Whisper (ak lokálny) | VoiceMeeter — príjem VBAN |
| VoiceMeeter + VST reťaz (DSP) | Capture karta (obraz hry) |
| Overlay server `:8080` | |
| Claude Code (vývoj) | |

Medzi strojmi vedú dve linky: **VBAN** (zvuk Mirany) a **WebSocket :8080** (dáta pre HUD).
Herný PC na kábli, nie Wi-Fi.

---

## Fáza 0 — Príprava (~1,5 h)

1. **[COWORK]** Nainštaluje Git, GitHub CLI, Python 3.12, VoiceMeeter Banana (winget)
   a Claude Code (PowerShell). Overí verzie.
2. **[COWORK]** Vytvorí `C:\mirana-v2` + podpriečinky, `git init`, `.gitignore`,
   `.env` šablónu, venv so základnými balíkmi.
3. **[COWORK]** Presunie z Downloads: `SPEC.md`, `persona.md`, `config.yaml`,
   `overlay-index.html` → `overlay\index.html`.
4. **[COWORK]** Nájde priečinok Cyberpunku, po potvrdení rozbalí CET do `bin\x64`.
5. **[COWORK]** Spustí `python -m sounddevice`, vypíše zariadenia.
6. **[ERIK]** `gh auth login` cez prehliadač.
7. **[ERIK]** Účty a API kľúče (Anthropic, OpenAI, Azure) → ručne do `.env`.
8. **[ERIK]** Reštart PC po VoiceMeeteri. Zapojí druhý mikrofón, overí vo Windows Sound.
9. **[ERIK]** Určí audio zariadenia → Cowork ich zapíše do `config.yaml`.
10. **[ERIK]** Spustí Cyberpunk, overí že sa CET ozve.

## Fáza 1 — Jadro

11. **[CODE]** Päť promptov podľa SPEC sekcia 2 (PTT → Whisper API → Sonnet → Azure TTS → main).
12. **[ERIK]** Test: drž F12, povedz vetu, počuj odpoveď. Polož 10 otázok o Cyberpunku,
    over tón persóny.
13. **[CODE]** `gh repo create mirana-v2 --private --source=. --push`

## Fáza 1b — Lokálny Whisper

14. **[CODE]** Implementuje prepínač `stt.provider: local|api`, faster-whisper `medium` na CUDA.
15. **[ERIK]** Porovná 20 otázok oproti API. Sadne slovenčina → prepni natrvalo,
    zruš OpenAI účet. Nesadne → späť na `api`.

## Fáza 2 — Filler hlášky + barge-in

16. **[CODE]** SPEC sekcia 3.
17. **[ERIK]** Test: po pustení klávesy žiadne ticho; stlačenie uprostred odpovede ju preruší.

## Fáza 3 — Overlay

18. **[CODE]** SPEC sekcia 4 — WebSocket server, napojenie na hotový HUD.
    **Vzhľad HUD-u neupravovať.**
19. **[ERIK]** Otvorí `localhost:8080` v prehliadači na hernom PC, položí otázku,
    sleduje titulky a stav.

## Fáza 4 — CET mod

20. **[CODE]** SPEC sekcia 5.
21. **[ERIK]** Spustí Cyberpunk, hrá 2 min, overí že sa JSON mení a že Mirana pozná
    quest bez toho, aby ho povedal. Nechá klesnúť HP pod 25 % — musí sa ozvať sama.

## Fáza 5 — Kick chat

22. **[COWORK]** Stiahne aktuálnu dokumentáciu z docs.kick.com do repa.
23. **[CODE]** SPEC sekcia 6.
24. **[ERIK]** Test z druhého účtu — sub prejde, nesub nie.

## Fáza 6 — Zvuk a napojenie notebooku

25. **[COWORK]** Stiahne free VST pluginy (bitcrusher, ring mod, EQ, limiter).
26. **[ERIK]** Herný PC: `voice.py` hrá do VoiceMeeter Input, VST reťaz na kanáli,
    VBAN send `VoiceToStream` na IP notebooku.
27. **[ERIK]** Notebook: VoiceMeeter VBAN receive → OBS Audio Input Capture
    ako samostatná stopa.
28. **[ERIK]** Notebook: OBS Browser Source na `http://IP-herného-PC:8080`.
    **Shutdown source when not visible musí byť vypnuté** — inak zomrie WebSocket.
29. **[ERIK]** Firewall na hernom PC: TCP 8080 a UDP 6980, obe len Private.
    Statická IP alebo DHCP rezervácia pre herný PC.

## Fáza 7 — Hardening

30. **[CODE]** SPEC sekcia 8 — budget cap, safety filter, supervisor, panic mute F11.
31. **[ERIK]** 8-hodinový suchý beh: skript + hra + mod + overlay + chat.
    Sleduj RAM a chyby v logu.
32. **[ERIK]** Prvý ostrý stream.

---

## Checklist pred každým streamom

- [ ] Herný PC: Mirana beží (okno bez červených chýb)
- [ ] Cyberpunk beží, CET načítaný, `mirana_state.json` sa mení
- [ ] Testovacia otázka cez F12 → počuť odpoveď
- [ ] Notebook: overlay v OBS svieti (stav IDLE)
- [ ] Miranin hlas vidno v OBS audio mixeri
- [ ] Kick chat pripojený
- [ ] Vieš, kde je panic mute (F11)

---

## Práca s Claude Code

1. Jeden prompt = jeden krok: „Postav len `inputs/ptt.py` podľa SPEC.md sekcia 2
   krok 1. Nič iné."
2. Po každom kroku to spustíš a overíš — Claude Code nepočuje reproduktory.
3. Commit po každom funkčnom kroku, tag po fáze (`v0.1-core`, `v0.2-fillers`…).
4. Pri páde vkladaj celý traceback a log, nie parafrázu.
5. Po každej fáze nechaj Cowork aktualizovať `PROGRESS.md`.
