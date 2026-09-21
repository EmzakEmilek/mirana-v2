"""Orchestrator: event fronta, stavovy automat IDLE -> LISTENING -> PROCESSING -> SPEAKING.

Vstupy hadzu eventy do fronty, o poradi a fallbackoch rozhoduje jedine tento subor.
"""

import logging
import queue
from enum import Enum, auto

from core.brain import Brain
from core.config import load_config
from core.memory import Memory
from inputs.ptt import PushToTalk
from outputs.voice import Voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


class Mirana:
    """Sklada ptt -> brain -> voice."""

    def __init__(self, config: dict):
        self.config = config
        self.fallback = config["fallback_phrases"]
        self.state = State.IDLE
        self._events: queue.Queue = queue.Queue()

        self.memory = Memory(config)
        self.brain = Brain(config)
        self.voice = Voice(config)
        self.ptt = PushToTalk(
            config,
            on_start=lambda: self._events.put(("start", None)),
            on_recording=lambda wav: self._events.put(("recording", wav)),
        )

    def _set_state(self, state: State) -> None:
        self.state = state
        logger.info("stav: %s", state.name)

    def _say(self, text: str) -> None:
        self._set_state(State.SPEAKING)
        try:
            self.voice.say(text)
        except Exception:
            logger.exception("voice zlyhal")

    def _handle_start(self) -> None:
        if self.state is State.IDLE:
            self._set_state(State.LISTENING)

    def _handle_recording(self, wav_bytes: bytes) -> None:
        if self.state is not State.LISTENING:
            return
        try:
            self._process(wav_bytes)
        except Exception:
            logger.exception("neocakavana chyba pri spracovani")
            self._say(self.fallback["general_error"])
        finally:
            self._set_state(State.IDLE)

    def _process(self, wav_bytes: bytes) -> None:
        self._set_state(State.PROCESSING)
        game_state_line = None  # inputs/game_state.py pride vo Faze 4

        transcript = self.brain.transcribe(wav_bytes)
        if transcript is None:
            self._say(self.fallback["stt_failed"])
            return
        if not transcript.strip():
            return  # omylom stlacene F12 — ticho spat do IDLE
        logger.info("Erik: %s", transcript)

        user_text = f"[ERIK] {transcript}"  # tag zdroja podla persona.md
        answer = self.brain.ask(user_text, game_state_line, self.memory.as_messages())
        if answer is None:
            self._say(self.fallback["llm_failed"])
            return
        logger.info("Mirana: %s", answer)

        self.memory.add_exchange(user_text, answer)
        self._say(answer)

    def run(self) -> None:
        self.ptt.start()
        logger.info("Mirana bezi. Drz %s pre PTT.", self.config["audio"]["ptt_key"])

        while True:
            event, payload = self._events.get()
            if event == "start":
                self._handle_start()
            elif event == "recording":
                self._handle_recording(payload)


if __name__ == "__main__":
    Mirana(load_config()).run()
