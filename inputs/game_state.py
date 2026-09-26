"""Stav hry z CET modu (mod/mirana_state) -> slovensky riadok [HRA] a herne udalosti.

Mod kazde 2 s zapise state.json do svojho priecinka. Tento modul subor sleduje (podla casu zmeny),
drzi posledny stav a porovnanim s predchadzajucim vyraba udalosti: hp_low, hp_critical, death,
district_change, quest_changed, level_up, combat_start, combat_end.

Do promptu ide vzdy slovensky riadok, nikdy surovy JSON — anglicke kluce a vety by stahovali
Miraninu slovencinu k prekladu. Anglicke su len vlastne mena z hry (questy, stvrte, zbrane).
Ked mod neposiela (hra nebezi, menu, pad), riadok sa nevklada vobec.
"""

import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.config import BASE_DIR

logger = logging.getLogger(__name__)

MOD_SOURCE = BASE_DIR / "mod" / "mirana_state"
MOD_SUBDIR = Path("bin") / "x64" / "plugins" / "cyber_engine_tweaks" / "mods" / "mirana_state"
GAME_DIR_CANDIDATES = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Cyberpunk 2077",
    r"C:\Program Files\Steam\steamapps\common\Cyberpunk 2077",
    r"C:\Program Files (x86)\GOG Galaxy\Games\Cyberpunk 2077",
    r"C:\GOG Games\Cyberpunk 2077",
    r"C:\Program Files\Epic Games\Cyberpunk 2077",
]


# --- hladanie hry a instalacia modu ---------------------------------------------------------

def _steam_libraries() -> list[Path]:
    """Vsetky Steam kniznice (aj na inych diskoch) z libraryfolders.vdf."""
    out = []
    for steam in (Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")):
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                out.append(Path(m.group(1).replace("\\\\", "\\")))
    return out


def find_game_dir() -> Path | None:
    candidates = [Path(p) for p in GAME_DIR_CANDIDATES]
    candidates += [lib / "steamapps" / "common" / "Cyberpunk 2077" for lib in _steam_libraries()]
    for path in candidates:
        if (path / "bin" / "x64" / "Cyberpunk2077.exe").exists():
            return path
    return None


def cet_installed(game_dir: Path) -> bool:
    return (game_dir / "bin" / "x64" / "plugins" / "cyber_engine_tweaks").is_dir()


def install_mod(game_dir: Path) -> Path:
    """Skopiruje mod/mirana_state do CET mods. Vrati cestu k state.json."""
    target = game_dir / MOD_SUBDIR
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MOD_SOURCE / "init.lua", target / "init.lua")
    return target / "state.json"


def resolve_json_path(cfg: dict) -> Path | None:
    """game_state.json_path: presna cesta, alebo "auto" = najdi hru a vezmi state.json z CET modu."""
    override = os.environ.get("MIRANA_GAME_STATE_PATH")  # simulator: tools/simulate_game.py
    if override:
        return Path(override)
    raw = (cfg.get("json_path") or "auto").strip()
    if raw.lower() != "auto":
        return Path(os.path.expandvars(raw))
    game = find_game_dir()
    return game / MOD_SUBDIR / "state.json" if game else None


# --- stav a udalosti --------------------------------------------------------------------------

@dataclass
class Snapshot:
    data: dict
    received: float = field(default_factory=time.time)

    def get(self, key, default=None):
        return self.data.get(key, default)

    @property
    def location(self) -> str:
        return ", ".join(x for x in (self.get("district"), self.get("subdistrict")) if x)


def telemetry_line(s: Snapshot) -> str:
    """Kratky slovensky riadok pre model. Surove hodnoty z hry su len vlastne mena."""
    parts = []
    if s.get("hp") is not None:
        parts.append(f"zdravie {s.get('hp')} %")
    if s.location:
        parts.append(s.location)
    if s.get("level") is not None:
        parts.append(f"úroveň {s.get('level')}" + (f", street cred {s.get('street_cred')}" if s.get("street_cred") is not None else ""))
    if s.get("quest"):
        quest = f"quest {s.get('quest')}"
        if s.get("objective"):
            quest += f", cieľ „{s.get('objective')}“"
        parts.append(quest)
    parts.append("v boji" if s.get("combat") else "mimo boja")
    if s.get("vehicle"):
        parts.append(f"šoféruje {s.get('vehicle')}")
    if s.get("weapon"):
        parts.append(f"v ruke {s.get('weapon')}")
    if s.get("money") is not None:
        parts.append(f"{s.get('money')} eddies")
    return "[HRA] " + " | ".join(parts)


# Slovensky opis udalosti pre [GAME_EVENT] — model z neho spravi jednu vetu v charaktere
EVENT_TEXT = {
    "hp_critical": "zdravie kleslo kriticky nízko, na {hp} %",
    "hp_low": "zdravie kleslo na {hp} %",
    "death": "Erik práve zomrel",
    "district_change": "Erik prišiel do štvrte {location}",
    "quest_changed": "Erik sleduje nový quest {quest}",
    "level_up": "Erik postúpil na úroveň {level}",
    "combat_start": "začal sa boj",
    "combat_end": "boj skončil",
}


def detect_events(prev: Snapshot | None, cur: Snapshot, hp_low: int, hp_critical: int) -> list[str]:
    if prev is None or not cur.get("in_game") or not prev.get("in_game"):
        return []
    events = []
    hp, old_hp = cur.get("hp"), prev.get("hp")
    if hp is not None and old_hp is not None:
        if hp <= 0 < old_hp:
            events.append("death")
        elif hp <= hp_critical < old_hp:
            events.append("hp_critical")
        elif hp <= hp_low < old_hp:
            events.append("hp_low")
    if cur.get("district") and prev.get("district") and cur.get("district") != prev.get("district"):
        events.append("district_change")
    if cur.get("quest") and cur.get("quest") != prev.get("quest"):
        events.append("quest_changed")
    if (cur.get("level") or 0) > (prev.get("level") or 0) > 0:
        events.append("level_up")
    if cur.get("combat") and not prev.get("combat"):
        events.append("combat_start")
    if prev.get("combat") and not cur.get("combat"):
        events.append("combat_end")
    return events


def event_text(name: str, s: Snapshot) -> str:
    values = {"hp": s.get("hp"), "location": s.location or "?", "quest": s.get("quest") or "?", "level": s.get("level")}
    return EVENT_TEXT.get(name, name).format(**values)


class GameState:
    """Sleduje state.json vo vlakne. on_event(nazov, snapshot) a on_snapshot(snapshot|None) volá z vlakna."""

    def __init__(self, config: dict, on_event=None, on_snapshot=None):
        cfg = config.get("game_state", {})
        self.enabled = cfg.get("enabled", False)
        self.poll = cfg.get("poll_interval_sec", 2)
        self.stale_after = cfg.get("stale_after_sec", 10)
        self.hp_low = cfg.get("hp_low_threshold", 25)
        self.hp_critical = cfg.get("hp_critical_threshold", 10)
        self.path = resolve_json_path(cfg) if self.enabled else None
        self.on_event = on_event
        self.on_snapshot = on_snapshot
        self._current: Snapshot | None = None
        self._mtime = 0.0
        self._lock = threading.Lock()
        self._was_live = False

    def start(self) -> None:
        if not self.enabled:
            return
        if self.path is None:
            logger.warning("hra sa nenasla — nastav game_state.json_path (okno Nastavenia -> Hra)")
            return
        logger.info("telemetria: sledujem %s", self.path)
        threading.Thread(target=self._run, name="game-state", daemon=True).start()

    @property
    def current(self) -> Snapshot | None:
        """Posledny stav, ak je cerstvy a hrac je v hre; inak None."""
        with self._lock:
            s = self._current
        if s is None or not s.get("in_game") or time.time() - s.received > self.stale_after:
            return None
        return s

    def line(self) -> str | None:
        s = self.current
        return telemetry_line(s) if s else None

    def _run(self) -> None:
        while True:
            try:
                self._tick()
            except Exception:
                logger.exception("chyba pri citani stavu hry")
            time.sleep(self.poll)

    def _tick(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime and mtime != self._mtime:
            self._mtime = mtime
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return  # mod prave zapisuje, precitame o chvilu
            snap = Snapshot(data)
            with self._lock:
                prev, self._current = self._current, snap
            if data.get("errors"):
                logger.debug("CET mod hlasi chyby: %s", data["errors"])
            for event in detect_events(prev, snap, self.hp_low, self.hp_critical):
                logger.info("herna udalost: %s (%s)", event, event_text(event, snap))
                if self.on_event:
                    self.on_event(event, snap)
        live = self.current is not None
        if live != self._was_live:
            self._was_live = live
            logger.info("telemetria %s", "pripojena" if live else "nedostupna (hra nebezi alebo menu)")
        if self.on_snapshot:
            self.on_snapshot(self.current)
