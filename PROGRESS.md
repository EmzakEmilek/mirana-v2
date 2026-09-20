# Mirana v2 - PROGRESS

Datum setupu: 2026-09-20
Projekt: C:\mirana-v2
Repo: mirana-v2 (privatne, zatial nevytvorene na GitHube)

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

venv balicky: python-dotenv, PyYAML, sounddevice, soundfile, numpy, pynput

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

## Podklady (HOTOVE, 2026-09-20)
- SPEC.md, persona.md, config.yaml, POSTUP.md, COWORK-FAZA-0.md ulozene v korene
- overlay/index.html (diegeticky HUD) ulozeny
- .gitignore prepisany na plnu verziu (+ *.pyc, mirana_state.json)
- .env.example ulozeny (obsahuje aj KICK_* pre Fazu 5)
- config.yaml: audio.output_device predvyplnene na
  "Voicemeeter Input (VB-Audio Voicemeeter VAIO)"; input_device ostava null

## Caka na Erika
- [ ] gh auth login (+ vytvorit privatne repo mirana-v2)
- [ ] pridat do .env riadky KICK_CLIENT_ID / KICK_CLIENT_SECRET / KICK_CHANNEL_ID
      (rucne - .env sa neda zapisovat vzdialene; predloha je v .env.example)
- [ ] doplnit API kluce do .env (ANTHROPIC_API_KEY, OPENAI_API_KEY, AZURE_SPEECH_KEY)
- [ ] nainstalovat Cyberpunk 2077, potom CyberEngineTweaks
- [ ] pripojit druhy mikrofon do herneho PC (odlozene)
- [ ] potvrdit audio routing vyssie
