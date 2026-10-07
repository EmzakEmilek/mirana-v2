"""Jadro Mirany: fronta udalosti, stavovy automat IDLE -> LISTENING -> PROCESSING -> SPEAKING a otazky.

Vstupy (PTT, okno, hra) hadzu udalosti do fronty; o poradi, preruseniach, fallbackoch a kratkej
pamati rozhoduje jedine hlavna slucka tu. Vsetko ostatne (wiki, snimka hry, dlhodoba pamat, momenty
na strih, HUD, pripomienky, poznamky) su funkcie v mirana/features — jadro ich len vola.

STT + LLM bezia vo worker vlakne; odpoved sa streamuje po vetach do Speakera, ktory prvu vetu
hovori, kym model pise dalsie. Kazda otazka je Turn; barge-in (PTT pocas PROCESSING/SPEAKING)
ju zrusi — Speaker ju zahodi, stream sa prerusi a do pamate ide len to, co Erik stihol pocut.
Filler hlaska sa spusti z casovaca, ak prva veta nepride do fillers.skip_if_faster_than_ms.
"""

import logging
import queue
import threading
import time
from enum import Enum, auto

from mirana.budget import Budget
from mirana import config as config_module
from mirana import intents
from mirana.config import load_config
from mirana.events import Answered, Fallback, GameEvent, Interrupted, Quit, Recording, Silent, Spoken, Typed
from mirana.features.archive import LogArchive
from mirana.features.highlights import HighlightsFeature
from mirana.features.hud import Hud
from mirana.features.idle import IdleNudge
from mirana.features.longterm import LongTermFeature
from mirana.features.notes import Notes
from mirana.features.vision import VisionFeature
from mirana.features.wiki import Wiki, WikiFeature
from mirana.inputs.game_state import GameState
from mirana.inputs.ptt import PushToTalk
from mirana.inputs.twitch_chat import TwitchChat
from mirana.llm.brain import Answer, Brain
from mirana.memory import Memory
from mirana.outputs.fillers import Fillers
from mirana.outputs.overlay import Overlay
from mirana.outputs.speaker import Speaker
from mirana.outputs.voice import Voice
from mirana.safety import Safety
from mirana.session import HEARTBEAT_PATH, ConversationLog, ensure_single_instance, setup_logging
from mirana.turn import Turn

logger = logging.getLogger(__name__)

MAX_TYPED_CHARS = 500  # pisana otazka z ovladacieho okna

# Poradie je dolezite: momenty na strih zapocitaju smrt skor, nez HUD ukaze jej cislo.
FEATURES = (HighlightsFeature, Hud, LongTermFeature, WikiFeature, VisionFeature, IdleNudge, Notes, LogArchive)


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


class Mirana:
    """Sklada ptt -> brain -> speaker/voice -> overlay a vola funkcie (features)."""

    def __init__(self, config: dict, session_id: str):
        self.config = config
        self.session_id = session_id
        self.fallback = config["fallback_phrases"]
        self.state = State.IDLE
        self._lock = threading.Lock()  # chrani state, _gen a _turn (menia ich ptt, worker, speaker aj slucka)
        self._gen = 0
        self._turn: Turn | None = None
        self.muted = False             # panic mute: Mirana mlci a ignoruje PTT, kym sa panic klaves nestlaci znova
        self.last_proactive = 0.0      # cas poslednej hlasky z hernej udalosti
        self._last_erik = 0.0          # cas poslednej Erikovej otazky — proaktivne hlasky mu neskacu do reci
        self._pending_urgent = None    # (nazov, snapshot, text, cas) — kriticke HP pocas reci pocka, kym dohovori
        self.questions = 0
        self._events: queue.Queue = queue.Queue()

        self.conversation = ConversationLog(session_id)
        self.budget = Budget(config)
        self.memory = Memory(config)
        self.wiki = Wiki(config)
        self.brain = Brain(config, self.budget, self.wiki)
        self.voice = Voice(config)
        self.fillers = Fillers(config, self.voice)
        self.overlay = Overlay(config)
        self.voice.on_level = self.overlay.level
        self.speaker = Speaker(config, self.voice, self.overlay, on_start=self._on_speech_start,
                               on_done=lambda turn: self._events.put(Spoken(turn)), safety=Safety(config))
        self.ptt = PushToTalk(config, on_start=self._on_ptt_press,
                              on_recording=lambda wav: self._events.put(Recording(wav)))
        self.ptt.on_level = self.overlay.level
        self.ptt.on_panic = self._on_panic
        gs = config.get("game_state", {})
        self.speak_on = set(gs.get("speak_on", []))
        self.proactive_cooldown = config["limits"].get("proactive_cooldown_sec", 300)
        self.quiet_after_erik = gs.get("quiet_after_erik_sec", 30)
        self.game = GameState(config, on_event=self._on_game_event, on_snapshot=self._on_snapshot)
        self.chat = TwitchChat(config, on_message=self._on_chat, on_status=self.overlay.chat_status)
        self.overlay.on_command = self._on_command
        self.highlights = None  # nastavi HighlightsFeature (pocitadlo smrti a statistiky dna)
        self.longterm = None    # nastavi LongTermFeature (divaci pre karty v HUD v2)
        self.features = [feature(self) for feature in FEATURES]

    @property
    def status_name(self) -> str:
        return "muted" if self.muted else self.state.name.lower()

    def _set_state(self, state: State) -> None:
        self.state = state
        logger.info("stav: %s", state.name)
        self.overlay.state(state.name.lower())

    def _each(self, method: str, *args) -> None:
        """Zavola metodu vsetkych funkcii; chyba jednej nezastavi ostatne ani Miranu."""
        for feature in self.features:
            try:
                getattr(feature, method)(*args)
            except Exception:
                logger.exception("funkcia %s.%s zlyhala", type(feature).__name__, method)

    # --- vstupy (ich vlastne vlakna) ------------------------------------------------------------

    def _on_game_event(self, name: str, snap, text: str) -> None:
        """Vlakno hry: funkcie zapisu moment a ukazu efekt hned (aj ked Mirana mlci), hlasku riesi slucka."""
        for feature in self.features:
            try:
                text = feature.on_game_event(name, snap, text)
            except Exception:
                logger.exception("funkcia %s.on_game_event zlyhala", type(feature).__name__)
        self._events.put(GameEvent(name, snap, text))

    def _on_snapshot(self, snap) -> None:
        self._each("on_snapshot", snap)

    def _on_chat(self, msg) -> None:
        self._each("on_chat", msg)

    def _on_command(self, cmd: str, text: str | None = None) -> None:
        """Prikazy z ovladacieho okna (ui/control.py); co nepozna jadro, dostanu funkcie."""
        if cmd == "mute":
            self._on_panic()
        elif cmd == "quit":
            self._events.put(Quit())
        elif cmd == "ask" and text:
            self._events.put(Typed(text))
        elif cmd == "volume" and text:
            try:
                self.voice.volume = max(0.0, min(1.5, float(text) / 100))
            except ValueError:
                pass
        else:
            for feature in self.features:
                try:
                    if feature.on_command(cmd, text):
                        return
                except Exception:
                    logger.exception("prikaz %s zlyhal", cmd)

    def _cancel_current(self) -> None:
        """Zrusi bezucu otazku (volat pod self._lock): hlas stichne, stream sa zastavi, Speaker ju zahodi."""
        self._gen += 1
        turn = self._turn
        if turn is not None and not turn.cancelled:
            turn.cancelled = True
            self._cancel_filler(turn)
            self._events.put(Interrupted(turn))
        self.voice.stop()

    def _on_panic(self) -> None:
        """Panic mute: okamzite umlcat a pozastavit. Druhe stlacenie Miranu vrati."""
        with self._lock:
            self.muted = not self.muted
            if self.muted:
                self._cancel_current()
                self.state = State.IDLE
                self.overlay.state("muted")
                logger.warning("PANIC MUTE — Mirana mlci, PTT sa ignoruje. Znova panic klaves = spat.")
            else:
                self._set_state(State.IDLE)
                logger.info("panic mute vypnuty")

    def _on_ptt_press(self) -> None:
        """Bezi v pynput vlakne. Barge-in musi zastavit zvuk okamzite, nie az ked sa slucka uvolni."""
        with self._lock:
            if self.muted:
                return
            if self.state is State.IDLE:
                self._set_state(State.LISTENING)
                return
            if self.state in (State.PROCESSING, State.SPEAKING):
                logger.info("barge-in pocas %s", self.state.name)
                self._cancel_current()
                self._set_state(State.LISTENING)

    # --- start otazky -----------------------------------------------------------------------------

    def _start_turn(self, source: str, target, *args, allowed: tuple = (State.IDLE,), interrupt: bool = False,
                    filler: bool = False) -> Turn | None:
        """Novy Turn + worker vlakno target(turn, *args). None, ked Mirana mlci alebo je v stave mimo `allowed`.

        interrupt=True: beziaca odpoved sa zrusi (pisana otazka). filler=True: casovac fillera, ak prva
        veta nepride vcas. voice.arm() zrusi stop z predchadzajuceho barge-inu."""
        with self._lock:
            if self.muted:
                return None
            if interrupt and self.state in (State.PROCESSING, State.SPEAKING):
                logger.info("nova otazka prerusila %s", self.state.name)
                self._cancel_current()
            elif self.state not in allowed:
                return None
            self._set_state(State.PROCESSING)
            turn = Turn(gen=self._gen, source=source)
            self._turn = turn
        self.voice.arm()
        if filler and self.fillers.enabled:
            turn.filler_timer = threading.Timer(self.fillers.delay_sec, self._play_filler, args=(turn,))
            turn.filler_timer.start()
        threading.Thread(target=target, args=(turn, *args), name=f"turn-{source}", daemon=True).start()
        return turn

    def start_turn(self, source: str, text: str) -> Turn | None:
        """Hlaska z vlastneho popudu (udalost z hry, pripomienka) — len ked Mirana nic nerobi."""
        return self._start_turn(source, self._work_event, text)

    # --- worker vlakno ----------------------------------------------------------------------------

    def _work_voice(self, turn: Turn, wav_bytes: bytes) -> None:
        try:
            started = time.perf_counter()
            self.overlay.stage("prepis", "active")
            transcript = self.brain.transcribe(wav_bytes)
            turn.stt_sec = time.perf_counter() - started
            if transcript is None:
                self.overlay.stage("prepis", "fail")
                self._events.put(Fallback(turn, "stt_failed"))
                return
            self.overlay.stage("prepis", "done", round(turn.stt_sec, 1))
            if not transcript.strip():
                self._cancel_filler(turn)  # omylom stlacene PTT — ticho, bez fillera
                self._events.put(Silent(turn))
                return
            logger.info("Erik: %s  (STT %.1f s)", transcript, turn.stt_sec)
            self._erik_asks(turn, transcript)
        except Exception:
            logger.exception("neocakavana chyba vo workeri")
            self._events.put(Fallback(turn, "general_error"))

    def _work_typed(self, turn: Turn, text: str) -> None:
        try:
            logger.info("Erik (pisane): %s", text)
            self._erik_asks(turn, text)
        except Exception:
            logger.exception("neocakavana chyba pri pisanej otazke")
            self._events.put(Fallback(turn, "general_error"))

    def _work_event(self, turn: Turn, text: str) -> None:
        try:
            turn.question = text
            self._ask(turn)
        except Exception:
            logger.exception("chyba pri hlaske z vlastneho popudu")
            self._events.put(Fallback(turn, "general_error"))

    def _erik_asks(self, turn: Turn, text: str) -> None:
        turn.question = text
        self.overlay.erik(text)
        self._each("on_question", turn)
        if self.budget.exceeded():
            self._events.put(Fallback(turn, "budget_reached"))
            return
        self._last_erik = time.time()
        self.questions += 1
        self._ask(turn)

    def _ask(self, turn: Turn) -> None:
        """Kontext + LLM stream. Stav hry ide ako riadok [HRA] do spravy — v system prompte by kazda
        zmena HP zrusila cache pamate. Chat divakov ([CHAT]) ide len k Erikovym otazkam."""
        # nerozdelene body len k otazke na build — inak ich Mirana pripominala pri kazdej otazke
        turn.add("HRA", self.game.line(points=turn.from_erik and intents.asks_about_build(turn.question)))
        if turn.from_erik:
            turn.add("CHAT", self.chat.line())
        self._each("context", turn)
        turn.prompt = turn.build_prompt()
        turn.asked_at = time.perf_counter()
        if not turn.cancelled:
            self.overlay.stage("model", "active")
        answer = self.brain.ask_stream(
            turn.prompt, None, self.memory.as_messages(), image_b64=turn.image,
            on_sentence=lambda sentence: self._on_sentence(turn, sentence),
            should_stop=lambda: turn.cancelled,
            on_lookup=lambda title=None: self._on_lookup(turn, title),
            on_look=lambda: self._on_look(turn),
        )
        self._events.put(Answered(turn, answer, turn.stt_sec))

    def _on_lookup(self, turn: Turn, title: str | None = None) -> None:
        """Model hlada vo wiki: povie "hladam v databaze" a HUD ukaze pristup do databazy;
        po najdeni (title) HUD ukaze nazov clanku. Bezny filler uz netreba."""
        if turn.cancelled:
            return
        if title is not None:
            self.overlay.search(title)
            return
        self._cancel_filler(turn)
        with self._lock:
            current = turn.gen == self._gen and self.state is State.PROCESSING
        if current and not turn.started and not turn.searched:
            turn.searched = True
            spoken = self.fillers.play_search()  # nahlas len prva; na HUD sa pri dlhsom hladani stridaju
            self.overlay.search(None, self.fillers.search_lines(spoken))

    def _on_look(self, turn: Turn) -> None:
        """Model sa sam pozera na hru (nastroj obrazovka): HUD ukaze sken, filler uz netreba."""
        turn.looked = True
        if turn.cancelled:
            return
        self._cancel_filler(turn)
        from mirana.inputs.game_state import target_info
        self.overlay.scan(target_info(self.game.current))

    def _on_sentence(self, turn: Turn, sentence: str) -> None:
        if turn.cancelled:
            return
        if turn.first_sentence:
            turn.first_sentence = False
            self._cancel_filler(turn)
            self.overlay.stage("model", "done", round(time.perf_counter() - turn.asked_at, 1))
        extra: dict = {}
        self._each("on_sentence", turn, sentence, extra)  # zvyraznene slova a divaci pre HUD v2
        self.speaker.say(turn, sentence, extra)

    # --- speaker vlakno -----------------------------------------------------------------------

    def _on_speech_start(self, turn: Turn) -> None:
        with self._lock:
            if turn.cancelled or turn.gen != self._gen or self.state is not State.PROCESSING:
                return
            self._set_state(State.SPEAKING)
        logger.info("prvy zvuk %.1f s po pusteni PTT / udalosti", time.perf_counter() - turn.released_at)

    # --- fillery ------------------------------------------------------------------------------

    def _cancel_filler(self, turn: Turn) -> None:
        if turn.filler_timer is not None:
            turn.filler_timer.cancel()

    def _play_filler(self, turn: Turn) -> None:
        with self._lock:
            current = not turn.cancelled and turn.gen == self._gen and self.state is State.PROCESSING
        if current and not turn.started:
            line = self.fillers.play_random()
            if line:
                self.overlay.filler(line)

    # --- hlavna slucka ------------------------------------------------------------------------

    def _handle_typed(self, text: str) -> None:
        """Pisana otazka z ovladacieho okna: ako PTT, len bez nahravky a prepisu. Prerusi beziacu odpoved."""
        text = " ".join(text.split())[:MAX_TYPED_CHARS]
        if not text:
            return
        if self._start_turn("typed", self._work_typed, text, allowed=tuple(State), interrupt=True,
                            filler=True) is None:
            logger.info("pisana otazka ignorovana, Mirana je stlmena: %s", text)
            self.overlay.notice("Mirana je stlmená, otázka sa neposlala. Zapni hlas a pošli ju znova.")

    def _handle_game_event(self, name: str, snap, text: str) -> None:
        """Proaktivna hlaska: len ked Mirana mlci a nie hned po Erikovej otazke; max raz za cooldown.
        Kriticke HP a smrt maju vynimku z cooldownu. Pocas sceny (rozhovor, cutscena) do hry nevstupuje."""
        if name not in self.speak_on or self.muted or self.budget.exceeded():
            return
        urgent = name in ("hp_critical", "death")
        if not urgent and snap.in_scene:
            logger.info("herna udalost %s bez hlasky (scena)", name)
            return
        now = time.time()
        if not urgent and (now - self.last_proactive < self.proactive_cooldown or now - self._last_erik < self.quiet_after_erik):
            logger.info("herna udalost %s bez hlasky (cooldown)", name)
            return
        if self.start_turn("game", text) is None:
            if urgent:  # povie ju hned, ako dohovori (Spoken aj tato funkcia bezia v hlavnej slucke)
                self._pending_urgent = (name, snap, text, now)
            return
        self._pending_urgent = None
        if not urgent:  # urgentna hlaska (kriticke HP) nema blokovat bezne hlasky na 5 minut
            self.last_proactive = now

    def _remember(self, turn: Turn, interrupted: bool) -> None:
        """Do pamate ide to, co Erik naozaj pocul — pri preruseni len vyslovene vety."""
        if turn.remembered or not turn.remember or turn.prompt is None:
            return
        if interrupted:
            if not turn.spoken:
                return  # nepocul nic, otazka ako keby nebola
            text = " ".join(turn.spoken) + " …"
        elif turn.answer is not None and turn.answer.text:
            text = turn.answer.text
        else:
            return
        turn.remembered = True
        self.memory.add_exchange(turn.tagged, text)
        self._each("on_answer", turn, text)

    def _handle_event(self, event) -> None:
        match event:
            case Recording(wav):
                self._start_turn("voice", self._work_voice, wav, allowed=(State.LISTENING,), filler=True)
            case Typed(text):
                self._handle_typed(text)
            case GameEvent(name, snap, text):
                self._handle_game_event(name, snap, text)
            case Interrupted(turn):
                self._remember(turn, interrupted=True)
            case Spoken(turn):
                self._remember(turn, interrupted=False)
                with self._lock:
                    if turn.gen == self._gen and self.state in (State.PROCESSING, State.SPEAKING):
                        self._set_state(State.IDLE)
                pending, self._pending_urgent = self._pending_urgent, None
                if pending and time.time() - pending[3] < 10:
                    self._handle_game_event(*pending[:3])
            case Answered(turn, answer):
                self._handle_answer(turn, answer)
            case Silent(turn) if not turn.cancelled and turn.gen == self._gen:
                with self._lock:
                    if self.state is State.PROCESSING:
                        self._set_state(State.IDLE)
            case Fallback(turn, reason) if not turn.cancelled and turn.gen == self._gen:
                logger.info("fallback: %s", reason)
                turn.remember = False
                self._cancel_filler(turn)
                self.speaker.say_all(turn, self.fallback[reason])

    def _handle_answer(self, turn: Turn, answer: Answer) -> None:
        turn.answer = answer
        self.overlay.budget(self.budget.spent, self.budget.cap)
        self.conversation.write(
            zdroj=turn.source, otazka=turn.question, kontext=turn.context, obrazovka=bool(turn.image) or turn.looked,
            mirana=answer.text, model=answer.model, stop=answer.stop_reason, wiki=answer.lookups,
            stt_s=round(turn.stt_sec, 2), prva_veta_s=answer.first_sentence_sec and round(answer.first_sentence_sec, 2),
            spolu_s=round(answer.total_sec, 2), usd=round(answer.cost, 5), prerusene=turn.cancelled,
            chyba=answer.error,
        )
        if turn.cancelled:
            return
        logger.info("Mirana: %s", answer.text)
        if not answer.ok and not answer.sentences:
            turn.remember = False
            if turn.from_erik:
                self.speaker.say_all(turn, self.fallback["llm_failed"])
            else:
                self.speaker.end(turn)  # hlaska z vlastneho popudu: model nemal co povedat -> ticho, nie "vypadol Net"
            return
        self.speaker.end(turn)

    def run(self) -> None:
        self.overlay.start()
        self._each("start")
        self.game.start()
        self.chat.start()
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
                event = self._events.get(timeout=5)
            except queue.Empty:
                self._each("tick")
                continue
            if isinstance(event, Quit):
                logger.info("vypnutie z ovladacieho okna")
                self.voice.stop()
                self._each("shutdown")
                return
            try:
                self._handle_event(event)
            except Exception:
                logger.exception("chyba v hlavnej slucke (%s)", type(event).__name__)


def main() -> None:
    ensure_single_instance()
    cfg = load_config()
    session_id = setup_logging(cfg)
    for problem in config_module.problems:
        logger.warning("config: %s", problem)
    try:
        Mirana(cfg, session_id).run()
    except KeyboardInterrupt:
        logger.info("Mirana vypnuta (Ctrl+C)")
