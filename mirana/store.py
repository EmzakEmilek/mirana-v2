"""Ukladanie suborov na jednom mieste: bezpecny (atomicky) zapis a denne pocitadla.

Atomicky zapis = najprv docasny subor vedla, potom premenovanie. Pri pade alebo vypadku prudu tak
nikdy neostane napoly zapisany JSON (rozpocet, statistiky, pamat, config).
"""

import json
import logging
import os
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


def write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    """Obsah JSON suboru, alebo `default`, ked subor chyba alebo je poskodeny."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data, indent: int | None = None) -> bool:
    """Atomicky zapis JSON. False pri chybe (zaloguje ju), aby volajuci nepadol."""
    try:
        write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=indent))
        return True
    except OSError:
        logger.exception("subor %s sa neda zapisat", path)
        return False


def append_jsonl(path: Path, record: dict) -> None:
    """Riadok do .jsonl logu (append je bezpecny aj bez docasneho suboru)."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("zaznam do %s sa neda zapisat", path)


class DailyJson:
    """JSON so zaznamom pre dnesny den ({"day": "2026-10-02", ...}); novy den = cerstve hodnoty."""

    def __init__(self, path: Path, defaults: dict):
        self.path = Path(path)
        self.defaults = defaults
        self.data = self._load()

    def _fresh(self) -> dict:
        return {"day": date.today().isoformat(), **self.defaults}

    def _load(self) -> dict:
        data = read_json(self.path, {})
        if isinstance(data, dict) and data.get("day") == date.today().isoformat():
            return {**self._fresh(), **data}
        return self._fresh()

    def roll(self) -> None:
        """Volat pred citanim/zapisom — o polnoci zacne novy den."""
        if self.data.get("day") != date.today().isoformat():
            self.data = self._fresh()

    def save(self) -> bool:
        return write_json(self.path, self.data)
