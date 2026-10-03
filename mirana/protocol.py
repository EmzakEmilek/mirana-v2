"""Protokol medzi Miranou a jej klientmi (HUD v OBS, ovladacie okno) — JSON spravy cez WebSocket.

Jedine miesto, kde su typy sprav a ich polia. Overlay posiela len spravy postavene cez event(),
testy kontroluju, ze kazdy typ niekto spracuje (overlay/index.html alebo ui/control.py) a ze okno posiela
len prikazy, ktore Mirana pozna.
"""

# typ -> polia spravy (okrem "type"); None = volne polia (info)
EVENTS: dict[str, tuple[str, ...] | None] = {
    "state": ("state",),                        # idle | listening | processing | speaking | muted
    "level": ("v", "bands"),                    # hlasitost 0..1 a 12 frekvencnych pasiem (alebo None), ~20x/s
    "filler": ("text",),
    "answer_start": (),
    "answer_append": ("text", "ms_per_char", "marks", "viewers"),   # marks [[od, do, name|nick|swear]]
    "question": ("text",),                      # systemova hlaska (vypadok hlasu...)
    "search": ("title", "lines"),               # hladanie v databaze (wiki)
    "scan": ("target",),                        # snimka obrazovky ide modelu; ciel pod zameriavacom alebo None
    "game_fx": ("kind", "text", "detail"),      # level_up | quest_completed | death | wanted | district | radio
    "telemetry": ("location", "quest", "combat", "wanted", "critical", "deaths", "money", "time", "weather"),
    "stage": ("name", "status", "sec"),         # faza otazky: prepis | model; active | done | fail
    "hud": ("version",),                        # ktory HUD ma server nastaveny (v1 | v2) — stranka sa prepne sama
    "erik": ("text",),                          # prepis Erikovej otazky
    "budget": ("spent", "cap"),
    "game": ("live", "line"),                   # riadok [HRA] pre okno
    "info": None,                               # model, effort
    "notice": ("text",),
    "chat_status": ("text",),
}

HUD = {"state", "level", "filler", "answer_start", "answer_append", "question", "search", "scan",
       "game_fx", "telemetry", "stage", "hud"}
GUI = {"state", "erik", "answer_start", "answer_append", "question", "budget", "game", "info", "notice",
       "chat_status"}

# prikazy z ovladacieho okna: {"type": "command", "cmd": ..., "text": ...}
COMMANDS = {"mute", "quit", "ask", "memory_edit", "hud_test", "volume"}

# spravy, ktore nove pripojenie dostane hned (aktualny stav); ostatne su jednorazove
REMEMBERED = {"state", "telemetry", "budget", "game", "info", "chat_status", "hud"}


def event(kind: str, /, **fields) -> dict:
    """Sprava daneho typu. Neznamy typ alebo ine polia su chyba v kode (ValueError)."""
    if kind not in EVENTS:
        raise ValueError(f"neznamy typ spravy: {kind}")
    expected = EVENTS[kind]
    if expected is not None and set(fields) != set(expected):
        raise ValueError(f"{kind}: polia {sorted(fields)}, cakane {sorted(expected)}")
    return {"type": kind, **fields}
