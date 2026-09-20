"""Orchestrator: event fronta, stavovy automat IDLE -> LISTENING -> PROCESSING -> SPEAKING."""

import logging
import queue
import traceback
from enum import Enum, auto
from pathlib import Path

import yaml

from core.brain import Brain
from core.memory import Memory
from inputs.ptt import PushToTalk
from outputs.voice import Voice

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.yaml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mirana.main")


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class Mirana:
    """Sklada ptt -> brain -> voice. Vstupy hadzu eventy do fronty, o poradi rozhoduje tento main."""

    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self.state = State.IDLE
        self._events: queue.Queue = queue.Queue()

        self.memory = Memory(self.config)
        self.brain = Brain(self.config)
        self.voice = Voice(self.config)
        self.ptt = PushToTalk(
            self.config,
            on_start=self._on_ptt_start,
            on_recording=self._on_ptt_recording,
        )

    def _set_state(self, state: State) -> None:
        self.state = state
        logger.info("stav: %s", state.name)

    def _on_ptt_start(self) -> None:
        """Bezi na listener vlakne pynput — len zaradi event, ziadna tazka praca."""
        self._events.put(("start", None))

    def _on_ptt_recording(self, wav_bytes: bytes) -> None:
        """Bezi na listener vlakne pynput — len zaradi event, ziadna tazka praca."""
        self._events.put(("recording", wav_bytes))

    def _handle_start(self) -> None:
        if self.state is State.IDLE:
            self._set_state(State.LISTENING)

    def _handle_recording(self, wav_bytes: bytes) -> None:
        if self.state is not State.LISTENING:
            return

        self._set_state(State.PROCESSING)
        game_state_line = None  # inputs/game_state.py pride vo Faze 4

        try:
            transcript, answer = self.brain.process(wav_bytes, game_state_line, self.memory.as_messages())
        except Exception:
            logger.error("brain zlyhal:\n%s", traceback.format_exc())
            transcript, answer = None, self.config["fallback_phrases"]["general_error"]

        self._set_state(State.SPEAKING)
        try:
            self.voice.say(answer)
        except Exception:
            logger.error("voice zlyhal:\n%s", traceback.format_exc())

        if transcript is not None:
            self.memory.add_exchange(transcript, answer)

        self._set_state(State.IDLE)

    def run(self) -> None:
        self.ptt.start()
        logger.info("Mirana bezi. Drz %s pre PTT.", self.config["audio"]["ptt_key"])

        while True:
            try:
                event, payload = self._events.get()
                if event == "start":
                    self._handle_start()
                elif event == "recording":
                    self._handle_recording(payload)
            except Exception:
                logger.error("neocakavana chyba v hlavnej slucke:\n%s", traceback.format_exc())
                self._set_state(State.IDLE)


if __name__ == "__main__":
    Mirana().run()
