"""Vsetky nastavenia Mirany na jednom mieste: predvolena hodnota, typ, rozsah a popis pre okno Nastavenia.

config.yaml obsahuje Erikove hodnoty (moze byt aj neuplny); load_config() ich doplni predvolenymi
a skontroluje. Zla hodnota (preklep, mimo rozsahu) Miranu nezhodi — pouzije sa predvolena a problem
sa ukaze v diagnostike okna a v logu. Okno Nastavenia sa sklada z tohto zoznamu (ui/settings_window.py):
nastavenie s `tab` a `label` dostane policko automaticky, Block oznacuje vlastnu cast okna (testy zvuku...).
"""

import copy
import re
from dataclasses import dataclass
from typing import Any

MISSING = object()

MODELS = {
    "claude-opus-5-5": "najlepšie lore; low ~$1,50 / 4 h (občas kalky), medium ~$1,95 / 4 h, pomalší",
    "claude-sonnet-5-5": "najrýchlejší (low ~2 s), ~$0,95 / 4 h, čistá slovenčina, slabšie lore",
    "claude-opus-5": "staršia generácia, ~$1,00 / 4 h",
    "claude-sonnet-5": "staršia generácia, ~$0,30 / 4 h, častejšie si vymýšľa lore",
    "claude-haiku-4-5": "najlacnejší, na rozhovor slabý",
}
VOICES = ("sk-SK-ViktoriaNeural", "sk-SK-LukasNeural", "en-US-EmmaMultilingualNeural", "en-US-AvaMultilingualNeural",
          "pl-PL-AgnieszkaNeural", "pl-PL-ZofiaNeural")  # poľské = slovenský text s poľským prízvukom, pre srandu
EFFECTS = {"vypnute": "vypnuté", "jemny": "jemný", "night_city": "Night City", "robot": "robot"}
KEYS = tuple(f"f{i}" for i in range(1, 13)) + ("insert", "home", "end", "page_up", "page_down", "pause",
                                              "scroll_lock", "mouse_x1", "mouse_x2", "mouse_middle")
GAME_EVENTS = {"hp_critical": "kritické HP", "hp_low": "nízke HP", "death": "smrť", "level_up": "nový level",
               "district_change": "nová štvrť", "quest_changed": "nový quest", "quest_completed": "dokončený quest",
               "wanted_up": "polícia ho hľadá", "wanted_clear": "polícia prestala", "combat_start": "začiatok boja",
               "combat_end": "koniec boja"}
TABS = ("Zvuk", "Hlas", "Model", "Hra", "Prepis", "Fillery", "HUD", "Chat", "Bezpečnosť", "Pamäť", "Persona")


@dataclass(frozen=True, eq=False)
class S:
    """Jedno nastavenie. kind: bool int float str choice list percent key flag any (prazdny = podla default)."""
    key: str
    default: Any
    kind: str = ""
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()
    nullable: bool = False
    on: Any = True                 # flag: hodnota pri zapnutom prepinaci (vypnuty = None)
    # okno Nastavenia
    tab: str = ""
    label: str = ""
    hint: str = ""
    widget: str = ""               # switch entry slider combo segmented lines checks key device_in/out/stream
    width: int = 0
    fmt: str = ""                  # slider: "{:+d} %"
    labels: dict | None = None     # zobrazovane mena volieb
    choice_hints: dict | None = None
    suggest: tuple = ()            # combo: navrhy, ale da sa napisat aj ine
    lower: bool = False            # lines: male pismena

    @property
    def type(self) -> str:
        if self.kind:
            return self.kind
        d = self.default
        return ("bool" if isinstance(d, bool) else "int" if isinstance(d, int) else "float" if isinstance(d, float)
                else "list" if isinstance(d, list) else "any" if isinstance(d, dict) else "str")

    def error(self, value) -> str | None:
        """None = hodnota je v poriadku, inak ludsky popis problemu."""
        if value is None:
            return None if self.nullable or self.type in ("flag", "any") else "chýba hodnota"
        t = self.type
        if t == "bool":
            return None if isinstance(value, bool) else "má byť true/false"
        if t in ("int", "float"):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or (t == "int" and not isinstance(value, int)):
                return "má byť celé číslo" if t == "int" else "má byť číslo"
            return self._range(value)
        if t in ("str", "key"):
            if not isinstance(value, str):
                return "má byť text"
            if t == "key":
                if not value.strip():
                    return None if self.nullable else "chýba hodnota"
                return _key_error(value)
            return None
        if t == "choice":
            return None if value in self.choices else f"neznáma voľba {value!r} (možnosti: {', '.join(self.choices)})"
        if t == "list":
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                return "má byť zoznam textov"
            bad = [x for x in value if self.choices and x not in self.choices]
            return f"neznáme položky {bad}" if bad else None
        if t == "percent":
            m = re.fullmatch(r"([+-]?\d+)%", str(value).strip())
            return "má byť percento, napr. +10%" if not m else self._range(int(m.group(1)))
        if t == "flag":
            return None if value == self.on else f"má byť {self.on!r} alebo null"
        return None

    def _range(self, value) -> str | None:
        if self.lo is not None and value < self.lo:
            return f"najmenej {self.lo:g}"
        if self.hi is not None and value > self.hi:
            return f"najviac {self.hi:g}"
        return None


@dataclass(frozen=True, eq=False)
class Block:
    """Vlastna cast okna Nastavenia (ui/settings_window.py: metoda _block_<name>)."""
    name: str
    tab: str


def _key_error(value: str) -> str | None:
    from mirana.inputs.ptt import parse_key  # pynput az ked treba
    try:
        parse_key(value)
        return None
    except ValueError:
        return f"neznámy kláves {value!r}"


SETTINGS = (
    # --- zvuk -------------------------------------------------------------------------------------
    S("audio.input_device", None, "str", nullable=True, tab="Zvuk", label="Mikrofón", widget="device_in"),
    S("audio.output_device", "default", tab="Zvuk", label="Výstup", widget="device_out",
      hint="Kam Mirana hovorí. Predvolený výstup Windows = tam, kam ide zvuk hry."),
    S("audio.stream_output_device", None, "str", nullable=True, tab="Zvuk", label="Výstup pre stream", widget="device_stream",
      hint="Druhý výstup naraz, napr. slúchadlá + HDMI do strihovej karty. Väčšinou vypnutý."),
    Block("devices", "Zvuk"),
    S("audio.volume", 100, lo=0, hi=150),                       # posuvnik v hlavnom okne
    S("audio.output_latency_ms", 100, lo=20, hi=500),
    S("audio.sample_rate", None, "int", nullable=True, lo=8000, hi=192000),
    S("audio.ptt_key", "f4", "key", tab="Zvuk", label="Kláves na hovor (drž)", widget="key",
      hint="Aj tlačidlo myši: mouse_x1 = zadné bočné, mouse_x2 = predné bočné. Hra ho dostane tiež, "
           "tak nech v nej nemá priradenú akciu. „Stlačiť…“ = nastav stlačením."),
    S("audio.panic_mute_key", "f11", "key", tab="Zvuk", label="Panic mute", widget="key"),
    S("audio.marker_key", None, "key", nullable=True, tab="Zvuk", label="Značka na strih", widget="key",
      hint="Ťuknutie zapíše čas vo VOD-ke do logs/strih-<dátum>.md. Prázdne = vypnuté."),

    # --- prepis reci ------------------------------------------------------------------------------
    S("stt.provider", "local", "choice", choices=("local", "api"), tab="Prepis", label="Prepis reči", width=160,
      hint="local = Whisper na grafike (najlepšie mená z hry). api = OpenAI Whisper."),
    S("stt.local_model", "medium", tab="Prepis", label="Whisper model", widget="combo", width=200,
      suggest=("small", "medium", "large-v3", "large-v3-turbo"),
      hint="medium = overený kompromis. large-v3 = presnejší, ~2× pomalší, viac VRAM. large-v3-turbo v teste prekladal do angličtiny."),
    S("stt.language", "sk", tab="Prepis", label="Jazyk", width=60),
    S("stt.api_model", "whisper-1"),
    S("stt.local_device", "cuda", "choice", choices=("cuda", "cpu")),
    S("stt.local_compute_type", "float16", "choice", choices=("float16", "int8_float16", "int8"),
      labels={"float16": "float16 (odporúčané)", "int8_float16": "int8_float16 (menej VRAM)",
              "int8": "int8 (najúspornejší)"},
      tab="Prepis", label="Výpočet na grafike", width=260,
      hint="float16 = v hre najrýchlejší (test 3.10.: int8_float16 bol pomalší, 3,0 s oproti 2,2 s)."),
    S("stt.local_beam_size", 3, lo=1, hi=5, tab="Prepis", label="Presnosť prepisu (beam)", widget="slider", fmt="{}",
      hint="Koľko variantov vety Whisper skúša. 5 = najpresnejšie a najpomalšie, 1 = najrýchlejšie. Odporúčané 3."),
    S("stt.local_prompt_prefix", "Erik sa po slovensky pýta Mirany na Cyberpunk 2077:"),
    S("stt.local_vocabulary", []),

    # --- model ------------------------------------------------------------------------------------
    S("llm.model", "claude-sonnet-5-5", "choice", choices=tuple(MODELS), tab="Model", label="Model", width=260,
      choice_hints=MODELS),
    S("llm.effort", "low", "choice", choices=("low", "medium", "high"), tab="Model", label="Effort (premýšľanie)",
      widget="segmented", hint="low = najrýchlejšia odpoveď. Vyšší effort = presnejšie, ale pomalšie a drahšie."),
    S("llm.fallbacks", "default", "flag", on="default", tab="Model", label="Záložný model",
      hint="Keď bezpečnostný filter omylom odmietne otázku, zopakuje ju iný model (len Opus)."),
    S("llm.max_tokens", 2000, lo=200, hi=16000),
    S("llm.cache_persona", True),
    S("llm.cache_memory", True),
    S("limits.daily_usd_cap", 5.0, "float", lo=0.1, tab="Model", label="Denný strop ($)",
      hint="Po jeho dosiahnutí Mirana do polnoci neodpovedá."),
    S("memory.max_exchanges", 30, lo=1, hi=200, tab="Model", label="Pamäť (výmen)",
      hint="Koľko otázok a odpovedí si pamätá. Viac = lepšie nadväzuje, mierne drahšie."),
    S("memory.trim_to", 15, lo=0, hi=200, tab="Model", label="Po zaplnení ponechať"),

    # --- hlas -------------------------------------------------------------------------------------
    S("tts.voice", "sk-SK-ViktoriaNeural", tab="Hlas", label="Hlas (Azure)", widget="combo", suggest=VOICES,
      hint="Viktoria = slovenský hlas. Emma/Ava = viacjazyčné (fonetiku vypni). Agnieszka/Zofia = poľský prízvuk, pre srandu."),
    S("tts.rate", "0%", "percent", lo=-30, hi=50, tab="Hlas", label="Rýchlosť reči", fmt="{:+d} %",
      hint="0 % = prirodzené tempo Azure. +10 až +20 % znie svižnejšie a stále zrozumiteľne."),
    S("tts.sentence_pause_ms", 250, lo=100, hi=800, tab="Hlas", label="Pauza medzi vetami", widget="slider", fmt="{} ms",
      hint="Ticho medzi vetami odpovede. Bez orezania by bolo ~900 ms."),
    S("tts.pitch", "0%", "percent", lo=-20, hi=20, tab="Hlas", label="Výška hlasu", fmt="{:+d} %"),
    S("tts.phonetics_file", "phonetics.yaml", "flag", on="phonetics.yaml", tab="Hlas", label="Fonetika anglických názvov",
      hint="Prepíše „Night City“ na „Najt Siti“ pre slovenský hlas (phonetics.yaml)."),
    S("tts.effects.enabled", True),
    S("tts.effects.preset", "vypnute", "choice", choices=tuple(EFFECTS), labels=EFFECTS, tab="Hlas", label="Efekty hlasu",
      width=160, hint="Night City = digitálna AI (filtre, zrnitosť, kovový nádych, echo). Platí aj pre fillery; vyskúšaj tlačidlom Vypočuť."),
    S("tts.effects.params", {}),
    Block("voice_preview", "Hlas"),

    # --- hra --------------------------------------------------------------------------------------
    Block("game_mod", "Hra"),
    S("game_state.enabled", True, tab="Hra", label="Telemetria z hry",
      hint="Mirana vie, kde si, aký máš quest, HP a či bojuješ. Bez bežiacej hry sa nič nedeje."),
    S("game_state.json_path", "auto", tab="Hra", label="Súbor stavu", width=420,
      hint="auto = nájde hru sama. Inak cesta k state.json z CET modu."),
    S("game_state.hp_low_threshold", 25, lo=1, hi=99, tab="Hra", label="Nízke HP (%)", width=60),
    S("game_state.hp_critical_threshold", 10, lo=1, hi=99, tab="Hra", label="Kritické HP (%)", width=60),
    S("limits.proactive_cooldown_sec", 300, lo=0, tab="Hra", label="Pauza medzi hláškami (s)", width=60,
      hint="Sama od seba sa ozve najviac raz za tento čas. Kritické HP a smrť majú výnimku. Počas rozhovorov a cutscén mlčí."),
    S("game_state.speak_on", ["hp_critical", "death", "level_up", "quest_completed"], choices=tuple(GAME_EVENTS),
      labels=GAME_EVENTS, tab="Hra", label="Kedy sa ozve sama", widget="checks"),
    S("game_state.poll_interval_sec", 0.5, lo=0.1, hi=10),
    S("game_state.stale_after_sec", 10, lo=2, hi=600),
    S("game_state.quiet_after_erik_sec", 30, lo=0, hi=600),

    # --- fillery, wiki, pripomienka ---------------------------------------------------------------
    S("fillers.enabled", True, tab="Fillery", label="Filler hlášky"),
    S("fillers.speak", False, tab="Fillery", label="Hovoriť ich nahlas",
      hint="Vypnuté = filler sa len ukáže na HUD, Mirana ho nepovie."),
    S("fillers.skip_if_faster_than_ms", 1300, lo=500, hi=3000, tab="Fillery", label="Pauza pred fillerom",
      widget="slider", fmt="{} ms", hint="Keď odpoveď príde skôr, filler sa nezahrá."),
    S("fillers.lines", ["sekundu, Emzo", "premýšľam", "momentík"], tab="Fillery", label="Hlášky (jedna na riadok)"),
    S("wiki.enabled", True, tab="Fillery", label="Hľadať vo wiki",
      hint="Pri lore otázkach Mirana pozrie Cyberpunk Fandom wiki. Hlášky pri hľadaní (nahlas):"),
    S("fillers.search_lines", ["hľadám v databáze"], tab="Fillery", label="Hlášky pri hľadaní"),
    S("wiki.max_lookups", 2, lo=0, hi=5),
    S("wiki.prefetch", True),
    S("wiki.timeout_sec", 5, "float", lo=1, hi=30),
    S("idle_nudge.enabled", True, tab="Fillery", label="Pripomenúť sa po tichu",
      hint="Keď sa dlho neozveš, Mirana sa vtipne ozve sama (nie v boji ani v cutscéne)."),
    S("idle_nudge.after_min", 10, "float", lo=1, tab="Fillery", label="Po koľkých minútach", width=60),
    S("idle_nudge.max_in_row", 3, lo=1, hi=20),

    # --- HUD --------------------------------------------------------------------------------------
    S("overlay.enabled", True, tab="HUD", label="HUD zapnutý"),
    S("overlay.hud", "v2", "choice", choices=("v1", "v2"), tab="HUD", label="Vzhľad HUD", width=260,
      labels={"v1": "v1 · klasický panel", "v2": "v2 · Friday + Kiroshi"},
      hint="Otvorený HUD v OBS sa po reštarte Mirany prepne sám. v2 je robený na zdroj 700×250 (dá sa zväčšiť)."),
    S("overlay.port", 8080, lo=1024, hi=65535, tab="HUD", label="Port", hint="OBS Browser Source: http://IP-herného-PC:port"),
    S("overlay.typewriter_ms_per_char", 26, lo=5, hi=200, tab="HUD", label="Písanie (ms/znak)",
      hint="Len záloha, keď hlas vypadne. Inak sa text píše v tempe reči."),
    S("overlay.host", "0.0.0.0"),
    Block("hud_tests", "HUD"),

    # --- chat -------------------------------------------------------------------------------------
    S("twitch_chat.enabled", False, tab="Chat", label="Čítať Twitch chat",
      hint="Mirana chat len číta (bez bota, nič nepíše). Sama ho nekomentuje, len keď sa spýtaš, napr. „čo píše chat?“"),
    S("twitch_chat.channel", "", tab="Chat", label="Kanál", width=260, hint="Názov kanála alebo odkaz, napr. twitch.tv/tvojkanal."),
    S("twitch_chat.max_messages", 15, lo=1, hi=100, tab="Chat", label="Posledných správ", width=60,
      hint="Koľko posledných správ Mirana vidí pri tvojej otázke."),
    S("twitch_chat.max_age_sec", 300, lo=10, tab="Chat", label="Nie staršie ako (s)", width=60),
    S("twitch_chat.max_chars", 150, lo=20, hi=500),
    S("twitch_chat.ignore_users", ["nightbot", "streamelements"], tab="Chat", label="Ignorovaní boti (jeden na riadok)",
      lower=True),

    # --- bezpecnost -------------------------------------------------------------------------------
    S("safety.enabled", True, tab="Bezpečnosť", label="Bezpečnostný filter",
      hint="E-maily, telefónne čísla, IP adresy a odkazy sa nevyslovia nikdy."),
    S("safety.blocked_words", [], tab="Bezpečnosť", label="Zakázané slová (jedno na riadok, stačí začiatok slova)"),

    # --- pamat, snimka, limity, hlasky, log -------------------------------------------------------
    Block("memory", "Pamäť"),
    Block("persona", "Persona"),
    S("vision.enabled", True),
    S("vision.window_title", "Cyberpunk 2077"),
    S("vision.max_width", 1280, lo=320, hi=3840),
    S("longterm.enabled", True),
    S("longterm.model", "claude-sonnet-5-5", "choice", choices=tuple(MODELS)),
    S("longterm.checkpoint_min", 30, "float", lo=5),
    S("longterm.max_facts", 25, lo=1, hi=200),
    S("longterm.viewer_notes", 3, lo=0, hi=20),
    S("limits.api_timeout_sec", 20, "float", lo=5, hi=120),
    S("limits.tts_timeout_sec", 10, "float", lo=2, hi=60),
    S("limits.api_retries", 1, lo=0, hi=5),
    S("fallback_phrases.stt_failed", "Nerozumela som ti, Emzo. Zopakuj to."),
    S("fallback_phrases.llm_failed", "Spojenie s Netom vypadlo. Skús to o chvíľu."),
    S("fallback_phrases.tts_failed", "Hlas mi vypadol, Emzo. Odpoveď máš na HUDe."),
    S("fallback_phrases.budget_reached", "Dnešný rozpočet je vyčerpaný. Zajtra som späť."),
    S("fallback_phrases.general_error", "Mám chybu v systéme. Pracujem na tom."),
    S("logging.level", "INFO", "choice", choices=("DEBUG", "INFO", "WARNING", "ERROR")),
    S("logging.archive_after_days", 14, lo=1, hi=365),
)

BY_KEY = {s.key: s for s in SETTINGS if isinstance(s, S)}


def get(cfg: dict, key: str, default=MISSING):
    node = cfg
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def put(cfg: dict, key: str, value) -> None:
    *path, last = key.split(".")
    node = cfg
    for part in path:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[last] = value


def defaults() -> dict:
    cfg: dict = {}
    for s in BY_KEY.values():
        put(cfg, s.key, copy.deepcopy(s.default))
    return cfg


def _leaves(node, prefix=""):
    for k, v in node.items():
        key = f"{prefix}{k}"
        if key in BY_KEY:
            yield key
        elif isinstance(v, dict) and v:
            yield from _leaves(v, key + ".")
        else:
            yield key


def cross_check(cfg: dict) -> list[str]:
    """Pravidla medzi viacerymi nastaveniami (plati pri starte aj v okne Nastavenia)."""
    problems = []
    if get(cfg, "memory.trim_to", 0) > get(cfg, "memory.max_exchanges", 0):
        problems.append("„Po zaplnení ponechať“ nemôže byť viac ako veľkosť pamäte.")
    if get(cfg, "game_state.hp_critical_threshold", 0) >= get(cfg, "game_state.hp_low_threshold", 100):
        problems.append("Kritické HP musí byť nižšie ako nízke HP.")
    keys = [k for k in (get(cfg, "audio.ptt_key", None), get(cfg, "audio.panic_mute_key", None),
                        get(cfg, "audio.marker_key", None)) if k]
    if len(keys) != len(set(keys)):
        problems.append("Kláves na hovor, panic mute a značka musia byť rôzne.")
    if get(cfg, "fillers.enabled", False) and not get(cfg, "fillers.lines", []):
        problems.append("Zapnuté fillery potrebujú aspoň jednu hlášku.")
    return problems


def resolve(raw: dict | None) -> tuple[dict, list[str]]:
    """config.yaml -> uplny config (chybajuce a zle hodnoty = predvolene) + zoznam problemov."""
    cfg = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    problems = []
    for key in _leaves(cfg):
        if key not in BY_KEY:
            problems.append(f"{key}: neznáme nastavenie (Mirana ho ignoruje)")
    for s in BY_KEY.values():
        value = get(cfg, s.key)
        if value is MISSING:
            put(cfg, s.key, copy.deepcopy(s.default))
            continue
        err = s.error(value)
        if err:
            problems.append(f"{s.key}: {err} — použitá predvolená hodnota {s.default!r}")
            put(cfg, s.key, copy.deepcopy(s.default))
    return cfg, problems + cross_check(cfg)
