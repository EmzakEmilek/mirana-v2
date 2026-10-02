"""Cyberpunk Fandom wiki (MediaWiki API, bez kluca) ako nastroj pre model.

Model zavola nastroj `wiki` s anglickym dotazom, keď si nie je isty faktom z lore. Vrati sa
najlepsi clanok ako cisty text: vybrane polia infoboxu (bez stavu a smrti postavy = spoiler),
uvod a pri kratkom uvode aj dalsie sekcie, spolu najviac MAX_CHARS. Vysledky sa drzia v pamati.
"""

import difflib
import json
import logging
import re
import threading
import time
import unicodedata

import requests

from core.config import BASE_DIR
from core.store import write_json

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

TITLES_PATH = BASE_DIR / "data" / "wiki_titles.json"
TITLES_MAX_AGE = 7 * 86400
# Predhladanie len pri otazkach na lore ("kto je X", "co je X", "povedz mi o X")
LORE_QUESTION = re.compile(r"\b(kto|čo|co|aký|aká|aké|akú|odkiaľ|odkial|povedz mi o|čo vieš o|kde (je|nájdem|najdem))\b", re.I)
# Bezne slova a zakladne veci, ktore model pozna (a clanky o nich su plne spoilerov)
STOPWORDS = {"mirana", "emzo", "erik", "kto", "co", "je", "to", "ten", "ta", "toto", "tento", "aky", "aka", "ake",
             "ako", "kde", "mam", "som", "sa", "si", "na", "do", "za", "od", "a", "the", "ok", "teda", "este",
             "ktory", "ktora", "nejaky", "ono", "on", "ona", "oni", "my", "vy", "ja", "ty", "vies", "povedz", "mi",
             "o", "s", "z", "v", "aj", "uz", "len", "tak", "tu", "tam", "auto", "bar", "city", "game", "quest",
             "gig", "perk", "zbran", "level", "hra", "hre", "hry", "mapa", "mape"}
SKIP_TITLES = {"night city", "v", "jackie", "jackie welles", "johnny", "johnny silverhand", "cyberpunk 2077",
               "cyberpunk", "eddies", "quest", "gig", "gigs"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^\w\s-]", " ", text).split())


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
        self._cache: dict[str, tuple[str | None, str]] = {}
        self._articles: dict[str, tuple[str, str]] = {}
        self.prefetch_enabled = cfg.get("prefetch", True)
        self._index: dict[str, str] = {}
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _get(self, **params) -> dict:
        r = self._session.get(API, params={**params, "format": "json"}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def article(self, title: str) -> tuple[str, str]:
        """(skutocny nazov po presmerovani, text clanku). Vynimku nechava volajucemu."""
        with self._lock:
            if title in self._articles:
                return self._articles[title]
        page = self._get(action="parse", page=title, prop="wikitext", redirects=1)["parse"]
        box, body = _find_infobox(_game_templates(page["wikitext"]["*"]))
        facts = infobox_facts(box)
        text = (f"[{facts}]\n" if facts else "") + clean_wikitext(body)
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS].rsplit(" ", 1)[0] + " …"
        result = (page.get("title") or title, text)
        with self._lock:
            self._articles[title] = result
        return result

    # --- predhladanie: clanok k otazke este pred modelom (bez dalsieho kola modelu) ---------------

    def start(self) -> None:
        """Index nazvov clankov: z disku, alebo stiahnut na pozadi (~10 s, raz za tyzden)."""
        if not self.enabled or not self.prefetch_enabled:
            return
        threading.Thread(target=self._load_index, name="wiki-index", daemon=True).start()

    def _load_index(self) -> None:
        try:
            if TITLES_PATH.exists() and time.time() - TITLES_PATH.stat().st_mtime < TITLES_MAX_AGE:
                titles = json.loads(TITLES_PATH.read_text(encoding="utf-8"))
            else:
                titles, params = [], {"action": "query", "list": "allpages", "apnamespace": 0, "aplimit": "max"}
                while True:
                    data = self._get(**params)
                    titles += [p["title"] for p in data["query"]["allpages"]]
                    if "continue" not in data:
                        break
                    params.update(data["continue"])
                write_json(TITLES_PATH, titles)
            index = {}
            for t in titles:
                if "/" in t or t.startswith(("Archived Conversation", "List of")):
                    continue
                base = re.sub(r"\s*\(.*?\)", "", t)
                keys = {_norm(t), _norm(base)}
                rest = base.split(" ", 1)[1] if " " in base else ""
                if " " in rest or re.search(r"\d", rest):  # "Makigai Tanishi T400" aj ako "Tanishi T400"
                    keys.add(_norm(rest))
                for key in keys:
                    if key and key not in SKIP_TITLES:
                        index.setdefault(key, t)
                if base == t and base.startswith("The "):
                    # "The Mox" (gang) ma prednost pred "Mox" (brokovnica): pyta sa skor na organizacie
                    key = _norm(base[4:])
                    if key and key not in SKIP_TITLES:
                        index[key] = t
            self._index = index
            logger.info("wiki index: %d nazvov", len(index))
        except Exception as e:
            logger.warning("wiki index sa nepodarilo nacitat: %s", e)

    def match(self, question: str) -> str | None:
        """Nazov clanku, na ktory sa Erik pyta ("kto je Padre?" -> "Padre"), alebo None."""
        index = self._index
        if not index or not LORE_QUESTION.search(question):
            return None
        words = re.findall(r"[\wÀ-ž'.-]+", question)
        # kandidati: najdlhsie suvisle useky slov (n-gramy do 4), od najdlhsieho
        for n in (4, 3, 2, 1):
            for i in range(len(words) - n + 1):
                gram = " ".join(words[i:i + n]).strip(".'-")
                key = _norm(gram)
                if n == 1 and (len(key) < 3 or key in STOPWORDS):
                    continue
                if key in index:
                    return index[key]
        # preklep z prepisu reci ("Padrej", "Tanishy"): jedno dlhsie slovo s velkym pismenom
        keys = [k for k in index if " " not in k]
        for w in words[1:]:
            key = _norm(w.strip(".'-"))
            if w[:1].isupper() and len(key) >= 5 and key not in STOPWORDS:
                close = difflib.get_close_matches(key, [k for k in keys if k[:1] == key[:1]], n=1, cutoff=0.86)
                if close:
                    return index[close[0]]
        return None

    def prefetch(self, question: str) -> tuple[str, str] | None:
        """(nazov, text) clanku k otazke, alebo None. Pri chybe ticho None (model si moze hladat sam)."""
        if not self.enabled or not self.prefetch_enabled:
            return None
        title = self.match(question)
        if not title:
            return None
        try:
            real, text = self.article(title)
        except Exception as e:
            logger.info("predhladanie %s zlyhalo: %s", title, e)
            return None
        logger.info("wiki predhladanie: %s -> %s", question[:60], real)
        return real, text

    def lookup(self, query: str) -> str:
        return self.search(query)[1]

    def search(self, query: str) -> tuple[str | None, str]:
        """(nazov clanku, text pre model). Pri chybe alebo prazdnom vysledku (None, veta, ktora to povie)."""
        query = " ".join((query or "").split())[:80]
        if not query:
            return None, "Prázdny dotaz."
        key = query.lower()
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        title = None
        try:
            hits = self._get(action="query", list="search", srsearch=query, srlimit=5)["query"]["search"]
            titles = [h["title"] for h in hits if not h["title"].startswith("Archived Conversation")]
            if not titles:
                result = f"Wiki pre „{query}“ nič nenašla."
            else:
                title, text = self.article(titles[0])
                others = ", ".join(titles[1:4])
                result = f"Článok „{title}“: {text or '(prázdny)'}" + (f"\nĎalšie výsledky: {others}" if others else "")
        except Exception as e:
            logger.warning("wiki zlyhala (%s): %s", query, e)
            return None, "Wiki je teraz nedostupná."
        logger.info("wiki: %s -> %s", query, result[:80].replace("\n", " "))
        with self._lock:
            self._cache[key] = (title, result)
        return title, result
