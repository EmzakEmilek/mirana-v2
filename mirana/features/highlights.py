"""Momenty zo streamu na strih: znacky (bocne tlacidlo mysi) a automaticke udalosti z hry.

Kazdy moment sa hned zapise do logs/strih-<datum>.md s casom vo VOD-ke (ako dlho stream bezal) aj
s hodinami, aby sa dal v zazname rychlo najst. Cas streamu sa zisti z verejneho decapi.me (ziadne
prihlasenie): "uptime" kanala -> zaciatok streamu = teraz - uptime. Ked stream nebezi alebo sluzba
nepomoze, ostane len cas na hodinach.

Drzi aj denne statistiky (smrti, levely, questy, znacky) — prezivu restart Mirany pocas streamu.
"""

import logging
import re
import threading
import time
from datetime import datetime

import requests

from mirana import intents
from mirana.config import BASE_DIR
from mirana.features import Feature
from mirana.store import DailyJson

logger = logging.getLogger(__name__)

LOGS_DIR = BASE_DIR / "logs"
STATS_PATH = BASE_DIR / "data" / "stream_stats.json"
UPTIME_URL = "https://decapi.me/twitch/uptime/{channel}"
REFRESH_SEC = 300
UNITS = {"day": 86400, "hour": 3600, "minute": 60, "second": 1}

KIND_LABELS = {
    "marker": "ZNAČKA", "death": "SMRŤ", "level_up": "LEVEL", "quest_completed": "QUEST",
    "wanted_up": "POLÍCIA",
}


def parse_uptime(text: str) -> int | None:
    """'1 hour, 2 minutes, 3 seconds' -> 3723; 'xyz is offline' -> None."""
    if not text or "offline" in text.lower():
        return None
    total, found = 0, False
    for number, unit in re.findall(r"(\d+)\s*(day|hour|minute|second)s?", text.lower()):
        total += int(number) * UNITS[unit]
        found = True
    return total if found else None


def fmt_offset(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class Highlights:
    def __init__(self, config: dict):
        self.channel = (config.get("twitch_chat") or {}).get("channel") or ""
        self.channel = self.channel.strip().rstrip("/").rsplit("/", 1)[-1].lstrip("#").lower()
        self.path = LOGS_DIR / f"strih-{datetime.now():%Y%m%d}.md"
        self._lock = threading.Lock()
        self._stream_start: float | None = None
        self._checked = 0.0
        self.session_start = time.time()
        self._daily = DailyJson(STATS_PATH, {k: 0 for k in ("death", "level_up", "quest_completed", "marker", "wanted_up")})

    # --- cas streamu --------------------------------------------------------------------------

    def refresh_clock(self) -> None:
        """Zisti zaciatok streamu (sietove volanie, volat mimo hlavneho vlakna)."""
        if not self.channel:
            return
        try:
            r = requests.get(UPTIME_URL.format(channel=self.channel), timeout=4)
            uptime = parse_uptime(r.text)
        except Exception as e:
            logger.info("cas streamu sa nepodarilo zistit: %s", e)
            return
        with self._lock:
            self._checked = time.time()
            self._stream_start = time.time() - uptime if uptime is not None else None
        logger.info("stream: %s", f"bezi {fmt_offset(uptime)}" if uptime is not None else "offline")

    def start(self) -> None:
        def loop():
            while True:
                self.refresh_clock()
                time.sleep(REFRESH_SEC)
        threading.Thread(target=loop, name="stream-clock", daemon=True).start()

    def vod_offset(self) -> str | None:
        with self._lock:
            start = self._stream_start
        return fmt_offset(time.time() - start) if start else None

    # --- momenty -------------------------------------------------------------------------------

    def add(self, kind: str, text: str, refresh: bool = False) -> str:
        """Zapise moment, vrati cas, ktory sa ukaze v okne ("1:23:45" alebo "21:14:07")."""
        if refresh:
            self.refresh_clock()
        clock = datetime.now().strftime("%H:%M:%S")
        vod = self.vod_offset()
        self._count(kind)
        line = f"- **{vod or '—'}** · {clock} · {KIND_LABELS.get(kind, kind.upper())} · {text}\n"
        with self._lock:
            new = not self.path.exists()
            try:
                LOGS_DIR.mkdir(exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    if new:
                        f.write(f"# Momenty na strih — {datetime.now():%d.%m.%Y}\n\n"
                                "Prvý čas = čas vo VOD-ke (ako dlho stream bežal), druhý = hodiny.\n\n")
                    f.write(line)
            except OSError:
                logger.exception("momenty na strih sa nedaju zapisat")
        logger.info("moment na strih: %s %s (%s)", kind, text, vod or clock)
        return vod or clock

    # --- statistiky dna -----------------------------------------------------------------------

    @property
    def stats(self) -> dict:
        with self._lock:
            self._daily.roll()
            return dict(self._daily.data)

    def _count(self, kind: str) -> None:
        with self._lock:
            self._daily.roll()
            self._daily.data[kind] = self._daily.data.get(kind, 0) + 1
            self._daily.save()

    @property
    def deaths(self) -> int:
        return self.stats.get("death", 0)

    def summary_line(self, questions: int) -> str:
        """[STREAM] riadok pre model, keď sa Erik pýta na stream."""
        s = self.stats
        minutes = int((time.time() - self.session_start) // 60)
        vod = self.vod_offset()
        parts = [f"stream beží {vod}" if vod else f"Mirana beží {minutes // 60} h {minutes % 60} min",
                 f"smrti dnes {s.get('death', 0)}", f"nové levely {s.get('level_up', 0)}",
                 f"dokončené hlavné questy {s.get('quest_completed', 0)}",
                 f"policajné naháňačky {s.get('wanted_up', 0)}", f"značky na strih {s.get('marker', 0)}",
                 f"otázok v tejto session {questions}"]
        return "[STREAM] " + " | ".join(parts)


class HighlightsFeature(Feature):
    """Znacka na strih (bocne tlacidlo mysi), zapis udalosti z hry a riadok [STREAM] so statistikami."""

    def __init__(self, app):
        super().__init__(app)
        self.store = app.highlights = Highlights(app.config)
        self.last_exchange = ("", "")  # posledna otazka a odpoved — kontext k znacke
        app.ptt.on_marker = self.on_marker

    def start(self) -> None:
        self.store.start()

    def context(self, turn) -> None:
        if turn.from_erik and intents.asks_about_stream(turn.question):
            turn.add("STREAM", self.store.summary_line(self.app.questions))

    def on_answer(self, turn, text: str) -> None:
        if turn.from_erik:
            self.last_exchange = (turn.question, text)

    def on_game_event(self, name: str, snap, text: str) -> str:
        wanted = snap.get("wanted") or 0
        if name == "death":
            self.store.add("death", snap.location or "")
            text += f" (dnes už {self.store.deaths}. smrť)"
        elif name == "level_up":
            self.store.add("level_up", f"úroveň {snap.get('level')}")
        elif name == "quest_completed":
            self.store.add("quest_completed", text)
        elif name == "wanted_up" and wanted >= 3:
            self.store.add("wanted_up", f"{wanted} hviezdy, {snap.location}")
        return text

    def on_marker(self) -> None:
        """Bocne tlacidlo: moment na strih. Sietove volanie (cas streamu) mimo hooku mysi."""
        def work():
            snap = self.app.game.current
            where = ", ".join(x for x in ((snap.location if snap else ""), (snap.quest if snap else "") or "") if x)
            question, answer = self.last_exchange
            context = " · ".join(x for x in (where, f"Erik: {question}" if question else "",
                                             f"Mirana: {answer[:120]}" if answer else "") if x)
            when = self.store.add("marker", context or "bez kontextu", refresh=True)
            self.app.overlay.notice(f"◆ Značka na strih: {when}")
        threading.Thread(target=work, name="marker", daemon=True).start()
