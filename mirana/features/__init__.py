"""Funkcie Mirany nad jadrom (mirana/app.py): wiki, snimka hry, pamat, momenty na strih, HUD, pripomienky.

Kazda funkcia je trieda odvodena od Feature a prepisuje len metody, ktore potrebuje. Jadro ich vola
v poradi zoznamu v app.py; chyba jednej funkcie sa zaloguje a ostatne bezia dalej. Nova funkcia =
novy subor tu + jeden riadok v app.FEATURES.
"""


class Feature:
    def __init__(self, app):
        self.app = app  # jadro: config, overlay, game, chat, brain, budget, voice, fillers, ptt, highlights

    def start(self) -> None:
        """Pri starte Mirany (hlavne vlakno)."""

    def on_question(self, turn) -> None:
        """Erikova otazka (hlasom alebo pisana) — worker vlakno, este pred kontextom a modelom."""

    def context(self, turn) -> None:
        """Doplni kontext pre model cez turn.add(znacka, riadok) — worker vlakno."""

    def on_answer(self, turn, text: str) -> None:
        """Odpoved, ktoru Erik naozaj pocul (pri preruseni len vyslovene vety) — hlavna slucka."""

    def on_game_event(self, name: str, snap, text: str) -> str:
        """Udalost z hry (vlakno hry). Vrati text pre model, moze ho doplnit."""
        return text

    def on_snapshot(self, snap) -> None:
        """Novy stav hry (alebo None, ked hra nebezi) — vlakno hry, ~2x za sekundu."""

    def on_chat(self, msg) -> None:
        """Sprava z Twitch chatu — vlakno chatu."""

    def on_command(self, cmd: str, text: str | None) -> bool:
        """Prikaz z ovladacieho okna. True = spracovany."""
        return False

    def tick(self) -> None:
        """Hlavna slucka, ked 5 s neprisla ziadna udalost."""

    def shutdown(self) -> None:
        """Pred vypnutim (hlavna slucka)."""
