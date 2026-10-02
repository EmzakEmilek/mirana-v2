"""Kontrola pri starte: co by Mirane chybalo, skor nez sa to prejavi na streame.

Spusta ju ovladacie okno pri otvoreni (vysledok vypise do okna) a mod v hre zaroven aktualizuje,
ak je v repe novsi a hra nebezi. Kazda kontrola je samostatna — chyba jednej nezastavi ostatne.
Kluce z .env sa len overia, ze existuju; ich hodnoty sa nikdy necitaju do vystupu.
"""

import os
from dataclasses import dataclass

from mirana.config import BASE_DIR, PERSONA_PATH


@dataclass
class Check:
    ok: bool
    name: str
    detail: str = ""


def _audio(cfg: dict) -> list[Check]:
    import sounddevice as sd

    from mirana.outputs.voice import resolve_output
    out = []
    device = cfg["audio"]["input_device"]
    try:
        name = sd.query_devices(device, "input")["name"] if device else sd.query_devices(kind="input")["name"]
        out.append(Check(True, "Mikrofón", name))
    except Exception as e:
        out.append(Check(False, "Mikrofón", f"{device or 'predvolený'} sa nenašiel ({e}) — vyber ho v Nastaveniach"))
    for key, label in (("output_device", "Výstup"), ("stream_output_device", "Výstup pre stream")):
        spec = cfg["audio"][key]
        if not spec:
            continue
        try:
            out.append(Check(True, label, sd.query_devices(resolve_output(spec))["name"]))
        except Exception as e:
            out.append(Check(False, label, f"{spec} sa nenašiel ({e})"))
    return out


def _cuda(cfg: dict) -> list[Check]:
    stt = cfg["stt"]
    if stt["provider"] != "local" or stt["local_device"] != "cuda":
        return []
    from mirana.llm.stt import _register_cuda_dlls
    _register_cuda_dlls()
    import ctranslate2
    n = ctranslate2.get_cuda_device_count()
    return [Check(n > 0, "Grafika pre Whisper", "CUDA v poriadku" if n else "CUDA nenájdená — prepis pôjde pomaly na CPU")]


def _game(cfg: dict) -> list[Check]:
    if not cfg["game_state"]["enabled"]:
        return []
    from mirana.inputs.game_state import MOD_SOURCE, MOD_SUBDIR, cet_installed, find_game_dir, mod_version, update_mod
    game = find_game_dir()
    if game is None:
        return [Check(False, "Hra", "Cyberpunk 2077 sa nenašiel — Mirana pôjde bez telemetrie")]
    if not cet_installed(game):
        return [Check(False, "Hra", "chýba Cyber Engine Tweaks — Mirana pôjde bez telemetrie")]
    message = update_mod(game)
    installed, repo = mod_version(game / MOD_SUBDIR / "init.lua"), mod_version(MOD_SOURCE / "init.lua")
    ok = installed is not None and installed >= (repo or 0)
    return [Check(ok, "Mod v hre", message or (f"mirana_state v{installed}" if ok else "mod nie je nainštalovaný"))]


def _files(cfg: dict) -> list[Check]:
    out = []
    try:
        persona_ok = bool(PERSONA_PATH.read_text(encoding="utf-8").strip())
    except OSError:
        persona_ok = False
    out.append(Check(persona_ok, "Persona", "persona.md" if persona_ok else "persona.md chýba alebo je prázdna"))
    phonetics = cfg["tts"]["phonetics_file"]
    if phonetics and not (BASE_DIR / phonetics).exists():
        out.append(Check(False, "Fonetika", f"{phonetics} chýba — názvy z hry bude čítať po anglicky"))
    return out


def _keys(cfg: dict) -> list[Check]:
    needed = {"ANTHROPIC_API_KEY": "model (Claude)", "AZURE_SPEECH_KEY": "hlas (Azure)", "AZURE_SPEECH_REGION": "hlas (Azure)"}
    if cfg["stt"]["provider"] == "api":
        needed["OPENAI_API_KEY"] = "prepis (OpenAI Whisper)"
    missing = [f"{name} ({what})" for name, what in needed.items() if not os.environ.get(name)]
    return [Check(not missing, "Kľúče v .env", "chýba " + ", ".join(missing) if missing else "v poriadku")]


def run_checks(cfg: dict, config_problems: list[str]) -> list[Check]:
    checks = [Check(False, "Nastavenia", p) for p in config_problems] or [Check(True, "Nastavenia", "v poriadku")]
    for part in (_keys, _files, _audio, _cuda, _game):
        try:
            checks += part(cfg)
        except Exception as e:
            checks.append(Check(False, part.__name__.strip("_"), f"kontrola zlyhala: {e}"))
    return checks
