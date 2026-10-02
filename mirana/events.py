"""Udalosti v hlavnej fronte Mirany. Vstupy (PTT, okno, hra) a workery ich vkladaju, o vsetkom
rozhoduje jedina hlavna slucka (match podla typu)."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Recording:
    """Erik pustil PTT — WAV nahravka na prepis."""
    wav: bytes


@dataclass(frozen=True)
class Typed:
    """Pisana otazka z ovladacieho okna."""
    text: str


@dataclass(frozen=True)
class GameEvent:
    """Udalost z hry (smrt, level, quest...) — uz zapisana do momentov na strih."""
    name: str
    snap: Any
    text: str


@dataclass(frozen=True)
class Answered:
    """Model dopisal odpoved (aj prerusenu alebo s chybou)."""
    job: Any
    answer: Any
    stt_sec: float = 0.0


@dataclass(frozen=True)
class Spoken:
    """Speaker dohovoril vsetky vety odpovede."""
    job: Any


@dataclass(frozen=True)
class Interrupted:
    """Barge-in: odpoved zrusena, do pamate ide len to, co zaznelo."""
    job: Any


@dataclass(frozen=True)
class Silent:
    """Prazdny prepis (omylom stlacene PTT)."""
    job: Any


@dataclass(frozen=True)
class Fallback:
    """Nahradna hlaska z configu (fallback_phrases[reason])."""
    job: Any
    reason: str


@dataclass(frozen=True)
class Quit:
    """Vypnutie z ovladacieho okna."""
