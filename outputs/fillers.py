"""Filler hlasky: kratke WAV zakryvaju ticho medzi pustenim PTT a odpovedou.

fillers.speak: false = hlaska sa len ukaze na HUD, nahlas sa nepovie (a WAV sa ani negeneruju).

Pri prvom spusteni sa vygeneruju cez TTS do fillers/*.wav (len chybajuce). Prehravanie je
neblokujuce — bezi z casovaca v main.py, kym worker cakal na Whisper a Claude.
"""

import logging
import random
import re
import unicodedata

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
        self.speak = cfg.get("speak", True)
        self._voice = voice
        self._clips: list[tuple[str, np.ndarray | None]] = []
        self._last_index: int | None = None
        self._search: list[tuple[str, np.ndarray]] = []
        self._last_search: int | None = None
        if cfg.get("search_lines"):  # pri hladani vo wiki, vzdy nahlas (hladanie trva par sekund)
            self._search = self._load_clips(cfg["search_lines"], "search_")
        if self.enabled and self.speak:
            self._load(cfg["lines"])
        elif self.enabled:
            self._clips = [(line, None) for line in cfg["lines"]]
            logger.info("fillery: %d hlasok, len na HUD (bez hlasu)", len(self._clips))

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

    def _load_clips(self, lines: list[str], prefix: str) -> list[tuple[str, np.ndarray]]:
        FILLERS_DIR.mkdir(exist_ok=True)
        clips = []
        for i, line in enumerate(lines, 1):
            path = FILLERS_DIR / f"{prefix}{i:02d}_{_slug(line)}.wav"
            try:
                if not path.exists():
                    path.write_bytes(self._voice.synthesize(line, timeout=15))
                clips.append((line, self._voice.to_device_audio(path.read_bytes())))
            except Exception as e:
                logger.warning("hlaska %r sa nevygenerovala: %s", line, e)
        logger.info("hlasky pri hladani: %d", len(clips))
        return clips

    def play_search(self) -> str | None:
        """Hlaska "hladam v databaze" — nahlas, neblokujuco, ina nez naposledy."""
        if not self._search:
            return None
        choices = [i for i in range(len(self._search)) if i != self._last_search] or [0]
        self._last_search = random.choice(choices)
        line, audio = self._search[self._last_search]
        logger.info("hladanie: %s", line)
        self._voice.play_audio(audio, block=False)
        return line

    def search_lines(self, first: str | None = None) -> list[str]:
        """Vsetky hlasky pri hladani, `first` na zaciatku — HUD ich pri dlhsom hladani strieda (bez hlasu)."""
        lines = [line for line, _ in self._search]
        if first in lines:
            i = lines.index(first)
            lines = lines[i:] + lines[:i]
        return lines

    def play_random(self) -> str | None:
        """Neblokujuce prehratie nahodnej hlasky (ina nez naposledy; bez hlasu, ked speak=false). Vrati text pre HUD."""
        if not self._clips:
            return None
        choices = [i for i in range(len(self._clips)) if i != self._last_index] or [0]
        self._last_index = random.choice(choices)
        line, audio = self._clips[self._last_index]
        logger.info("filler: %s%s", line, "" if audio is not None else " (len HUD)")
        if audio is not None:
            self._voice.play_audio(audio, block=False)
        return line

    def wait(self) -> None:
        """Pocka, kym hlaska dohra — odpoved nesmie zacat cez nu."""
        self._voice.wait()

    def stop(self) -> None:
        self._voice.stop()
