"""Pripomienka, ked sa Erik dlho neozve: jedna vtipna hlaska (moze siahnut po [HRA])."""

import logging
import time

from mirana.features import Feature

logger = logging.getLogger(__name__)


class IdleNudge(Feature):
    """Nie v boji ani v scene, nie ked Mirana hovori; najviac max_in_row za sebou, potom caka na Erika."""

    def __init__(self, app):
        super().__init__(app)
        cfg = app.config.get("idle_nudge", {})
        self.enabled = cfg.get("enabled", False)
        self.after = float(cfg.get("after_min", 10)) * 60
        self.max_in_row = int(cfg.get("max_in_row", 3))
        self.since = time.time()        # posledna Erikova otazka alebo start — od toho sa meria ticho
        self.last = 0.0
        self.in_row = 0                 # pripomienky bez Erikovej reakcie; po max_in_row zmlkne (je asi AFK)

    def on_question(self, turn) -> None:
        self.since = time.time()
        self.in_row = 0

    def tick(self) -> None:
        app = self.app
        if not self.enabled or app.muted or self.in_row >= self.max_in_row:
            return
        now = time.time()
        if now - max(self.since, self.last) < self.after or app.budget.exceeded():
            return
        if now - app.last_proactive < 60:
            return  # prave sa ozvala k udalosti z hry, nech to nie je dvakrat po sebe
        snap = app.game.current
        if snap is not None and (snap.in_scene or snap.get("combat")):
            return  # skusi znova o chvilu
        minutes = int((now - self.since) // 60)
        if app.start_turn("idle", f"Erik sa ti neozval {minutes} minút.") is None:
            return  # Mirana prave hovori alebo pocuva
        self.last = now
        self.in_row += 1
        logger.info("pripomienka po %d min ticha (%d. za sebou)", minutes, self.in_row)
