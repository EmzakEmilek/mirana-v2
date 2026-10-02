"""Cyberpunk Fandom wiki (MediaWiki API, bez kluca) ako nastroj pre model.

Model zavola nastroj `wiki` s anglickym dotazom, keď si nie je isty faktom z lore. Vrati sa
najlepsi clanok ako cisty text: vybrane polia infoboxu (bez stavu a smrti postavy = spoiler),
uvod a pri kratkom uvode aj dalsie sekcie, spolu najviac MAX_CHARS. Vysledky sa drzia v pamati.
"""

import logging
import re
import threading

import requests

logger = logging.getLogger(__name__)

API = "https://cyberpunk.fandom.com/api.php"
HEADERS = {"User-Agent": "MiranaStreamCompanion/1.0 (Cyberpunk 2077 stream assistant)"}
MAX_CHARS = 1800

TOOL = {
    "name": "wiki",
    "description": (
        "Search the Cyberpunk wiki (Fandom) and return the best matching article. "
        "Use it only when you are not sure about a lore fact: a character, gang, corporation, place, "
        "vehicle, weapon, cyberware, item, quest name or term. Query in English, short, e.g. "
        "'Padre', 'Eurodollar', 'Tanishi T400', 'Royce'. Not needed for things you know well."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Short English search query"}},
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}

# Polia infoboxu, ktore NEposielame: stav a smrt su spoilery, ostatne je balast
SKIP_FIELDS = re.compile(
    r"status|dod|death|died|fate|killed|image|caption|voiced|appears|quote|gallery|"
    r"title|level|partner|relative|place_of_birth|dob|age|hair|eyes|gender|ref",
    re.I,
)
CP_TEMPLATE = re.compile(r"\{\{CP\|([^}|]+)[^}]*\}\}")
ITEM_TEMPLATE = re.compile(r"\{\{(?:R|Item|W|Wpn)\|(?:[^}|]*\|)*([^}|]+)\}\}")


def _game_templates(text: str) -> str:
    """{{CP|2077}} -> Cyberpunk 2077, {{R|I|Seraph}} -> Seraph (inak by po zmazani ostali diery)."""
    text = CP_TEMPLATE.sub(r"Cyberpunk \1", text)
    return ITEM_TEMPLATE.sub(r"\1", text)


def _strip_templates(text: str) -> str:
    """Zmaze {{...}} aj vnorene (citacie, spoiler sablony)."""
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    return text


def clean_wikitext(text: str) -> str:
    text = _strip_templates(_game_templates(text))
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"\{\|.*?\|\}", "", text, flags=re.S)  # tabulky
    text = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", "", text, flags=re.I)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)  # [[a|b]] -> b, [[a]] -> a
    text = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", text)
    text = re.sub(r"<br\s*/?>", ", ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\1:", text, flags=re.M)
    text = re.sub(r"__\w+__", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _find_infobox(text: str) -> tuple[str, str]:
    """Prvy {{Infobox ...}} (vyvazene zatvorky) -> (obsah, text bez neho)."""
    start = text.find("{{Infobox")
    if start < 0:
        return "", text
    depth, i = 0, start
    while i < len(text) - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            depth += 1
            i += 2
        elif pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return text[start + 2:i - 2], text[:start] + text[i:]
        else:
            i += 1
    return "", text


def infobox_facts(box: str) -> str:
    facts = []
    for line in box.split("\n|")[1:]:
        key, _, value = line.partition("=")
        key = key.strip()
        value = " ".join(clean_wikitext(value).split()).strip(" ,")
        if key and value and not SKIP_FIELDS.search(key):
            facts.append(f"{key.replace('_', ' ')}: {value}")
    return "; ".join(facts)


class Wiki:
    def __init__(self, config: dict):
        cfg = config.get("wiki", {})
        self.enabled = cfg.get("enabled", False)
        self.timeout = cfg.get("timeout_sec", 5)
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _get(self, **params) -> dict:
        r = self._session.get(API, params={**params, "format": "json"}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def lookup(self, query: str) -> str:
        """Text pre model. Pri chybe alebo prazdnom vysledku vrati vetu, ktora to povie (model nema hadat)."""
        query = " ".join((query or "").split())[:80]
        if not query:
            return "Prázdny dotaz."
        key = query.lower()
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        try:
            hits = self._get(action="query", list="search", srsearch=query, srlimit=5)["query"]["search"]
            titles = [h["title"] for h in hits if not h["title"].startswith("Archived Conversation")]
            if not titles:
                result = f"Wiki pre „{query}“ nič nenašla."
            else:
                page = self._get(action="parse", page=titles[0], prop="wikitext", redirects=1)
                box, body = _find_infobox(_game_templates(page["parse"]["wikitext"]["*"]))
                facts = infobox_facts(box)
                text = (f"[{facts}]\n" if facts else "") + clean_wikitext(body)
                if len(text) > MAX_CHARS:
                    text = text[:MAX_CHARS].rsplit(" ", 1)[0] + " …"
                others = ", ".join(titles[1:4])
                result = f"Článok „{titles[0]}“: {text or '(prázdny)'}" + (f"\nĎalšie výsledky: {others}" if others else "")
        except Exception as e:
            logger.warning("wiki zlyhala (%s): %s", query, e)
            return "Wiki je teraz nedostupná."
        logger.info("wiki: %s -> %s", query, result[:80].replace("\n", " "))
        with self._lock:
            self._cache[key] = result
        return result
