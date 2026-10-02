"""Uprava config.yaml a persona.md z ovladacieho okna.

config.yaml ma v komentaroch vysvetlivky a vysledky testov — ruamel.yaml ich pri ulozeni zachova
(obycajny yaml.dump by ich zmazal). Pred kazdym ulozenim sa urobi zaloha data/config.yaml.bak.
"""

import io
import shutil

from ruamel.yaml import YAML

from mirana.config import BASE_DIR, CONFIG_PATH, PERSONA_PATH
from mirana.store import write_text_atomic

BACKUP_DIR = BASE_DIR / "data"


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # nezalamovat dlhe riadky s komentarmi
    y.indent(mapping=2, sequence=4, offset=2)
    y.representer.add_representer(type(None), lambda r, _: r.represent_scalar("tag:yaml.org,2002:null", "null"))
    return y


def load_editable():
    """config.yaml ako upravitelny strom (zachova komentare a poradie)."""
    return _yaml().load(CONFIG_PATH.read_text(encoding="utf-8"))


def save(data) -> None:
    BACKUP_DIR.mkdir(exist_ok=True)
    shutil.copy2(CONFIG_PATH, BACKUP_DIR / "config.yaml.bak")
    buf = io.StringIO()
    _yaml().dump(data, buf)
    write_text_atomic(CONFIG_PATH, buf.getvalue())


def load_persona() -> str:
    return PERSONA_PATH.read_text(encoding="utf-8")


def save_persona(text: str) -> None:
    BACKUP_DIR.mkdir(exist_ok=True)
    shutil.copy2(PERSONA_PATH, BACKUP_DIR / "persona.md.bak")
    write_text_atomic(PERSONA_PATH, text.rstrip() + "\n")
