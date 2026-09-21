"""Spolocne nacitanie config.yaml a .env — jediné miesto, ktoré pozná cesty v repe."""

from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
PERSONA_PATH = BASE_DIR / "persona.md"

load_dotenv(BASE_DIR / ".env")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_persona() -> str:
    return PERSONA_PATH.read_text(encoding="utf-8")
