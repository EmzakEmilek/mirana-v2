"""Safety: posledna kontrola vety pred hlasom a HUD-om.

Zachytena veta sa nevysloví ani nevypise, len zaloguje. Claude sam takmer nikdy nic zle nepovie —
tento filter je poistka pre Kick TOS (nadavky na skupiny ludi, osobne udaje) a hlavne pre chat
divakov, kde sa niekto moze pokusit Miranu prinutit nieco zopakovat.

Zoznam slov je v config.yaml (safety.blocked_words) — porovnava sa zaciatok slova bez ohladu na
velkost pismen a diakritiku, takze staci koren slova.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Osobne udaje nepatria do vysielania: e-maily, telefonne cisla, IP adresy, webove odkazy.
_PERSONAL_DATA = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("telefon", re.compile(r"(?:\+\d{1,3}[\s-]?)?(?:\d{3}[\s-]?){2}\d{3,4}\b")),
    ("ip", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")),
    ("odkaz", re.compile(r"https?://|www\.", re.IGNORECASE)),
]


def _fold(text: str) -> str:
    """Male pismena bez diakritiky — 'Cigán' aj 'cigan' sa porovnaju rovnako."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


class Safety:
    def __init__(self, config: dict):
        cfg = config.get("safety", {})
        self.enabled = cfg.get("enabled", True)
        words = [_fold(w) for w in cfg.get("blocked_words", []) if w.strip()]
        self._blocked = re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")", re.IGNORECASE) if words else None

    def check(self, sentence: str) -> str | None:
        """None = veta je v poriadku, inak dovod, preco ju zahodit."""
        if not self.enabled:
            return None
        for name, pattern in _PERSONAL_DATA:
            if pattern.search(sentence):
                return name
        if self._blocked is not None:
            match = self._blocked.search(_fold(sentence))
            if match:
                return f"slovo '{match.group(0)}'"
        return None
