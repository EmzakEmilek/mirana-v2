"""Orchestrator: event fronta, stavovy automat IDLE -> LISTENING -> PROCESSING -> SPEAKING.

Vstupy hadzu eventy do fronty, o poradi, fallbackoch a pamati rozhoduje jedine tento subor.

STT + LLM bezia vo worker vlakne; odpoved sa streamuje po vetach do Speakera, ktory prvu vetu
hovori, kym model pise dalsie. Kazda otazka je Job; barge-in (F12 pocas PROCESSING/SPEAKING)
job zrusi — Speaker ho zahodi, stream sa preruší a do pamate ide len to, co Erik stihol pocut.
Filler hlaska sa spusti z casovaca, ak prva veta nepride do fillers.skip_if_faster_than_ms.
"""

import os
import sys

# Spustenie z ikony (pythonw.exe) nema konzolu: sys.stdout/stderr su None a niektore kniznice
# (tqdm pri stahovani modelu, print) by padli. Vystup ide do prazdna, vsetko podstatne je v logs/.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto

from core.brain import Answer, Brain
from core.budget import Budget
from core.config import load_config
from core.memory import Memory
from core.safety import Safety
from core.session import HEARTBEAT_PATH, ConversationLog, ensure_single_instance, setup_logging
from inputs.game_state import GameState, event_text
from inputs.ptt import PushToTalk
from outputs.fillers import Fillers
from outputs.overlay import Overlay
from outputs.speaker import Speaker
from outputs.voice import Voice

logger = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


@dataclass
class Job:
    gen: int
    released_at: float                       # pustenie F12 — od neho meriame cas do prveho zvuku
    filler_timer: threading.Timer | None = None
    cancelled: bool = False                  # barge-in; cita ho Speaker aj stream v Brain
    started: bool = False                    # prva veta uz znie (nastavuje Speaker)
    tts_failed: bool = False
    first_sentence: bool = True
    remember: bool = True                    # fallback hlasky sa do pamate nedavaju
    user_text: str | None = None
    answer: Answer | None = None
    spoken: list[str] = field(default_factory=list)
    remembered: bool = False


class Mirana:
    """Sklada ptt -> brain -> speaker/voice -> overlay."""

    def __init__(self, config: dict, session_id: str):
        self.config = config
        self.fallback = config["fallback_phrases"]
        self.state = State.IDLE
        self._lock = threading.Lock()  # chrani state, _gen a _job (menia ich ptt, worker, speaker aj slucka)
        self._gen = 0
        self._job: Job | None = None
        self._muted = False            # panic mute (F11): Mirana mlci a ignoruje F12, kym sa F11 nestlaci znova
        self._last_proactive = 0.0     # cas poslednej hlasky z hernej udalosti
        self._last_erik = 0.0          # cas poslednej Erikovej otazky — proaktivne hlasky mu neskacu do reci
        self._telemetry_shown = None   # posledny stav poslany na HUD (posiela sa len zmena)
        self._pending_urgent = None    # (nazov, snapshot, cas) — kriticke HP pocas reci pocka, kym dohovori
        self._events: queue.Queue = queue.Queue()

        self.conversation = ConversationLog(session_id)
        self.budget = Budget(config)
        self.memory = Memory(config)
        self.brain = Brain(config, self.budget)
        self.voice = Voice(config)
        self.fillers = Fillers(config, self.voice)
        self.overlay = Overlay(config)
        self.voice.on_level = self.overlay.level
        self.speaker = Speaker(config, self.voice, self.overlay, on_start=self._on_speech_start,
                               on_done=lambda job: self._events.put(("spoken", job)), safety=Safety(config))
        self.ptt = PushToTalk(
            config,
            on_start=self._on_ptt_press,
            on_recording=lambda wav: self._events.put(("recording", wav)),
        )
        self.ptt.on_level = self.overlay.level
        gs = config.get("game_state", {})
        self.speak_on = set(gs.get("speak_on", []))
        self.proactive_cooldown = config["limits"].get("proactive_cooldown_sec", 300)
        self.quiet_after_erik = gs.get("quiet_after_erik_sec", 30)
        self.game = GameState(config, on_event=lambda name, snap: self._events.put(("game_event", None, (name, snap))),
                              on_snapshot=self._on_game_snapshot)
        self.ptt.on_panic = self._on_panic
        self.overlay.on_command = self._on_command

    def _set_state(self, state: State) -> None:
        self.state = state
        logger.info("stav: %s", state.name)
        self.overlay.state(state.name.lower())

    # --- PTT vlakno ---------------------------------------------------------------------------

    def _cancel_current(self) -> None:
        """Zrusi bezucu otazku (volat pod self._lock): hlas stichne, stream sa zastavi, Speaker ju zahodi."""
        self._gen += 1
        job = self._job
        if job is not None and not job.cancelled:
            job.cancelled = True
            self._cancel_filler(job)
            self._events.put(("interrupted", job))
        self.voice.stop()

    def _on_panic(self) -> None:
        """F11: okamzite umlcat a pozastavit. Druhe stlacenie Miranu vrati."""
        with self._lock:
            self._muted = not self._muted
            if self._muted:
                self._cancel_current()
                self.state = State.IDLE
                self.overlay.state("muted")
                logger.warning("PANIC MUTE (F11) — Mirana mlci, F12 sa ignoruje. Znova F11 = spat.")
            else:
                self._set_state(State.IDLE)
                logger.info("panic mute vypnuty")

    def _on_command(self, cmd: str) -> None:
        """Prikazy z ovladacieho okna (gui.py)."""
        if cmd == "mute":
            self._on_panic()
        elif cmd == "quit":
            self._events.put(("quit",))

    def _on_ptt_press(self) -> None:
        """Bezi v pynput vlakne. Barge-in musi zastavit zvuk okamzite, nie az ked sa slucka uvolni."""
        with self._lock:
            if self._muted:
                return
            if self.state is State.IDLE:
                self._set_state(State.LISTENING)
                return
            if self.state in (State.PROCESSING, State.SPEAKING):
                logger.info("barge-in pocas %s", self.state.name)
                self._cancel_current()
                self._set_state(State.LISTENING)

    # --- worker vlakno ------------------------------------------------------------------------

    def _work(self, job: Job, wav_bytes: bytes) -> None:
        """STT -> LLM stream. Vety idu rovno do Speakera, vysledok do fronty."""
        try:
            stt_started = time.perf_counter()
            transcript = self.brain.transcribe(wav_bytes)
            stt_sec = time.perf_counter() - stt_started
            if transcript is None:
                self._events.put(("fallback", job, "stt_failed"))
                return
            if not transcript.strip():
                self._cancel_filler(job)  # omylom stlacene F12 — ticho, bez fillera
                self._events.put(("silent", job, None))
                return
            logger.info("Erik: %s  (STT %.1f s)", transcript, stt_sec)
            self.overlay.erik(transcript)
            if self.budget.exceeded():
                self._events.put(("fallback", job, "budget_reached"))
                return

            self._last_erik = time.time()
            self._ask(job, f"[ERIK] {transcript}", stt_sec)  # tag zdroja podla persona.md
        except Exception:
            logger.exception("neocakavana chyba vo workeri")
            self._events.put(("fallback", job, "general_error"))

    def _ask(self, job: Job, tagged_text: str, stt_sec: float = 0.0) -> None:
        """LLM stream. Stav hry ide ako riadok [HRA] na zaciatok spravy — v system prompte by
        kazda zmena HP zrusila cache pamate, v sprave sa ulozi do historie a cache nerusi."""
        line = self.game.line()
        job.user_text = f"{line}\n{tagged_text}" if line else tagged_text
        answer = self.brain.ask_stream(
            job.user_text, None, self.memory.as_messages(),
            on_sentence=lambda sentence: self._on_sentence(job, sentence),
            should_stop=lambda: job.cancelled,
        )
        self._events.put(("answer", job, (answer, stt_sec)))

    def _work_game_event(self, job: Job, name: str, snap) -> None:
        try:
            self._ask(job, f"[GAME_EVENT] {event_text(name, snap)}")
        except Exception:
            logger.exception("chyba pri hernej udalosti")
            self._events.put(("fallback", job, "general_error"))

    # --- telemetria (vlakno game-state) ---------------------------------------------------------

    def _on_game_snapshot(self, snap) -> None:
        shown = (snap.location, snap.get("quest") or "", bool(snap.get("combat"))) if snap else ("", "", False)
        if shown != self._telemetry_shown:
            self._telemetry_shown = shown
            self.overlay.telemetry(*shown)
            self.overlay.game(live=snap is not None, line=self.game.line())

    def _handle_game_event(self, name: str, snap) -> None:
        """Proaktivna hlaska: len ked Mirana mlci a nie hned po Erikovej otazke; max raz za cooldown.
        Kriticke HP a smrt maju vynimku z cooldownu."""
        if name not in self.speak_on or self._muted or self.budget.exceeded():
            return
        urgent = name in ("hp_critical", "death")
        now = time.time()
        if not urgent and (now - self._last_proactive < self.proactive_cooldown or now - self._last_erik < self.quiet_after_erik):
            logger.info("herna udalost %s bez hlasky (cooldown)", name)
            return
        with self._lock:
            if self.state is not State.IDLE:
                if urgent:
                    self._pending_urgent = (name, snap, now)  # povie ju hned, ako dohovori
                return
            self._set_state(State.PROCESSING)
            job = Job(gen=self._gen, released_at=time.perf_counter())
            self._job = job
        self._pending_urgent = None
        if not urgent:  # urgentna hlaska (kriticke HP) nema blokovat bezne hlasky na 5 minut
            self._last_proactive = now
        self.voice.arm()
        threading.Thread(target=self._work_game_event, args=(job, name, snap), daemon=True).start()

    def _on_sentence(self, job: Job, sentence: str) -> None:
        if job.cancelled:
            return
        if job.first_sentence:
            job.first_sentence = False
            self._cancel_filler(job)
        self.speaker.say(job, sentence)

    # --- speaker vlakno -----------------------------------------------------------------------

    def _on_speech_start(self, job: Job) -> None:
        with self._lock:
            if job.cancelled or job.gen != self._gen or self.state is not State.PROCESSING:
                return
            self._set_state(State.SPEAKING)
        logger.info("prvy zvuk %.1f s po pusteni F12 / udalosti", time.perf_counter() - job.released_at)

    # --- hlavna slucka ------------------------------------------------------------------------

    def _cancel_filler(self, job: Job) -> None:
        if job.filler_timer is not None:
            job.filler_timer.cancel()

    def _play_filler(self, job: Job) -> None:
        with self._lock:
            current = not job.cancelled and job.gen == self._gen and self.state is State.PROCESSING
        if current and not job.started:
            line = self.fillers.play_random()
            if line:
                self.overlay.filler(line)

    def _handle_recording(self, wav_bytes: bytes) -> None:
        with self._lock:
            if self.state is not State.LISTENING:
                return
            self._set_state(State.PROCESSING)
            job = Job(gen=self._gen, released_at=time.perf_counter())
            self._job = job
        self.voice.arm()  # novy job: zrus stop z predchadzajuceho barge-inu
        if self.fillers.enabled:
            job.filler_timer = threading.Timer(self.fillers.delay_sec, self._play_filler, args=(job,))
            job.filler_timer.start()
        threading.Thread(target=self._work, args=(job, wav_bytes), daemon=True).start()

    def _remember(self, job: Job, interrupted: bool) -> None:
        """Do pamate ide to, co Erik naozaj pocul — pri preruseni len vyslovene vety."""
        if job.remembered or not job.remember or job.user_text is None:
            return
        if interrupted:
            if not job.spoken:
                return  # nepocul nic, otazka ako keby nebola
            text = " ".join(job.spoken) + " …"
        elif job.answer is not None and job.answer.text:
            text = job.answer.text
        else:
            return
        job.remembered = True
        self.memory.add_exchange(job.user_text, text)

    def _handle_event(self, event: str, job: Job, payload) -> None:
        if event == "game_event":
            self._handle_game_event(*payload)
            return
        if event == "interrupted":
            self._remember(job, interrupted=True)
            return
        if event == "spoken":
            self._remember(job, interrupted=False)
            with self._lock:
                if job.gen == self._gen and self.state in (State.PROCESSING, State.SPEAKING):
                    self._set_state(State.IDLE)
            pending, self._pending_urgent = self._pending_urgent, None
            if pending and time.time() - pending[2] < 10:
                self._handle_game_event(pending[0], pending[1])
            return
        if event == "answer":
            answer, stt_sec = payload
            job.answer = answer
            self.overlay.budget(self.budget.spent, self.budget.cap)
            self.conversation.write(
                erik=job.user_text, mirana=answer.text, model=answer.model, stop=answer.stop_reason,
                stt_s=round(stt_sec, 2), prva_veta_s=answer.first_sentence_sec and round(answer.first_sentence_sec, 2),
                spolu_s=round(answer.total_sec, 2), usd=round(answer.cost, 5), prerusene=job.cancelled,
                chyba=answer.error,
            )
            if job.cancelled:
                return
            logger.info("Mirana: %s", answer.text)
            if not answer.ok and not answer.sentences:
                job.remember = False
                self.speaker.say_all(job, self.fallback["llm_failed"])
                return
            self.speaker.end(job)
            return
        if job.cancelled or job.gen != self._gen:
            return
        if event == "silent":
            with self._lock:
                if self.state is State.PROCESSING:
                    self._set_state(State.IDLE)
        elif event == "fallback":
            logger.info("fallback: %s", payload)
            job.remember = False
            self._cancel_filler(job)
            self.speaker.say_all(job, self.fallback[payload])

    def run(self) -> None:
        self.overlay.start()
        self.game.start()
        self.ptt.start()
        logger.info("Mirana bezi (%s, effort %s). Drz %s pre PTT. Dnes minute $%.3f z $%.2f.",
                    self.config["llm"]["model"], self.config["llm"]["effort"], self.config["audio"]["ptt_key"],
                    self.budget.spent, self.budget.cap)

        self.overlay.state("idle")  # pociatocny stav pre HUD aj okno (inak by prisiel az pri prvej zmene)
        self.overlay.budget(self.budget.spent, self.budget.cap)
        self.overlay.info(model=self.config["llm"]["model"], effort=self.config["llm"]["effort"])
        HEARTBEAT_PATH.parent.mkdir(exist_ok=True)
        while True:
            HEARTBEAT_PATH.write_text(str(time.time()))  # run.py podla neho pozna zamrznutie
            try:
                event, *rest = self._events.get(timeout=5)
            except queue.Empty:
                continue
            if event == "quit":
                logger.info("vypnutie z ovladacieho okna")
                self.voice.stop()
                return
            try:
                if event == "recording":
                    self._handle_recording(rest[0])
                else:
                    job, payload = (rest + [None])[:2]
                    self._handle_event(event, job, payload)
            except Exception:
                logger.exception("chyba v hlavnej slucke (%s)", event)


if __name__ == "__main__":
    ensure_single_instance()
    cfg = load_config()
    try:
        Mirana(cfg, setup_logging(cfg)).run()
    except KeyboardInterrupt:
        logger.info("Mirana vypnuta (Ctrl+C)")
