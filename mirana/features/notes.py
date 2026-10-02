""""Mirana, zapis si do logu, ze ..." -> logs/poznamky.md (podklad na upravy Mirany po streame)."""

import logging
import time

from mirana import intents
from mirana.config import BASE_DIR
from mirana.features import Feature

logger = logging.getLogger(__name__)

NOTES_PATH = BASE_DIR / "logs" / "poznamky.md"


def save_note(text: str) -> bool:
    if not intents.wants_note(text):
        return False
    NOTES_PATH.parent.mkdir(exist_ok=True)
    with NOTES_PATH.open("a", encoding="utf-8") as f:
        f.write(f"- {time.strftime('%Y-%m-%d %H:%M')} {text}\n")
    logger.info("poznamka ulozena do %s", NOTES_PATH.name)
    return True


class Notes(Feature):
    def on_question(self, turn) -> None:
        save_note(turn.question)
