"""HUD v OBS: telemetria z hry (lokacia, quest, boj, policia, smrti), efekty pri udalostiach a
ukazky efektov z okna Nastavenia -> HUD."""

import threading
import time

from mirana.features import Feature


class Hud(Feature):
    def __init__(self, app):
        super().__init__(app)
        self.hp_critical = app.config.get("game_state", {}).get("hp_critical_threshold", 10)
        self._telemetry_shown = None   # posledny stav poslany na HUD (posiela sa len zmena)
        self._game_line_shown = None

    def on_snapshot(self, snap) -> None:
        shown = {"deaths": self.app.highlights.deaths}
        if snap:
            hp = snap.get("hp")
            shown.update(location=snap.location, quest=snap.quest or "", combat=bool(snap.get("combat")),
                         wanted=int(snap.get("wanted") or 0), critical=hp is not None and 0 < hp <= self.hp_critical)
        if shown != self._telemetry_shown:
            self._telemetry_shown = shown
            self.app.overlay.telemetry(**shown)
        line = self.app.game.line()
        if line != self._game_line_shown:  # ovladacie okno: aktualne zdravie, cas, ciel...
            self._game_line_shown = line
            self.app.overlay.game(live=snap is not None, line=line)

    def on_game_event(self, name: str, snap, text: str) -> str:
        """Efekt aj ked Mirana mlci. Smrt uz zapocitali momenty na strih (su v zozname pred HUD)."""
        ov, deaths = self.app.overlay, self.app.highlights.deaths
        if name == "death":
            ov.game_fx("death", f"FLATLINE #{deaths}")
        elif name == "level_up":
            ov.game_fx("level_up", f"LEVEL {snap.get('level')}")
        elif name == "quest_completed":
            ov.game_fx("quest_completed", "QUEST DOKONČENÝ")
        elif name == "wanted_up":
            ov.game_fx("wanted", "NCPD " + "★" * (snap.get("wanted") or 0))
        return text

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
                "quest": (snap.quest if snap else "") or "Jízda"}

        def restore(after: float) -> None:
            time.sleep(after)
            self._telemetry_shown = None  # dalsi snimok z hry posle skutocny stav
            if snap is None:
                ov.telemetry(deaths=deaths)
            ov.state(app.status_name)

        if kind == "level":
            ov.game_fx("level_up", "LEVEL 7")
        elif kind == "quest":
            ov.game_fx("quest_completed", "QUEST DOKONČENÝ")
        elif kind == "death":
            ov.telemetry(**base, deaths=deaths + 1)
            ov.game_fx("death", f"FLATLINE #{deaths + 1}")
            restore(5)
        elif kind == "police":
            ov.telemetry(**base, combat=True, wanted=3, deaths=deaths)
            ov.game_fx("wanted", "NCPD ★★★")
            restore(6)
        elif kind == "critical":
            ov.telemetry(**base, combat=True, critical=True, deaths=deaths)
            restore(6)
        elif kind == "db":
            ov.state("processing")
            ov.search(None, app.fillers.search_lines())
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
