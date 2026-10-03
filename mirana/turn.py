"""Turn: jedna otazka alebo hlaska Mirany — odkial prisla, kontext pre model a priebeh odpovede.

Kontext zbieraju funkcie (features) do pomenovanych riadkov; poradie v sprave pre model je pevne
(CONTEXT_ORDER), nezavisle od poradia funkcii. Do kratkej pamate ide len `tagged` (otazka bez
kontextu): [HRA] a [CHAT] tvorili 85 % pamate a v kazdej novej sprave su aj tak aktualne.
"""

import threading
import time
from dataclasses import dataclass, field

TAGS = {"voice": "ERIK", "typed": "ERIK", "game": "GAME_EVENT", "idle": "IDLE"}
CONTEXT_ORDER = ("HRA", "STREAM", "WIKI", "OBRAZOVKA", "CHAT", "DIVÁCI", "SYSTÉM")


@dataclass
class Turn:
    gen: int                                 # generacia — barge-in ju zvysi a stary turn sa zahodi
    source: str = "voice"                    # voice | typed | game | idle
    released_at: float = field(default_factory=time.perf_counter)  # pustenie PTT / udalost
    question: str = ""                       # Erikova otazka (alebo text udalosti) bez znacky
    context: dict[str, str] = field(default_factory=dict)  # znacka -> cely riadok ("[HRA] ...")
    image: str | None = None                 # snimka hry (base64 JPEG) pri "co je toto?"
    stt_sec: float = 0.0
    asked_at: float = 0.0                    # kedy sa otazka poslala modelu (faza "model" v HUD v2)
    prompt: str | None = None                # sprava pre model; None = model sa este nepytal

    # priebeh odpovede (cita ho Speaker, stream v Brain aj hlavna slucka)
    filler_timer: threading.Timer | None = None
    cancelled: bool = False                  # barge-in
    started: bool = False                    # prva veta uz znie (nastavuje Speaker)
    tts_failed: bool = False
    first_sentence: bool = True
    searched: bool = False                   # hlaska "hladam v databaze" uz zaznela
    remember: bool = True                    # fallback hlasky sa do pamate nedavaju
    answer: object | None = None             # core Answer
    spoken: list[str] = field(default_factory=list)
    remembered: bool = False

    @property
    def from_erik(self) -> bool:
        return self.source in ("voice", "typed")

    @property
    def tagged(self) -> str:
        return f"[{TAGS[self.source]}] {self.question}"

    def add(self, tag: str, line: str | None) -> None:
        """Riadok kontextu (uz so znackou, napr. "[HRA] zdravie 80 %"). Prazdny sa nepridava."""
        if tag not in CONTEXT_ORDER:
            raise ValueError(f"neznama znacka kontextu: {tag}")
        if line:
            self.context[tag] = line

    def build_prompt(self) -> str:
        lines = [self.context[tag] for tag in CONTEXT_ORDER if tag in self.context]
        return "\n".join(lines + [self.tagged])
