"""Denny strop nakladov na LLM: pocita cenu z usage kazdej odpovede, drzi ju v data/budget.json.

Stav prezije restart (inak by kazdy restart vynuloval strop). Novy den (lokalny cas) = novy rozpocet.
Whisper bezi lokalne a Azure TTS je vo free tieri, preto sa pocita len Claude.
"""

import logging
import threading

from core.config import BASE_DIR
from core.store import DailyJson

logger = logging.getLogger(__name__)

BUDGET_PATH = BASE_DIR / "data" / "budget.json"

# USD za milion tokenov: (input, cache read, cache write 5 min, output). Zdroj: claude-api skill, 2026-09.
PRICES = {
    "claude-opus-5-5": (4.0, 0.20, 5.0, 20.0),
    "claude-opus-5": (5.0, 0.50, 6.25, 25.0),
    "claude-sonnet-5-5": (2.0, 0.20, 2.5, 10.0),
    "claude-sonnet-5": (2.0, 0.20, 2.5, 10.0),
    "claude-haiku-4-5": (1.0, 0.10, 1.25, 5.0),
}


def cost_usd(model: str, usage) -> float:
    price = PRICES.get(model)
    if price is None:
        logger.warning("neznama cena modelu %s, pocitam ako Opus 5", model)
        price = PRICES["claude-opus-5"]
    return (
        usage.input_tokens * price[0]
        + (usage.cache_read_input_tokens or 0) * price[1]
        + (usage.cache_creation_input_tokens or 0) * price[2]
        + usage.output_tokens * price[3]
    ) / 1e6


class Budget:
    """Thread-safe pocitadlo dennych nakladov s tvrdym stropom limits.daily_usd_cap."""

    def __init__(self, config: dict):
        self.cap = float(config["limits"]["daily_usd_cap"])
        self._lock = threading.Lock()
        self._day = DailyJson(BUDGET_PATH, {"usd": 0.0})
        logger.info("rozpocet dnes: $%.3f z $%.2f", self.spent, self.cap)

    @property
    def spent(self) -> float:
        with self._lock:
            self._day.roll()
            return float(self._day.data["usd"])

    def exceeded(self) -> bool:
        return self.spent >= self.cap

    def add(self, model: str, usage) -> float:
        """Zapocita odpoved, vrati jej cenu. Pri prekroceni stropu zaloguje varovanie."""
        cost = cost_usd(model, usage)
        with self._lock:
            self._day.roll()
            spent = float(self._day.data["usd"]) + cost
            self._day.data["usd"] = round(spent, 5)
            self._day.save()
        if spent >= self.cap:
            logger.warning("DENNY STROP DOSIAHNUTY: $%.3f / $%.2f — dalsie otazky sa neposielaju", spent, self.cap)
        return cost
