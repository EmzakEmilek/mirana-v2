"""Orchestrator: event fronta, stavovy automat IDLE -> LISTENING -> PROCESSING -> SPEAKING.

Vstupy hadzu eventy do fronty, o poradi a fallbackoch rozhoduje jedine tento subor.

Faza 2: STT + LLM bezia vo worker vlakne, aby slucka ostala responzivna. Kazda uloha ma
generaciu; barge-in (F12 pocas PROCESSING/SPEAKING) generaciu zvysi, takze vysledok starej
ulohy sa zahodi. Filler hlaska sa spusti z casovaca, ak odpoved nepride do
fillers.skip_if_faster_than_ms.
"""

import logging
import queue
import threading
from dataclasses import dataclass
from enum import Enum, auto

from core.brain import Brain
from core.config import load_config
from core.memory import Memory
from inputs.ptt import PushToTalk
from outputs.fillers import Fillers
from outputs.overlay import Overlay
from outputs.voice import Voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


@dataclass
class Job:
    gen: int
    filler_timer: threading.Timer | None = None


class Mirana:
    """Sklada ptt -> brain -> voice."""

    def __init__(self, config: dict):
        self.config = config
        self.fallback = config["fallback_phrases"]
        self.state = State.IDLE
        self._lock = threading.Lock()  # chrani state a _gen (menia ich 3 vlakna: ptt, worker, slucka)
        self._gen = 0
        self._events: queue.Queue = queue.Queue()

        self.memory = Memory(config)
        self.brain = Brain(config)
        self.voice = Voice(config)
        self.fillers = Fillers(config, self.voice)
        self.overlay = Overlay(config)
        self.ptt = PushToTalk(
            config,
            on_start=self._on_ptt_press,
            on_recording=lambda wav: self._events.put(("recording", wav)),
        )

    def _set_state(self, state: State) -> None:
        self.state = state
        logger.info("stav: %s", state.name)
        self.overlay.state(state.name.lower())

    # --- PTT vlakno ---------------------------------------------------------------------------

    def _on_ptt_press(self) -> None:
        """Bezi v pynput vlakne. Barge-in musi zastavit zvuk okamzite, nie az ked sa slucka uvolni."""
        with self._lock:
            if self.state is State.IDLE:
                self._set_state(State.LISTENING)
                return
            if self.state in (State.PROCESSING, State.SPEAKING):
                self._gen += 1  # bezucu ulohu zahodime, jej vysledok uz nikto neprehra
                logger.info("barge-in pocas %s", self.state.name)
                self.voice.stop()
                self._set_state(State.LISTENING)

    # --- worker vlakno ------------------------------------------------------------------------

    def _work(self, job: Job, wav_bytes: bytes) -> None:
        """STT -> LLM. Vysledok posiela do fronty, slucka rozhodne, ci je este aktualny."""
        try:
            transcript = self.brain.transcribe(wav_bytes)
            if transcript is None:
                self._events.put(("fallback", job, "stt_failed"))
                return
            if not transcript.strip():
                self._cancel_filler(job)  # omylom stlacene F12 — ticho, bez fillera
                self._events.put(("silent", job, None))
                return
            logger.info("Erik: %s", transcript)

            user_text = f"[ERIK] {transcript}"  # tag zdroja podla persona.md
            game_state_line = None  # inputs/game_state.py pride vo Faze 4
            answer = self.brain.ask(user_text, game_state_line, self.memory.as_messages())
            if answer is None:
                self._events.put(("fallback", job, "llm_failed"))
                return
            self._events.put(("answer", job, (user_text, answer)))
        except Exception:
            logger.exception("neocakavana chyba vo workeri")
            self._events.put(("fallback", job, "general_error"))

    # --- hlavna slucka ------------------------------------------------------------------------

    def _is_current(self, job: Job) -> bool:
        with self._lock:
            return job.gen == self._gen and self.state is State.PROCESSING

    def _cancel_filler(self, job: Job) -> None:
        if job.filler_timer is not None:
            job.filler_timer.cancel()

    def _play_filler(self, job: Job) -> None:
        if self._is_current(job):
            line = self.fillers.play_random()
            if line:
                self.overlay.filler(line)

    def _handle_recording(self, wav_bytes: bytes) -> None:
        with self._lock:
            if self.state is not State.LISTENING:
                return
            self._set_state(State.PROCESSING)
            job = Job(gen=self._gen)
        if self.fillers.enabled:
            job.filler_timer = threading.Timer(self.fillers.delay_sec, self._play_filler, args=(job,))
            job.filler_timer.start()
        threading.Thread(target=self._work, args=(job, wav_bytes), daemon=True).start()

    def _say(self, job: Job, text: str) -> None:
        """Prehra odpoved, ak je uloha stale aktualna. Barge-in pocas reci ju zastavi z PTT vlakna."""
        self._cancel_filler(job)
        with self._lock:
            if job.gen != self._gen or self.state is not State.PROCESSING:
                return
            self._set_state(State.SPEAKING)
        try:
            audio = self.voice.to_device_audio(self.voice.synthesize(text))
            self.fillers.wait()  # nech filler dohra, odpoved nesmie zacat cez neho
            with self._lock:
                if job.gen != self._gen:
                    return
            self.overlay.answer(text)  # HUD pise sucasne s hlasom; Erikova otazka sa nezobrazuje
            self.voice.play_audio(audio, block=True)
        except Exception:
            logger.exception("voice zlyhal")
        finally:
            with self._lock:
                if job.gen == self._gen and self.state is State.SPEAKING:
                    self._set_state(State.IDLE)

    def _handle_result(self, event: str, job: Job, payload) -> None:
        if not self._is_current(job):
            logger.info("vysledok zahodeny (barge-in)")
            return
        if event == "silent":
            with self._lock:
                self._set_state(State.IDLE)
        elif event == "fallback":
            self._say(job, self.fallback[payload])
        elif event == "answer":
            user_text, answer = payload
            logger.info("Mirana: %s", answer)
            self.memory.add_exchange(user_text, answer)
            self._say(job, answer)

    def run(self) -> None:
        self.overlay.start()
        self.ptt.start()
        logger.info("Mirana bezi. Drz %s pre PTT.", self.config["audio"]["ptt_key"])

        while True:
            event, *rest = self._events.get()
            if event == "recording":
                self._handle_recording(rest[0])
            else:
                self._handle_result(event, *rest)


if __name__ == "__main__":
    Mirana(load_config()).run()
