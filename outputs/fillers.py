"""Filler hlasky: kratke WAV zakryvaju ticho medzi pustenim PTT a odpovedou.

Pri prvom spusteni sa vygeneruju cez TTS do fillers/*.wav (len chybajuce). Prehravanie je
neblokujuce — bezi z casovaca v main.py, kym worker cakal na Whisper a Claude.
"""

import logging
import random
import re
import unicodedata
from pathlib import Path

import numpy as np

from core.config import BASE_DIR
from outputs.voice import Voice

logger = logging.getLogger(__name__)

FILLERS_DIR = BASE_DIR / "fillers"


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")


class Fillers:
    """Nacita (alebo vygeneruje) hlasky z config fillers.lines a prehrava nahodnu, nikdy tu istu 2x po sebe."""

    def __init__(self, config: dict, voice: Voice):
        cfg = config["fillers"]
        self.enabled = cfg["enabled"]
        self.delay_sec = cfg["skip_if_faster_than_ms"] / 1000
        self._voice = voice
        self._clips: list[tuple[str, np.ndarray]] = []
        self._last_index: int | None = None
        if self.enabled:
            self._load(cfg["lines"])

    def _load(self, lines: list[str]) -> None:
        FILLERS_DIR.mkdir(exist_ok=True)
        generated = 0
        for i, line in enumerate(lines, 1):
            path = FILLERS_DIR / f"{i:02d}_{_slug(line)}.wav"
            if not path.exists():
                path.write_bytes(self._voice.synthesize(line, timeout=15))
                generated += 1
            self._clips.append((line, self._voice.to_device_audio(path.read_bytes())))
        logger.info("fillery: %d hlasok (%d novo vygenerovanych)", len(self._clips), generated)

    def play_random(self) -> str | None:
        """Neblokujuce prehratie nahodnej hlasky (ina nez naposledy). Vrati jej text pre HUD."""
        if not self._clips:
            return None
        choices = [i for i in range(len(self._clips)) if i != self._last_index] or [0]
        self._last_index = random.choice(choices)
        line, audio = self._clips[self._last_index]
        logger.info("filler: %s", line)
        self._voice.play_audio(audio, block=False)
        return line

    def wait(self) -> None:
        """Pocka, kym hlaska dohra — odpoved nesmie zacat cez nu."""
        self._voice.wait()

    def stop(self) -> None:
        self._voice.stop()
