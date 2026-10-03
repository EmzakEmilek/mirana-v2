"""HUD v OBS: telemetria z hry, efekty pri udalostiach, zvyraznene slova v odpovedi a ukazky z Nastaveni.

Pre HUD v2 navyse: cas, pocasie a eddies v telemetrii, karta pri novej stvrti a novej skladbe v radiu,
podrobnosti momentov (kde zomrel, aky quest) a v kazdej vete odpovede zvyraznene mena z hry, nicky
divakov a nadavky (marks) + kto z divakov bol spomenuty (karta kontaktu).
"""

import re
import threading
import time

from mirana import intents
from mirana.features import Feature
from mirana.features.longterm import _mentioned, _norm as _nick_norm
from mirana.features.wiki import _norm as _name_norm
from mirana.inputs.game_state import EVENT_TEXT, _text, weather_text

TOKEN = re.compile(r"[^\W_][\w'’]*(?:-[\w'’]+)*")
NOT_NAMES = {"mirana", "emzo", "erik", "emzakemil"}
MAX_NGRAM = 4
BADGES = (("broadcaster", "STREAMER"), ("moderator", "MOD"), ("vip", "VIP"), ("subscriber", "SUB"))


def mark_sentence(sentence: str, is_name, viewers: dict) -> tuple[list, list]:
    """Zvyraznene useky vety [[od, do, druh]] (nick | swear | name) a karty spomenutych divakov.

    Poradie prednosti: nick divaka, nadavka, nazov z hry; useky sa neprekryvaju. Nazov musi zacinat
    velkym pismenom (slovenske slova z vety tak nezasvietia); viacslovne nazvy maju prednost."""
    taken = [False] * len(sentence)
    marks, cards = [], []

    def free(a: int, b: int) -> bool:
        return not any(taken[a:b])

    def take(a: int, b: int, kind: str) -> None:
        for i in range(a, b):
            taken[i] = True
        marks.append([a, b, kind])

    tokens = [(m.start(), m.end(), m.group(0)) for m in TOKEN.finditer(sentence)]
    seen = set()
    for a, b, word in tokens:
        norm = _nick_norm(word)
        for login, v in viewers.items():
            nick = v.get("nick") or login
            exact = norm in (_nick_norm(nick), _nick_norm(login))
            if exact or (word[:1].isupper() and _mentioned(nick, {norm})):
                if free(a, b):
                    take(a, b, "nick")
                if login not in seen and len(cards) < 3:
                    seen.add(login)
                    badge = next((label for key, label in BADGES if key in (v.get("badges") or [])), "")
                    cards.append({"nick": nick, "badge": badge, "visits": v.get("visits", 1),
                                  "since": v.get("first_seen") or ""})
                break
    for m in intents.SWEAR.finditer(sentence):
        if free(m.start(), m.end()):
            take(m.start(), m.end(), "swear")
    i = 0
    while i < len(tokens):
        for n in range(min(MAX_NGRAM, len(tokens) - i), 0, -1):
            group = tokens[i:i + n]
            a, b = group[0][0], group[-1][1]
            gaps = [sentence[group[k][1]:group[k + 1][0]] for k in range(n - 1)]
            if any(g not in (" ", "-") for g in gaps) or not group[0][2][:1].isupper():
                continue
            phrase = sentence[a:b]
            if (n == 1 and len(phrase) < 3) or _name_norm(phrase) in NOT_NAMES or not free(a, b):
                continue
            if is_name(phrase) or (n == 1 and _declined_name(phrase, is_name)):
                take(a, b, "name")
                i += n - 1
                break
        i += 1
    marks.sort()
    return marks, cards


def _declined_name(word: str, is_name) -> bool:
    """Vysklonovany nazov: Heywoodu -> Heywood, Jackiem -> Jackie, Arasake -> Arasaka (koren aspon 4 znaky)."""
    for k in (1, 2, 3):
        stem = word[:-k]
        if len(stem) >= 4 and (is_name(stem) or (k == 1 and is_name(stem + "a"))):
            return True
    return False


class Hud(Feature):
    def __init__(self, app):
        super().__init__(app)
        self.hp_critical = app.config.get("game_state", {}).get("hp_critical_threshold", 10)
        self._telemetry_shown = None   # posledny stav poslany na HUD (posiela sa len zmena)
        self._game_line_shown = None
        self._radio = ...              # (stanica, skladba) — prva hodnota po starte sa neukazuje
        self._names = {_name_norm(x) for x in app.config["stt"].get("local_vocabulary") or []} - NOT_NAMES

    # --- telemetria -------------------------------------------------------------------------------

    def on_snapshot(self, snap) -> None:
        shown = {"deaths": self.app.highlights.deaths}
        if snap:
            hp = snap.get("hp")
            money = snap.get("money")
            shown.update(location=snap.location, quest=snap.quest or "", combat=bool(snap.get("combat")),
                         wanted=int(snap.get("wanted") or 0), critical=hp is not None and 0 < hp <= self.hp_critical,
                         money=money if isinstance(money, int) else None, time=_text(snap.get("time")) or "",
                         weather=weather_text(snap.get("weather")) or "")
        if shown != self._telemetry_shown:
            self._telemetry_shown = shown
            self.app.overlay.telemetry(**shown)
        line = self.app.game.line()
        if line != self._game_line_shown:  # ovladacie okno: aktualne zdravie, cas, ciel...
            self._game_line_shown = line
            self.app.overlay.game(live=snap is not None, line=line)
        self._check_radio(snap)

    def _check_radio(self, snap) -> None:
        """Nova skladba v radiu (v aute alebo vreckove) -> karta "now playing" v HUD v2."""
        radio = (_text(snap.get("radio")), _text(snap.get("song"))) if snap else (None, None)
        if radio != self._radio:
            first = self._radio is ...
            self._radio = radio
            if not first and radio[1]:
                self.app.overlay.game_fx("radio", radio[1], radio[0] or "")

    # --- udalosti z hry ---------------------------------------------------------------------------

    def on_game_event(self, name: str, snap, text: str) -> str:
        """Efekt aj ked Mirana mlci. Smrt uz zapocitali momenty na strih (su v zozname pred HUD)."""
        ov, deaths = self.app.overlay, self.app.highlights.deaths
        if name == "death":
            ov.game_fx("death", f"FLATLINE #{deaths}", snap.location or "")
        elif name == "level_up":
            points = [f"+{snap.get(key)} {label}" for key, label in (("attribute_points", "atribút"),
                                                                     ("perk_points", "perk")) if snap.get(key)]
            ov.game_fx("level_up", f"LEVEL {snap.get('level')}", " · ".join(points))
        elif name == "quest_completed":
            prefix = EVENT_TEXT["quest_completed"].split("{")[0]
            ov.game_fx("quest_completed", "QUEST DOKONČENÝ", text.removeprefix(prefix) if text.startswith(prefix) else "")
        elif name == "wanted_up":
            wanted = snap.get("wanted") or 0
            ov.game_fx("wanted", "NCPD " + "★" * wanted, snap.location or "")
        elif name == "district_change":
            detail = " · ".join(x for x in (snap.get("subdistrict"), _text(snap.get("time")),
                                            weather_text(snap.get("weather"))) if x)
            ov.game_fx("district", str(snap.get("district") or snap.location), detail)
        return text

    # --- vety odpovede ----------------------------------------------------------------------------

    def _is_name(self, phrase: str) -> bool:
        return _name_norm(phrase) in self._names or self.app.wiki.has_name(phrase)

    def on_sentence(self, turn, sentence: str, extra: dict) -> None:
        memory = self.app.longterm
        viewers = dict(memory.data.get("viewers") or {}) if memory is not None else {}
        extra["marks"], extra["viewers"] = mark_sentence(sentence, self._is_name, viewers)

    # --- ukazky z Nastaveni -----------------------------------------------------------------------

    def on_command(self, cmd: str, text: str | None) -> bool:
        if cmd == "hud_test" and text:
            threading.Thread(target=self.test, args=(text,), name="hud-test", daemon=True).start()
            return True
        return False

    def test(self, kind: str) -> None:
        """Ukazka efektu na HUD. Len vizual: ziadny model, hlas ani zapis do statistik."""
        app, ov = self.app, self.app.overlay
        snap = app.game.current
        deaths = app.highlights.deaths
        base = {"location": (snap.location if snap else "") or "Watson, Kabuki",
                "quest": (snap.quest if snap else "") or "Jízda", "time": "23:40", "weather": "dážď", "money": 12400}

        def restore(after: float) -> None:
            time.sleep(after)
            self._telemetry_shown = None  # dalsi snimok z hry posle skutocny stav
            if snap is None:
                ov.telemetry(deaths=deaths)
            ov.state(app.status_name)

        def levels(seconds: float, loud: float = 0.8) -> None:
            """Falosny hlas pre gulu: hlasitost a pasma ako pri reci."""
            end = time.time() + seconds
            while time.time() < end:
                t = time.time()
                v = loud * (0.45 + 0.55 * abs((t * 3.1) % 2 - 1))
                ov.level(v, [round(min(1, max(0, v * (0.9 - abs(i - 3.5) / 9) + 0.15 * ((t * 7 + i) % 1))), 2)
                             for i in range(12)])
                time.sleep(0.05)
            ov.level(0.0, None)

        if kind == "level":
            ov.game_fx("level_up", "LEVEL 7", "+1 atribút · +1 perk")
        elif kind == "quest":
            ov.telemetry(**base)
            ov.game_fx("quest_completed", "QUEST DOKONČENÝ", "Jízda")
            time.sleep(1.5)
            ov.telemetry(**{**base, "money": 13600})  # odmena: HUD v2 dopocita "+1 200 €$"
            restore(5)
        elif kind == "death":
            ov.telemetry(**base, deaths=deaths + 1)
            ov.game_fx("death", f"FLATLINE #{deaths + 1}", base["location"])
            restore(6)
        elif kind == "police":
            ov.telemetry(**base, combat=True, wanted=3, deaths=deaths)
            ov.game_fx("wanted", "NCPD ★★★", base["location"])
            restore(7)
        elif kind == "critical":
            ov.telemetry(**base, combat=True, critical=True, deaths=deaths)
            restore(7)
        elif kind == "district":
            ov.game_fx("district", "Watson", "Kabuki · 23:40 · dážď")
        elif kind == "radio":
            ov.game_fx("radio", "Never Fade Away", "89.7 Growl FM")
        elif kind == "db":
            ov.state("processing")
            ov.search(None, app.fillers.search_lines())
            time.sleep(5)
            ov.search("Sebastian Ibarra")
            restore(3)
        elif kind == "scan":
            ov.state("processing")
            ov.scan({"name": "Maelstrom Ganger", "status": "nepriateľ", "level": 8, "hp": 64, "recent": False})
            restore(4)
        elif kind == "listen":
            ov.state("listening")
            levels(2.5, 0.55)
            ov.state("processing")
            ov.stage("prepis", "active")
            time.sleep(1.2)
            ov.stage("prepis", "done", 1.2)
            ov.stage("model", "active")
            time.sleep(1.6)
            ov.stage("model", "done", 1.6)
            restore(0.3)
        elif kind == "viewer":
            ov.state("speaking")
            ov.answer_start()
            sentence = "Kubo_SK, vitaj späť, tretí deň a stále nevieš, kde je Afterlife."
            ov.answer_append(sentence, duration_sec=3.2, marks=[[0, 7, "nick"], [52, 61, "name"]],
                             viewers=[{"nick": "Kubo_SK", "badge": "SUB", "visits": 3, "since": "2026-10-02"}])
            levels(3.4)
            restore(0.2)
        elif kind == "answer":
            ov.state("processing")
            ov.stage("model", "active")
            time.sleep(1.4)
            ov.stage("model", "done", 1.4)
            ov.state("speaking")
            ov.answer_start()
            for sentence in ("Padre je fixer z Heywoodu, kedysi bol medzi Valentinos.",
                             "Kurva, toho chlapa nechceš mať proti sebe."):
                marks, _ = mark_sentence(sentence, self._is_name, {})
                ov.answer_append(sentence, duration_sec=len(sentence) * 0.055, marks=marks)
                levels(len(sentence) * 0.06)
            restore(0.2)
