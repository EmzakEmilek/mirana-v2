"""Spolocne nacitanie config.yaml a .env — jediné miesto, ktoré pozná cesty v repe.

Predvolene hodnoty, typy a rozsahy su v mirana/schema.py; config.yaml moze byt aj neuplny.
"""

import logging
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
PERSONA_PATH = BASE_DIR / "persona.md"

load_dotenv(BASE_DIR / ".env")

# problemy z posledneho load_config() — loguje ich Mirana pri starte, ukazuje diagnostika v okne
problems: list[str] = []


def load_config(path: Path | None = None) -> dict:
    """Uplny config: hodnoty z config.yaml doplnene predvolenymi, zle hodnoty nahradene predvolenymi."""
    from mirana import schema

    global problems
    try:
        with open(path or CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raw, problems = {}, [f"config.yaml sa nedá prečítať ({e}) — Mirana ide s predvolenými nastaveniami"]
        logging.getLogger(__name__).error(problems[0])
        cfg, more = schema.resolve(raw)
        problems += more
        return cfg
    cfg, problems = schema.resolve(raw)
    return cfg


def load_persona() -> str:
    return PERSONA_PATH.read_text(encoding="utf-8")
