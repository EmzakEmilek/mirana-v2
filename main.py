"""Orchestrator: event fronta, stavovy automat IDLE -> LISTENING -> PROCESSING -> SPEAKING.

Vstupy hadzu eventy do fronty, o poradi, fallbackoch a pamati rozhoduje jedine tento subor.

STT + LLM bezia vo worker vlakne; odpoved sa streamuje po vetach do Speakera, ktory prvu vetu
hovori, kym model pise dalsie. Kazda otazka je Job; barge-in (PTT pocas PROCESSING/SPEAKING)
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
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto

from core.brain import Answer, Brain
from core.events import (Answered, Fallback, GameEvent, Interrupted, Quit, Recording, Silent,
                         Spoken, Typed)
from core.highlights import Highlights
from core.longterm import LongTermMemory
from core.budget import Budget
from core.config import BASE_DIR, load_config
from core.memory import Memory
from core.safety import Safety
from core.vision import Vision
from core.session import HEARTBEAT_PATH, ConversationLog, ensure_single_instance, setup_logging
from inputs.game_state import GameState
from inputs.twitch_chat import TwitchChat
from inputs.ptt import PushToTalk
from outputs.fillers import Fillers
from outputs.overlay import Overlay
from outputs.speaker import Speaker
from outputs.voice import Voice

logger = logging.getLogger(__name__)

MAX_TYPED_CHARS = 500  # pisana otazka z ovladacieho okna
NOTE_VERB = re.compile(r"zap[ií]š|zapis|poznač|poznac|zaznač|zaznac", re.I)
NOTE_PLACE = re.compile(r"do logu|log|poznám|poznam", re.I)
NOTES_PATH = BASE_DIR / "logs" / "poznamky.md"
FORGET = re.compile(r"\bzabudni\b", re.I)  # "Mirana, zabudni Kuba" / "zabudni, ze nemam rad stealth"
STREAM_WORDS = re.compile(r"stream|zhr[nň]|dnes", re.I)  # otazka o streame -> riadok [STREAM] so statistikami


def save_note(text: str) -> None:
    """"Mirana, zapis si do logu, ze ..." -> logs/poznamky.md (podklad na upravy Mirany)."""
    if NOTE_VERB.search(text) and NOTE_PLACE.search(text):
        NOTES_PATH.parent.mkdir(exist_ok=True)
        with NOTES_PATH.open("a", encoding="utf-8") as f:
            f.write(f"- {time.strftime('%Y-%m-%d %H:%M')} {text}\n")
        logger.info("poznamka ulozena do %s", NOTES_PATH.name)


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


@dataclass
class Job:
    gen: int
    released_at: float                       # pustenie PTT — od neho meriame cas do prveho zvuku
    filler_timer: threading.Timer | None = None
    cancelled: bool = False                  # barge-in; cita ho Speaker aj stream v Brain
    started: bool = False                    # prva veta uz znie (nastavuje Speaker)
    tts_failed: bool = False
    first_sentence: bool = True
    searched: bool = False                   # hlaska "hladam v databaze" uz zaznela
    remember: bool = True                    # fallback hlasky sa do pamate nedavaju
    user_text: str | None = None             # cela sprava pre model ([HRA] + [CHAT] + otazka)
    tagged_text: str | None = None           # len otazka/udalost — ide do pamate
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
        self._muted = False            # panic mute: Mirana mlci a ignoruje PTT, kym sa panic klaves nestlaci znova
        self._last_proactive = 0.0     # cas poslednej hlasky z hernej udalosti
        self._last_erik = 0.0          # cas poslednej Erikovej otazky — proaktivne hlasky mu neskacu do reci
        idle = config.get("idle_nudge", {})
        self.idle_enabled = idle.get("enabled", False)
        self.idle_after = float(idle.get("after_min", 10)) * 60
        self.idle_max_in_row = int(idle.get("max_in_row", 3))
        self._idle_since = time.time()  # posledna Erikova otazka alebo start — od toho sa meria ticho
        self._last_nudge = 0.0
        self._nudges_in_row = 0         # pripomienky bez Erikovej reakcie; po max_in_row Mirana zmlkne (je asi AFK)
        self._telemetry_shown = None   # posledny stav poslany na HUD (posiela sa len zmena)
        self._game_line_shown = None
        self._pending_urgent = None    # (nazov, snapshot, text, cas) — kriticke HP pocas reci pocka, kym dohovori
        self._events: queue.Queue = queue.Queue()

        self.conversation = ConversationLog(session_id)
        self.highlights = Highlights(config)
        self.longterm = LongTermMemory(config, session_id)
        self._longterm_game_at = 0.0
        self.vision = Vision(config)
        self._questions = 0
        self._last_exchange = ("", "")  # posledna otazka a odpoved — kontext k znacke na strih
        self.budget = Budget(config)
        self.memory = Memory(config)
        self.brain = Brain(config, self.budget)
        self.brain.memory_block = lambda: self.longterm.block
        self.voice = Voice(config)
        self.fillers = Fillers(config, self.voice)
        self.overlay = Overlay(config)
        self.voice.on_level = self.overlay.level
        self.speaker = Speaker(config, self.voice, self.overlay, on_start=self._on_speech_start,
                               on_done=lambda job: self._events.put(Spoken(job)), safety=Safety(config))
        self.ptt = PushToTalk(
            config,
            on_start=self._on_ptt_press,
            on_recording=lambda wav: self._events.put(Recording(wav)),
        )
        self.ptt.on_level = self.overlay.level
        if hasattr(self.brain.stt, "begin"):  # Azure: prepis bezi uz pocas drzania PTT
            self.ptt.stream_stt = self.brain.stt
        gs = config.get("game_state", {})
        self.speak_on = set(gs.get("speak_on", []))
        self.proactive_cooldown = config["limits"].get("proactive_cooldown_sec", 300)
        self.quiet_after_erik = gs.get("quiet_after_erik_sec", 30)
        self.game = GameState(config, on_event=lambda name, snap, text: self._events.put(
                                  GameEvent(name, snap, self._record_game_event(name, snap, text))),
                              on_snapshot=self._on_game_snapshot)
        self.chat = TwitchChat(config, on_message=self._on_chat,
                               on_status=self.overlay.chat_status)
        self.ptt.on_panic = self._on_panic
        self.ptt.on_marker = self._on_marker
        self.hp_critical = gs.get("hp_critical_threshold", 10)
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
            self._events.put(Interrupted(job))
        self.voice.stop()

    def _on_panic(self) -> None:
        """Panic mute: okamzite umlcat a pozastavit. Druhe stlacenie Miranu vrati."""
        with self._lock:
            self._muted = not self._muted
            if self._muted:
                self._cancel_current()
                self.state = State.IDLE
                self.overlay.state("muted")
                logger.warning("PANIC MUTE — Mirana mlci, PTT sa ignoruje. Znova panic klaves = spat.")
            else:
                self._set_state(State.IDLE)
                logger.info("panic mute vypnuty")

    def _on_chat(self, msg) -> None:
        self.longterm.add_chat(msg)

    def _save_stream(self) -> None:
        minutes = int((time.time() - self.highlights.session_start) // 60)
        self.longterm.update_stream(self.highlights.stats, minutes)

    def _on_marker(self) -> None:
        """Bocne tlacidlo: moment na strih. Sietove volanie (cas streamu) mimo hooku mysi."""
        def work():
            snap = self.game.current
            where = ", ".join(x for x in ((snap.location if snap else ""), (snap.quest if snap else "") or "") if x)
            question, answer = self._last_exchange
            context = " · ".join(x for x in (where, f"Erik: {question}" if question else "",
                                             f"Mirana: {answer[:120]}" if answer else "") if x)
            when = self.highlights.add("marker", context or "bez kontextu", refresh=True)
            self.overlay.notice(f"◆ Značka na strih: {when}")
        threading.Thread(target=work, name="marker", daemon=True).start()

    def _hud_test(self, kind: str) -> None:
        """Ukazka efektu na HUD z okna Nastavenia -> HUD. Len vizual: ziadny model, hlas ani zapis do statistik."""
        ov = self.overlay
        snap = self.game.current
        base = {"location": (snap.location if snap else "") or "Watson, Kabuki",
                "quest": (snap.quest if snap else "") or "Jízda"}

        def restore(after: float) -> None:
            time.sleep(after)
            self._telemetry_shown = None  # dalsi snimok z hry posle skutocny stav
            if snap is None:
                ov.telemetry(deaths=self.highlights.deaths)
            ov.state("muted" if self._muted else self.state.name.lower())

        if kind == "level":
            ov.game_fx("level_up", "LEVEL 7")
        elif kind == "quest":
            ov.game_fx("quest_completed", "QUEST DOKONČENÝ")
        elif kind == "death":
            ov.telemetry(**base, deaths=self.highlights.deaths + 1)
            ov.game_fx("death", f"FLATLINE #{self.highlights.deaths + 1}")
            restore(5)
        elif kind == "police":
            ov.telemetry(**base, combat=True, wanted=3, deaths=self.highlights.deaths)
            ov.game_fx("wanted", "NCPD ★★★")
            restore(6)
        elif kind == "critical":
            ov.telemetry(**base, combat=True, critical=True, deaths=self.highlights.deaths)
            restore(6)
        elif kind == "db":
            ov.state("processing")
            ov.search(None, self.fillers.search_lines())
            time.sleep(5)
            ov.search("Sebastian Ibarra")
            restore(3)
        elif kind == "scan":
            ov.state("processing")
            ov.scan()
            restore(3)
        elif kind == "answer":
            ov.state("speaking")
            ov.answer_start()
            for sentence in ("Padre je fixer z Heywoodu, kedysi bol medzi Valentinos.",
                             "Ľudia ho berú ako kňaza, aj keď ho nikto nevysvätil."):
                ov.answer_append(sentence, duration_sec=len(sentence) * 0.055)
                time.sleep(len(sentence) * 0.06)
            restore(0.2)

    def _on_command(self, cmd: str, text: str | None = None) -> None:
        """Prikazy z ovladacieho okna (gui.py)."""
        if cmd == "mute":
            self._on_panic()
        elif cmd == "quit":
            self._events.put(Quit())
        elif cmd == "ask" and text:
            self._events.put(Typed(text))
        elif cmd == "memory_reload":
            self.longterm.reload()
        elif cmd == "hud_test" and text:
            threading.Thread(target=self._hud_test, args=(text,), name="hud-test", daemon=True).start()
        elif cmd == "volume" and text:
            try:
                self.voice.volume = max(0.0, min(1.5, float(text) / 100))
            except ValueError:
                pass

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
                self._events.put(Fallback(job, "stt_failed"))
                return
            if not transcript.strip():
                self._cancel_filler(job)  # omylom stlacene PTT — ticho, bez fillera
                self._events.put(Silent(job))
                return
            logger.info("Erik: %s  (STT %.1f s)", transcript, stt_sec)
            save_note(transcript)
            self.overlay.erik(transcript)
            if self.budget.exceeded():
                self._events.put(Fallback(job, "budget_reached"))
                return

            self._last_erik = self._idle_since = time.time()
            self._nudges_in_row = 0
            self._questions += 1
            self._ask(job, f"[ERIK] {transcript}", stt_sec)  # tag zdroja podla persona.md
        except Exception:
            logger.exception("neocakavana chyba vo workeri")
            self._events.put(Fallback(job, "general_error"))

    def _ask(self, job: Job, tagged_text: str, stt_sec: float = 0.0) -> None:
        """LLM stream. Stav hry ide ako riadok [HRA] na zaciatok spravy — v system prompte by
        kazda zmena HP zrusila cache pamate, v sprave sa ulozi do historie a cache nerusi.
        Chat divakov ([CHAT]) ide len k Erikovym otazkam, nie k hernym udalostiam."""
        erik = tagged_text.startswith("[ERIK]")
        stream = self.highlights.summary_line(self._questions) if erik and STREAM_WORDS.search(tagged_text) else None
        wiki = None
        if erik and self.brain.wiki.enabled:
            # clanok k otazke uz teraz (~0.5 s) — model ho dostane hned a netreba dalsie kolo s hladanim (~2-3 s)
            found = self.brain.wiki.prefetch(tagged_text[7:])
            if found and not job.cancelled:
                self.overlay.search(found[0])
                wiki = f"[WIKI {found[0]}] {found[1]}"
        viewers = system = None
        if erik:
            question = tagged_text[7:]
            if FORGET.search(question):
                nick = self.longterm.forget_viewer(question)
                if nick:
                    system = f"[SYSTÉM] poznámky o divákovi {nick} sú zmazané"
                else:
                    n = self.longterm.forget_fact(self.brain.anthropic_client, question)
                    system = f"[SYSTÉM] z pamäte o Erikovi zmazané fakty: {n}" if n else "[SYSTÉM] v pamäti som nič také nenašla"
            viewers = self.longterm.viewers_line(self.chat.recent_logins(), question)
        image = None
        if erik and self.vision.wants(tagged_text):
            # "co je toto?" — snimka okna hry (len hra, nikdy cely monitor), ~50 ms + ~0.2 s pre model
            image = self.vision.capture()
            if image and not job.cancelled:
                self.overlay.scan()
        lines = [self.game.line(), stream, wiki, "[OBRAZOVKA] priložená snímka hry" if image else None,
                 self.chat.line() if erik else None, viewers, system]
        job.tagged_text = tagged_text
        job.user_text = "\n".join([x for x in lines if x] + [tagged_text])
        answer = self.brain.ask_stream(
            job.user_text, None, self.memory.as_messages(), image_b64=image,
            on_sentence=lambda sentence: self._on_sentence(job, sentence),
            should_stop=lambda: job.cancelled,
            on_lookup=lambda title=None: self._on_lookup(job, title),
        )
        self._events.put(Answered(job, answer, stt_sec))

    def _start_job(self, target, *args, allowed: tuple = (State.IDLE,), interrupt: bool = False,
                   filler: bool = False) -> Job | None:
        """Novy Job + worker vlakno target(job, *args). None, ked Mirana mlci alebo je v stave mimo `allowed`.

        interrupt=True: beziaca odpoved sa zrusi (pisana otazka). filler=True: casovac fillera, ak prva
        veta nepride vcas. voice.arm() zrusi stop z predchadzajuceho barge-inu."""
        with self._lock:
            if self._muted:
                return None
            if interrupt and self.state in (State.PROCESSING, State.SPEAKING):
                logger.info("nova otazka prerusila %s", self.state.name)
                self._cancel_current()
            elif self.state not in allowed:
                return None
            self._set_state(State.PROCESSING)
            job = Job(gen=self._gen, released_at=time.perf_counter())
            self._job = job
        self.voice.arm()
        if filler and self.fillers.enabled:
            job.filler_timer = threading.Timer(self.fillers.delay_sec, self._play_filler, args=(job,))
            job.filler_timer.start()
        threading.Thread(target=target, args=(job, *args), name="job", daemon=True).start()
        return job

    def _maybe_nudge(self) -> None:
        """Erik sa dlho neozval: jedna vtipna pripomienka (moze siahnut po [HRA]). Nie v boji ani v scene,
        nie ked Mirana hovori; najviac idle_nudge.max_in_row za sebou, potom caka na Erika."""
        if not self.idle_enabled or self._muted or self._nudges_in_row >= self.idle_max_in_row:
            return
        now = time.time()
        if now - max(self._idle_since, self._last_nudge) < self.idle_after or self.budget.exceeded():
            return
        if now - self._last_proactive < 60:
            return  # prave sa ozvala k udalosti z hry, nech to nie je dvakrat po sebe
        snap = self.game.current
        if snap is not None and (snap.in_scene or snap.get("combat")):
            return  # skusi znova o chvilu
        minutes = int((now - self._idle_since) // 60)
        if self._start_job(self._work_tagged, f"[IDLE] Erik sa ti neozval {minutes} minút.") is None:
            return
        self._last_nudge = now
        self._nudges_in_row += 1
        logger.info("pripomienka po %d min ticha (%d. za sebou)", minutes, self._nudges_in_row)

    def _work_tagged(self, job: Job, tagged_text: str) -> None:
        try:
            self._ask(job, tagged_text)
        except Exception:
            logger.exception("chyba pri hernej udalosti")
            self._events.put(Fallback(job, "general_error"))

    # --- telemetria (vlakno game-state) ---------------------------------------------------------

    def _on_game_snapshot(self, snap) -> None:
        shown = {"deaths": self.highlights.deaths}
        if snap:
            hp = snap.get("hp")
            shown.update(location=snap.location, quest=snap.quest or "", combat=bool(snap.get("combat")),
                         wanted=int(snap.get("wanted") or 0), critical=hp is not None and 0 < hp <= self.hp_critical)
        if shown != self._telemetry_shown:
            self._telemetry_shown = shown
            self.overlay.telemetry(**shown)
        if snap and time.time() - self._longterm_game_at > 30:
            self._longterm_game_at = time.time()
            self.longterm.update_game(snap)
        line = self.game.line()
        if line != self._game_line_shown:  # ovladacie okno: aktualne zdravie, cas, ciel...
            self._game_line_shown = line
            self.overlay.game(live=snap is not None, line=line)

    def _record_game_event(self, name: str, snap, text: str) -> str:
        """Moment na strih + efekt na HUD (vzdy, aj ked Mirana mlci). Vrati text pre model."""
        wanted = snap.get("wanted") or 0
        if name == "death":
            self.highlights.add("death", snap.location or "")
            text += f" (dnes už {self.highlights.deaths}. smrť)"
            self.overlay.game_fx("death", f"FLATLINE #{self.highlights.deaths}")
        elif name == "level_up":
            self.highlights.add("level_up", f"úroveň {snap.get('level')}")
            self.overlay.game_fx("level_up", f"LEVEL {snap.get('level')}")
        elif name == "quest_completed":
            self.highlights.add("quest_completed", text)
            self.overlay.game_fx("quest_completed", "QUEST DOKONČENÝ")
        elif name == "wanted_up" and wanted >= 3:
            self.highlights.add("wanted_up", f"{wanted} hviezdy, {snap.location}")
        if name == "wanted_up":
            self.overlay.game_fx("wanted", "NCPD " + "★" * wanted)
        return text

    def _handle_game_event(self, name: str, snap, text: str) -> None:
        """Proaktivna hlaska: len ked Mirana mlci a nie hned po Erikovej otazke; max raz za cooldown.
        Kriticke HP a smrt maju vynimku z cooldownu. Pocas sceny (rozhovor, cutscena) do hry nevstupuje."""
        if name not in self.speak_on or self._muted or self.budget.exceeded():
            return
        urgent = name in ("hp_critical", "death")
        if not urgent and snap.in_scene:
            logger.info("herna udalost %s bez hlasky (scena)", name)
            return
        now = time.time()
        if not urgent and (now - self._last_proactive < self.proactive_cooldown or now - self._last_erik < self.quiet_after_erik):
            logger.info("herna udalost %s bez hlasky (cooldown)", name)
            return
        if self._start_job(self._work_tagged, f"[GAME_EVENT] {text}") is None:
            if urgent:  # povie ju hned, ako dohovori (Spoken aj tato funkcia bezia v hlavnej slucke)
                self._pending_urgent = (name, snap, text, now)
            return
        self._pending_urgent = None
        if not urgent:  # urgentna hlaska (kriticke HP) nema blokovat bezne hlasky na 5 minut
            self._last_proactive = now

    def _on_lookup(self, job: Job, title: str | None = None) -> None:
        """Model hlada vo wiki: povie "hladam v databaze" a HUD ukaze pristup do databazy;
        po najdeni (title) HUD ukaze nazov clanku. Bezny filler uz netreba."""
        if job.cancelled:
            return
        if title is not None:
            self.overlay.search(title)
            return
        self._cancel_filler(job)
        with self._lock:
            current = job.gen == self._gen and self.state is State.PROCESSING
        if current and not job.started and not job.searched:
            job.searched = True
            spoken = self.fillers.play_search()  # nahlas len prva; na HUD sa pri dlhsom hladani stridaju
            self.overlay.search(None, self.fillers.search_lines(spoken))

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
        logger.info("prvy zvuk %.1f s po pusteni PTT / udalosti", time.perf_counter() - job.released_at)

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

    def _handle_typed(self, text: str) -> None:
        """Pisana otazka z ovladacieho okna: ako PTT, len bez nahravky a prepisu. Prerusi beziacu odpoved."""
        text = " ".join(text.split())[:MAX_TYPED_CHARS]
        if not text:
            return
        if self._start_job(self._work_text, text, allowed=tuple(State), interrupt=True, filler=True) is None:
            logger.info("pisana otazka ignorovana, Mirana je stlmena: %s", text)
            self.overlay.notice("Mirana je stlmená, otázka sa neposlala. Zapni hlas a pošli ju znova.")

    def _work_text(self, job: Job, text: str) -> None:
        try:
            logger.info("Erik (pisane): %s", text)
            save_note(text)
            self.overlay.erik(text)
            if self.budget.exceeded():
                self._events.put(Fallback(job, "budget_reached"))
                return
            self._last_erik = self._idle_since = time.time()
            self._nudges_in_row = 0
            self._questions += 1
            self._ask(job, f"[ERIK] {text}")
        except Exception:
            logger.exception("neocakavana chyba pri pisanej otazke")
            self._events.put(Fallback(job, "general_error"))

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
        if job.tagged_text and job.tagged_text.startswith("[ERIK]"):
            self._last_exchange = (job.tagged_text[7:], text)
        # Do pamate ide len otazka, nie [HRA] a [CHAT]: tie tvorili 85 % pamate, aktualne su vzdy v novej
        # sprave a stary chat by sa vracal ako novy. Kratsia pamat = viac vymen za rovnaku cenu.
        self.memory.add_exchange(job.tagged_text or job.user_text, text)

    def _handle_event(self, event) -> None:
        match event:
            case Recording(wav):
                self._start_job(self._work, wav, allowed=(State.LISTENING,), filler=True)
            case Typed(text):
                self._handle_typed(text)
            case GameEvent(name, snap, text):
                self._handle_game_event(name, snap, text)
            case Interrupted(job):
                self._remember(job, interrupted=True)
            case Spoken(job):
                self._remember(job, interrupted=False)
                with self._lock:
                    if job.gen == self._gen and self.state in (State.PROCESSING, State.SPEAKING):
                        self._set_state(State.IDLE)
                pending, self._pending_urgent = self._pending_urgent, None
                if pending and time.time() - pending[3] < 10:
                    self._handle_game_event(*pending[:3])
            case Answered(job, answer, stt_sec):
                self._handle_answer(job, answer, stt_sec)
            case Silent(job) if not job.cancelled and job.gen == self._gen:
                with self._lock:
                    if self.state is State.PROCESSING:
                        self._set_state(State.IDLE)
            case Fallback(job, reason) if not job.cancelled and job.gen == self._gen:
                logger.info("fallback: %s", reason)
                job.remember = False
                self._cancel_filler(job)
                self.speaker.say_all(job, self.fallback[reason])

    def _handle_answer(self, job: Job, answer: Answer, stt_sec: float) -> None:
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

    def _shutdown_memory(self) -> None:
        """Pred vypnutim: statistiky dna a zhrnutie modelom (max ~25 s; co nestihne, doplni dalsi start)."""
        try:
            self._save_stream()
            self.overlay.notice("Ukladám pamäť…")
            worker = threading.Thread(target=self.longterm.extract, args=(self.brain.anthropic_client,), daemon=True)
            worker.start()
            worker.join(timeout=25)
            self.longterm.save(force=True)
        except Exception:
            logger.exception("pamat sa pri vypnuti neulozila")

    def run(self) -> None:
        self.overlay.start()
        self.highlights.start()
        self.longterm.start(self.brain.anthropic_client, stats_fn=self._save_stream)
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
                self._maybe_nudge()
                continue
            if isinstance(event, Quit):
                logger.info("vypnutie z ovladacieho okna")
                self.voice.stop()
                self._shutdown_memory()
                return
            try:
                self._handle_event(event)
            except Exception:
                logger.exception("chyba v hlavnej slucke (%s)", type(event).__name__)


if __name__ == "__main__":
    ensure_single_instance()
    cfg = load_config()
    try:
        Mirana(cfg, setup_logging(cfg)).run()
    except KeyboardInterrupt:
        logger.info("Mirana vypnuta (Ctrl+C)")
