# Prompt pre Cowork — Fáza 0

Najprv stiahni do `Downloads`: `SPEC.md`, `persona.md`, `config.yaml`,
`overlay-index.html`, `env.example.txt`, `gitignore.txt`.

Potom vlož Coworku (spustenému na hernom PC) tento prompt celý:

---

```
Pripravuješ projekt Mirana na tomto počítači (herný PC, Windows).
Urob všetko, čo sa dá, bez môjho zásahu. Kde treba mňa, zastav a povedz mi to.

NIKDY: nevypĺňaj registračné formuláre, nezadávaj moje údaje ani kartu,
a nikdy nečítaj ani nepíš hodnoty API kľúčov.

1. INŠTALÁCIE
   Použi winget (spoľahlivejšie než klikanie v inštalátoroch):
     winget install --id Git.Git -e
     winget install --id GitHub.cli -e
     winget install --id Python.Python.3.12 -e
     winget install --id VB-Audio.Voicemeeter.Banana -e
   Potom Claude Code cez PowerShell:
     irm https://claude.ai/install.ps1 | iex
   Po inštaláciách otvor NOVÝ PowerShell a over verzie:
     git --version, gh --version, python --version, claude --version
   Ak niektorý príkaz nie je rozpoznaný, napíš mi to.

2. PRIEČINOK PROJEKTU
   Vytvor C:\mirana-v2 a v ňom podpriečinky:
   inputs, core, outputs, overlay, mod, fillers
   Spusti v ňom: git init

3. SÚBORY ZO STIAHNUTÝCH
   Z priečinka Downloads presuň do C:\mirana-v2:
     SPEC.md              -> SPEC.md
     persona.md           -> persona.md
     config.yaml          -> config.yaml
     overlay-index.html   -> overlay\index.html      (premenuj)
     gitignore.txt        -> .gitignore              (premenuj)
     env.example.txt      -> .env                    (premenuj, hodnoty nechaj prázdne)

4. PYTHON PROSTREDIE
   V C:\mirana-v2 vytvor venv a over, že sa aktivuje:
     python -m venv venv
     .\venv\Scripts\activate
   Nainštaluj základ:
     pip install python-dotenv PyYAML sounddevice soundfile numpy pynput

5. AUDIO ZARIADENIA
   Spusti: python -m sounddevice
   Vypíš mi celý zoznam a počkaj, kým ti poviem, ktoré je druhý mikrofón
   a ktoré je VoiceMeeter Input. Potom ich zapíš do config.yaml
   (audio.input_device a audio.output_device).

6. CYBER ENGINE TWEAKS
   Nájdi priečinok Cyberpunk 2077 (hľadaj Cyberpunk2077.exe, typicky
   ...\steamapps\common\Cyberpunk 2077\bin\x64\). Povedz mi, akú cestu si našiel,
   a počkaj na moje potvrdenie.
   Po potvrdení stiahni najnovší release z
   https://github.com/maximegmd/CyberEngineTweaks/releases a rozbaľ obsah
   do toho bin\x64 priečinka.

7. PROGRESS.md
   Vytvor C:\mirana-v2\PROGRESS.md: dátum, čo je nainštalované, verzie nástrojov,
   cesty (projekt, hra), sekcia "Čaká na Erika", sekcia "Stav fáz".

8. ZÁVEREČNÁ SPRÁVA
   Vypíš mi stručne:
   - čo prešlo a čo zlyhalo
   - zoznam audio zariadení z kroku 5
   - cestu k hre z kroku 6
   - čo musím urobiť ja
```

---

## Po dobehnutí Coworku — tvoje štyri kroky

1. `gh auth login` — prihlásenie cez prehliadač
2. API kľúče (Anthropic, OpenAI, Azure) ručne do `C:\mirana-v2\.env`
3. Reštart PC po VoiceMeeteri, zapojiť druhý mikrofón, overiť vo Windows Sound
4. Spustiť Cyberpunk, overiť že sa CET ozve

Potom ideš do Claude Code na Fázu 1.
