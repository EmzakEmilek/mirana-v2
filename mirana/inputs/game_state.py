"""Stav hry z CET modu (mod/mirana_state) -> slovensky riadok [HRA] a herne udalosti.

Mod kazdu 1 s zapise state.json do svojho priecinka. Tento modul subor sleduje (podla casu zmeny),
drzi posledny stav a porovnanim s predchadzajucim vyraba udalosti: hp_low, hp_critical, death,
district_change, quest_changed, quest_completed, level_up, wanted_up, wanted_clear,
combat_start, combat_end.

Do promptu ide vzdy slovensky riadok, nikdy surovy JSON — anglicke kluce a vety by stahovali
Miraninu slovencinu k prekladu. Z hry su len vlastne mena (questy, stvrte, veci) v jazyku hry.
Ked mod neposiela (hra nebezi, menu, pad), riadok sa nevklada vobec.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from mirana.config import BASE_DIR

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


def mod_version(path: Path) -> int | None:
    """VERSION z init.lua (v repe alebo v hre), None ked subor chyba."""
    try:
        m = re.search(r"^local VERSION = (\d+)", path.read_text(encoding="utf-8"), re.M)
    except OSError:
        return None
    return int(m.group(1)) if m else None


def game_running() -> bool:
    """Bezi Cyberpunk? (mod sa pocas hry neprepisuje — CET ho ma nacitany)."""
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Cyberpunk2077.exe", "/NH"], capture_output=True,
                             text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except Exception:
        return True  # radsej nic neprepisovat
    return "Cyberpunk2077.exe" in out


def update_mod(game_dir: Path | None) -> str | None:
    """Novsi mod v repe -> skopiruje ho do hry (len ked hra nebezi). Vrati spravu pre okno, alebo None."""
    if game_dir is None or not cet_installed(game_dir):
        return None
    repo, installed = mod_version(MOD_SOURCE / "init.lua"), mod_version(game_dir / MOD_SUBDIR / "init.lua")
    if repo is None or (installed is not None and installed >= repo):
        return None
    if game_running():
        return f"Mod mirana_state v{repo} sa nainštaluje po vypnutí hry (v hre je {installed or 'žiadny'})."
    install_mod(game_dir)
    return f"Mod mirana_state aktualizovaný: v{installed or '—'} → v{repo}."


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

# Sledovany "quest", ktory nie je quest: neobjavene miesto na mape
PSEUDO_QUESTS = {"Neobjevené", "Neobjavené", "Undiscovered"}
PSEUDO_QUEST_IDS = {"generic_sts_quest"}

TARGET_HOLD_SEC = 10  # ako dlho po odvrateni pohladu sa ciel este posiela ("pred chvilou zameriaval")
# Po nacitani hry (save, start) mod chvilu posiela neuplne udaje (level 1, prazdny pribeh) a potom skutocne —
# vyzeralo by to ako level up a hromada dokoncenych questov. Udalosti sa vtedy ignoruju.
LOAD_GRACE_SEC = 30

# Od tejto urovne je hrac v scene (rozhovor s volbami, cutscena) — gamePSMHighLevel.SceneTier3+
SCENE_TIER = 3

WEATHER = [  # (kus nazvu stavu pocasia z hry, slovensky) — prvy zhodny vyhrava; None = nespominat
    ("norain", None), ("heavyrain", "silný dážď"), ("lightrain", "slabý dážď"),  # mod v4: len dazd
    ("toxic", "toxický dážď"), ("sandstorm", "piesočná búrka"), ("rain", "dážď"), ("pollution", "smog"),
    ("fog", "hmla"), ("heavy_clouds", "zamračené"), ("cloudy", "zamračené"), ("light_clouds", "polooblačno"),
    ("sunny", "jasno"), ("clear", "jasno"),
]

ATTRIBUTES = [("body", "Telo"), ("reflexes", "Reflexy"), ("tech", "Technika"), ("intelligence", "Inteligencia"),
              ("cool", "Chladnokrvnosť")]


def _plural(n: int, one: str, few: str, many: str) -> str:
    return one if n == 1 else few if 2 <= n <= 4 else many


def _thing_name(value) -> str | None:
    """Nazov z hry; neprelozeny kluc zariadenia "Gameplay-Devices-DisplayNames-ExplosivePropane"
    -> "Explosive Propane" (lepsie nez nic, model to pochopi)."""
    if isinstance(value, str) and value.startswith("Gameplay-"):
        value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value.rsplit("-", 1)[-1])
    return _text(value)


def _text(value) -> str | None:
    """Text z hry, bez neprelozenych klucov (LocKey#123) a prazdnych hodnot."""
    if not isinstance(value, str) or not value.strip() or value.startswith("LocKey#"):
        return None
    return value.strip()


def weather_text(raw) -> str | None:
    raw = (raw or "").lower() if isinstance(raw, str) else ""
    return next((sk for key, sk in WEATHER if key in raw), None)


def _main_done(s) -> list[dict]:
    story = s.get("story") if isinstance(s.get("story"), dict) else {}
    done = story.get("main_done")
    return [q for q in done if isinstance(q, dict)] if isinstance(done, list) else []


def _quest_order(quest_id) -> int:
    """Poradie hlavneho questu podla id (q000 prolog ... q1xx 2. dejstvo); Phantom Liberty (q3xx) mimo."""
    m = re.match(r"q(\d{3})", str(quest_id or ""))
    n = int(m.group(1)) if m else -1
    return n if 0 <= n < 300 else -1


@dataclass
class Snapshot:
    data: dict
    received: float = field(default_factory=time.time)

    def get(self, key, default=None):
        return self.data.get(key, default)

    @property
    def location(self) -> str:
        return ", ".join(x for x in (self.get("district"), self.get("subdistrict")) if x)

    @property
    def quest(self) -> str | None:
        """Sledovany quest, okrem neobjavenych miest na mape."""
        quest = _text(self.get("quest"))
        return None if quest in PSEUDO_QUESTS or self.get("quest_id") in PSEUDO_QUEST_IDS else quest

    @property
    def in_scene(self) -> bool:
        tier = self.get("scene_tier")
        return isinstance(tier, int) and tier >= SCENE_TIER


def _health(s: Snapshot) -> str | None:
    if s.get("hp") is None:
        return None
    text = f"zdravie {s.get('hp')} %"
    extra = []
    # od modu v3 su to nabitia z maxima; v2 posielal percenta, tie sa nezobrazuju
    if s.get("heal_charges") is not None and s.get("heal_max"):
        extra.append(f"liečenie {s.get('heal_charges')} z {s.get('heal_max')}")
    if s.get("grenade_charges") is not None and s.get("grenade_max"):
        extra.append(f"granáty {s.get('grenade_charges')} z {s.get('grenade_max')}")
    return text + (f" ({', '.join(extra)})" if extra else "")


def _world(s: Snapshot) -> str | None:
    items = [x for x in (s.location, s.get("time") if _text(s.get("time")) else None, weather_text(s.get("weather"))) if x]
    return ", ".join(items) or None


def _character(s: Snapshot) -> str | None:
    if s.get("level") is None:
        return None
    text = f"úroveň {s.get('level')}"
    if s.get("street_cred") is not None:
        text += f", street cred {s.get('street_cred')}"
    attrs = s.get("attributes") if isinstance(s.get("attributes"), dict) else {}
    if attrs:
        text += ", atribúty " + " ".join(f"{sk} {attrs[key]}" for key, sk in ATTRIBUTES if attrs.get(key) is not None)
    free = []
    if s.get("attribute_points"):
        n = s.get("attribute_points")
        free.append(f"{n} {_plural(n, 'atribútový bod', 'atribútové body', 'atribútových bodov')}")
    if s.get("perk_points"):
        n = s.get("perk_points")
        free.append(f"{n} {_plural(n, 'perkový bod', 'perkové body', 'perkových bodov')}")
    if free:
        text += ", nerozdelené " + " a ".join(free)
    return text


def _gear(s: Snapshot) -> str | None:
    items = []
    if _text(s.get("os")):
        items.append(f"OS {s.get('os')}")
    if s.get("cyberware_capacity"):
        items.append(f"kybervýzbroj voľná kapacita {s.get('cyberware_free')} z {s.get('cyberware_capacity')}")
    if s.get("ram_max"):
        items.append(f"RAM {s.get('ram')}/{s.get('ram_max')}")
    weapons = [w for w in (s.get("weapons") or []) if _text(w)] if isinstance(s.get("weapons"), list) else []
    if weapons:
        items.append("zbrane " + ", ".join(weapons))
    if s.get("armor") is not None:
        items.append(f"brnenie {s.get('armor')}")
    return ", ".join(items) or None


def _weapon(s: Snapshot) -> str | None:
    if not _text(s.get("weapon")):
        return None
    text = f"v ruke {s.get('weapon')}"
    if s.get("ammo") is not None:
        text += f", v zásobníku {s.get('ammo')}" + (f" z {s.get('ammo_max')}" if s.get("ammo_max") else "")
        if s.get("ammo_reserve") is False:
            text += ", náhradné náboje došli"
    return text


def _story(s: Snapshot) -> str | None:
    main = _main_done(s)
    story = s.get("story") if isinstance(s.get("story"), dict) else None
    if story is None:
        return None
    text = f"príbeh: dokončené hlavné questy {len(main)}"
    ordered = [q for q in main if _quest_order(q.get("id")) >= 0 and _text(q.get("title"))]
    if ordered:
        text += f", najďalej {max(ordered, key=lambda q: _quest_order(q.get('id')))['title']}"
    if story.get("side_done") is not None:
        text += f", ostatné questy a zákazky {story.get('side_done')}"
    return text


def _quest(s: Snapshot) -> str | None:
    if not s.quest:
        return None
    text = f"quest {s.quest}"
    if _text(s.get("objective")):
        text += f", cieľ „{s.get('objective')}“"
    return text


def _situation(s: Snapshot) -> str:
    text = "v boji" if s.get("combat") else "mimo boja"
    if s.in_scene:
        text += ", práve v scéne (rozhovor alebo cutscéna)"
    wanted = s.get("wanted")
    if isinstance(wanted, int) and wanted > 0:
        text += f", polícia ho hľadá ({wanted} {_plural(wanted, 'hviezda', 'hviezdy', 'hviezd')})"
    return text


def _target(s: Snapshot) -> str | None:
    t = s.get("target") if isinstance(s.get("target"), dict) else None
    name = _thing_name(t.get("name")) if t else None
    if not name:
        return None
    verb = "pred chvíľou zameriaval" if t.get("recent") else "zameriava"
    if t.get("kind") == "vehicle":
        return f"{verb} vozidlo {name}"
    if t.get("kind") == "device":
        return f"{verb} zariadenie {name}"
    info = []
    if t.get("dead"):
        info.append("mŕtvy")
    elif t.get("boss"):
        info.append("boss")
    elif t.get("hostile"):
        info.append("nepriateľ")
    elif t.get("civilian"):
        info.append("civil")
    if t.get("level") and not t.get("dead"):
        info.append(f"úroveň {t['level']}")
    if t.get("hp") is not None and not t.get("dead") and t.get("hp") < 100:
        info.append(f"zdravie {t['hp']} %")
    return f"{verb} {name}" + (f" ({', '.join(info)})" if info else "")


def target_info(s: Snapshot | None) -> dict | None:
    """Ciel pod zameriavacom pre kartu skenu v HUD v2: meno, druh, level, zdravie (alebo None)."""
    t = s.get("target") if s is not None and isinstance(s.get("target"), dict) else None
    name = _thing_name(t.get("name")) if t else None
    if not name:
        return None
    if t.get("kind") in ("vehicle", "device"):
        status = "vozidlo" if t.get("kind") == "vehicle" else "zariadenie"
    else:
        status = ("mŕtvy" if t.get("dead") else "boss" if t.get("boss") else "nepriateľ" if t.get("hostile")
                  else "civil" if t.get("civilian") else "neutrálny")
    return {"name": name, "status": status, "level": t.get("level") if not t.get("dead") else None,
            "hp": t.get("hp") if not t.get("dead") else None, "recent": bool(t.get("recent"))}


def _vehicle(s: Snapshot) -> str | None:
    radio = _text(s.get("radio"))
    song = _text(s.get("song"))
    music = (f"rádio {radio}" + (f", hrá {song}" if song else "")) if radio else None
    if not _text(s.get("vehicle")):
        return music  # vreckove radio aj peso
    text = f"{'šoféruje' if s.get('driver', True) else 'vezie sa v'} {s.get('vehicle')}"
    if s.get("speed_kmh") is not None:
        text += f", {s.get('speed_kmh')} km/h"
    return text + (f", {music}" if music else "")


def telemetry_line(s: Snapshot) -> str:
    """Slovensky riadok pre model. Z hry su len vlastne mena; prazdne a nulove casti sa vynechaju."""
    parts = [
        _health(s), _world(s), _situation(s), _quest(s), _target(s), _vehicle(s), _weapon(s),
        _character(s), _gear(s), _story(s),
        f"{s.get('money')} eddies" if s.get("money") is not None else None,
    ]
    return "[HRA] " + " | ".join(p for p in parts if p)


# Slovensky opis udalosti pre [GAME_EVENT] — model z neho spravi jednu vetu v charaktere
EVENT_TEXT = {
    "hp_critical": "zdravie kleslo kriticky nízko, na {hp} %",
    "hp_low": "zdravie kleslo na {hp} %",
    "death": "Erik práve zomrel",
    "district_change": "Erik prišiel do štvrte {location}",
    "quest_changed": "Erik sleduje nový quest {quest}",
    "quest_completed": "Erik dokončil hlavný quest {completed}",
    "level_up": "Erik postúpil na úroveň {level}",
    "wanted_up": "polícia ho hľadá, už {wanted}",
    "wanted_clear": "polícia ho prestala hľadať",
    "combat_start": "začal sa boj",
    "combat_end": "boj skončil",
}


def detect_events(prev: Snapshot | None, cur: Snapshot, hp_low: int, hp_critical: int,
                  last_quest: str | None = None) -> list[str]:
    """last_quest = posledny skutocny quest; odbocka na neobjavene miesto a spat nie je novy quest."""
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
    if cur.quest and cur.quest != (last_quest or prev.quest):
        events.append("quest_changed")
    if len(completed_quests(prev, cur)) == 1:  # viac naraz = nacitany save, nie postup
        events.append("quest_completed")
    wanted, old_wanted = cur.get("wanted"), prev.get("wanted")
    if isinstance(wanted, int) and isinstance(old_wanted, int):
        if wanted > old_wanted:
            events.append("wanted_up")
        elif wanted == 0 < old_wanted:
            events.append("wanted_clear")
    if 0 < (prev.get("level") or 0) < (cur.get("level") or 0) <= (prev.get("level") or 0) + 2:  # skok = nacitany save
        events.append("level_up")
    if cur.get("combat") and not prev.get("combat"):
        events.append("combat_start")
    if prev.get("combat") and not cur.get("combat"):
        events.append("combat_end")
    return events


def completed_quests(prev: Snapshot | None, cur: Snapshot) -> list[str]:
    """Hlavne questy, ktore pribudli medzi dokoncenymi. Na zaciatku (prvy zoznam) nic."""
    if prev is None or not isinstance(prev.get("story"), dict) or not isinstance(cur.get("story"), dict):
        return []
    before = {q.get("id") for q in _main_done(prev)}
    return [q.get("title") or q.get("id") for q in _main_done(cur) if q.get("id") not in before]


def event_text(name: str, s: Snapshot, prev: Snapshot | None = None) -> str:
    wanted = s.get("wanted") or 0
    values = {
        "hp": s.get("hp"), "location": s.location or "?", "quest": s.quest or "?", "level": s.get("level"),
        "wanted": f"{wanted} {_plural(wanted, 'hviezda', 'hviezdy', 'hviezd')}",
        "completed": ", ".join(completed_quests(prev, s)) or "?",
    }
    return EVENT_TEXT.get(name, name).format(**values)


class GameState:
    """Sleduje state.json vo vlakne. on_event(nazov, snapshot, text) a on_snapshot(snapshot|None) volá z vlakna."""

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
        self._last_quest: str | None = None
        self._errors: set[str] = set()
        self._last_target: tuple[dict, float] | None = None
        self._in_game_since = 0.0           # kedy sa hrac naposledy dostal do hry (nacitanie save)

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
            # Erik sa spyta "kto je toto?" az ked uz zameriavac uhol — ciel plati este TARGET_HOLD_SEC
            target = data.get("target") if isinstance(data.get("target"), dict) else None
            if target:
                self._last_target = (dict(target), time.time())
            elif self._last_target and time.time() - self._last_target[1] <= TARGET_HOLD_SEC:
                data["target"] = {**self._last_target[0], "recent": True}
            snap = Snapshot(data)
            with self._lock:
                prev, self._current = self._current, snap
            errors = data.get("errors") or {}
            if set(errors) != self._errors:
                self._errors = set(errors)
                if errors:
                    logger.warning("CET mod: tieto udaje nejdu: %s", errors)
            if prev is None or prev.get("quest_id") != data.get("quest_id"):
                logger.info("sledovany quest: %s (id %s, typ %s)", data.get("quest"), data.get("quest_id"), data.get("quest_type"))
            if snap.get("in_game") and (prev is None or not prev.get("in_game")):
                self._in_game_since = time.time()
            events = detect_events(prev, snap, self.hp_low, self.hp_critical, self._last_quest)
            if events and time.time() - self._in_game_since < LOAD_GRACE_SEC:
                logger.info("udalosti hned po nacitani hry ignorovane: %s", ", ".join(events))
                events = []
            if snap.quest:
                self._last_quest = snap.quest
            for event in events:
                text = event_text(event, snap, prev)
                logger.info("herna udalost: %s (%s)", event, text)
                if self.on_event:
                    self.on_event(event, snap, text)
        live = self.current is not None
        if live != self._was_live:
            self._was_live = live
            logger.info("telemetria %s", "pripojena" if live else "nedostupna (hra nebezi alebo menu)")
        if self.on_snapshot:
            self.on_snapshot(self.current)
