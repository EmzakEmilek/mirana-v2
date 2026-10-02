"""Protokol medzi Miranou a jej klientmi (HUD v OBS, ovladacie okno) — JSON spravy cez WebSocket.

Jedine miesto, kde su typy sprav a ich polia. Overlay posiela len spravy postavene cez event(),
testy kontroluju, ze kazdy typ niekto spracuje (overlay/index.html alebo ui/control.py) a ze okno posiela
len prikazy, ktore Mirana pozna.
"""

# typ -> polia spravy (okrem "type"); None = volne polia (info)
EVENTS: dict[str, tuple[str, ...] | None] = {
    "state": ("state",),                        # idle | listening | processing | speaking | muted
    "level": ("v",),                            # hlasitost 0..1, ~20x/s
    "filler": ("text",),
    "answer_start": (),
    "answer_append": ("text", "ms_per_char"),
    "question": ("text",),                      # systemova hlaska (vypadok hlasu...)
    "search": ("title", "lines"),               # hladanie v databaze (wiki)
    "scan": (),                                 # snimka obrazovky ide modelu
    "game_fx": ("kind", "text"),                # level_up | quest_completed | death | wanted
    "telemetry": ("location", "quest", "combat", "wanted", "critical", "deaths"),
    "erik": ("text",),                          # prepis Erikovej otazky
    "budget": ("spent", "cap"),
    "game": ("live", "line"),                   # riadok [HRA] pre okno
    "info": None,                               # model, effort
    "notice": ("text",),
    "chat_status": ("text",),
}

HUD = {"state", "level", "filler", "answer_start", "answer_append", "question", "search", "scan",
       "game_fx", "telemetry"}
GUI = {"state", "erik", "answer_start", "answer_append", "question", "budget", "game", "info", "notice",
       "chat_status"}

# prikazy z ovladacieho okna: {"type": "command", "cmd": ..., "text": ...}
COMMANDS = {"mute", "quit", "ask", "memory_edit", "hud_test", "volume"}

# spravy, ktore nove pripojenie dostane hned (aktualny stav); ostatne su jednorazove
REMEMBERED = {"state", "telemetry", "budget", "game", "info", "chat_status"}


def event(kind: str, /, **fields) -> dict:
    """Sprava daneho typu. Neznamy typ alebo ine polia su chyba v kode (ValueError)."""
    if kind not in EVENTS:
        raise ValueError(f"neznamy typ spravy: {kind}")
    expected = EVENTS[kind]
    if expected is not None and set(fields) != set(expected):
        raise ValueError(f"{kind}: polia {sorted(fields)}, cakane {sorted(expected)}")
    return {"type": kind, **fields}
