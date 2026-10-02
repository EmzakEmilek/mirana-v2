"""Overlay: WebSocket server pre HUD (overlay/index.html) v OBS.

Jeden port (overlay.port): obycajny HTTP GET vrati index.html, WebSocket upgrade dostava JSON eventy.
Server bezi vo vlastnom vlakne s vlastnym asyncio loopom; main.py vola send() z ktorehokolvek vlakna.
Novy klient dostane pri pripojeni aktualny stav (state, telemetria, posledna odpoved), aby HUD po
reconnecte nebol prazdny. Ked overlay zlyha, Mirana bezi dalej — server ma vlastny try/except.
"""

import asyncio
import json
import logging
import threading
from http import HTTPStatus

from websockets.asyncio.server import serve

from core import protocol
from core.config import BASE_DIR

logger = logging.getLogger(__name__)

INDEX_PATH = BASE_DIR / "overlay" / "index.html"


class Overlay:
    """Drzi mnozinu pripojenych HUD klientov a posiela im eventy ako JSON."""

    def __init__(self, config: dict):
        cfg = config["overlay"]
        self.enabled = cfg["enabled"]
        self.host = cfg["host"]
        self.port = cfg["port"]
        self.ms_per_char = cfg["typewriter_ms_per_char"]
        self._clients: set = set()
        self._last: dict[str, dict] = {}  # typ -> posledny event, pre novych klientov
        self._loop: asyncio.AbstractEventLoop | None = None
        self.on_command = None  # on_command(cmd, text) — prikazy z ovladacieho okna (gui.py), len z localhostu

    # --- verejne API (thread-safe) --------------------------------------------------------

    def start(self) -> None:
        if not self.enabled:
            return
        threading.Thread(target=self._run, name="overlay", daemon=True).start()

    def state(self, name: str) -> None:
        self._send("state", state=name)

    def filler(self, text: str) -> None:
        self._send("filler", text=text)

    def answer_start(self) -> None:
        """Nova odpoved — HUD vymaze staru. Odpovede sa nepamataju: po reconnecte (refresh v OBS)
        by sa inak stara odpoved vypisala znova."""
        self._send("answer_start")

    def answer_append(self, text: str, duration_sec: float | None = None, ms_per_char: int | None = None) -> None:
        """Dalsia veta odpovede. Tempo pisania z dlzky jej audia, aby text dobehol s hlasom."""
        if ms_per_char is None:
            ms_per_char = self.ms_per_char
            if duration_sec and text:
                ms_per_char = max(15, int(duration_sec * 1000 / len(text)))
        self._send("answer_append", text=text, ms_per_char=ms_per_char)

    def question(self, text: str) -> None:
        """Len pre [SYSTEM] hlasky — Erikove otazky sa na HUD nezobrazuju (rozhodnutie 2026-09-21)."""
        self._send("question", text=text)

    def search(self, title: str | None, lines: list[str] | None = None) -> None:
        """Hladanie v databaze (wiki): None = zacina sa hladat (HUD strieda `lines` kazde 2 s),
        inak nazov najdeneho clanku."""
        self._send("search", title=title, lines=lines or [])

    def scan(self) -> None:
        """Mirana sa pozera na obrazovku (posiela sa snimka hry)."""
        self._send("scan")

    def game_fx(self, kind: str, text: str) -> None:
        """Efekt na HUD pri udalosti z hry (level, quest, smrt, policia)."""
        self._send("game_fx", kind=kind, text=text)

    def telemetry(self, *, location: str = "", quest: str = "", combat: bool = False, wanted: int = 0,
                  critical: bool = False, deaths: int = 0) -> None:
        """HP sa na HUD neukazuje (ma ho hra): lokacia + quest, boj a kriticke HP zafarbia jadro,
        hviezdy policie a pocitadlo smrti su v hlavicke panela."""
        self._send("telemetry", location=location, quest=quest, combat=combat, wanted=wanted,
                   critical=critical, deaths=deaths)

    def level(self, value: float) -> None:
        """Hlasitost 0..1 (hlas Mirany alebo Erikov mikrofon), ~20x/s. Nepamata sa."""
        self._send("level", v=round(value, 3))

    def erik(self, text: str) -> None:
        """Prepis Erikovej otazky — pre ovladacie okno. HUD ho ignoruje (otazky sa na streame neukazuju)."""
        self._send("erik", text=text)

    def budget(self, spent: float, cap: float) -> None:
        self._send("budget", spent=round(spent, 4), cap=cap)

    def game(self, live: bool, line: str | None) -> None:
        """Stav telemetrie pre ovladacie okno (HUD ma vlastny setTelemetry)."""
        self._send("game", live=live, line=line)

    def info(self, **data) -> None:
        """Staticke info o behu (model, effort) pre ovladacie okno."""
        self._send("info", **data)

    def notice(self, text: str) -> None:
        """Systemova hlaska len pre ovladacie okno (na HUD v streame nepatri)."""
        self._send("notice", text=text)

    def chat_status(self, text: str) -> None:
        self._send("chat_status", text=text)

    # --- vnutro ---------------------------------------------------------------------------

    def _send(self, kind: str, /, **fields) -> None:
        event = protocol.event(kind, **fields)
        if kind in protocol.REMEMBERED:
            self._last[kind] = event
        if self._loop is None or not self._clients:
            return
        try:
            self._loop.call_soon_threadsafe(self._loop.create_task, self._broadcast(json.dumps(event)))
        except RuntimeError:
            pass  # loop uz nebezi

    async def _broadcast(self, message: str) -> None:
        for client in list(self._clients):
            try:
                await client.send(message)
            except Exception:
                self._clients.discard(client)

    async def _handler(self, websocket) -> None:
        self._clients.add(websocket)
        logger.info("HUD pripojeny (%d klientov)", len(self._clients))
        try:
            for event in self._last.values():
                await websocket.send(json.dumps(event))
            async for message in websocket:
                self._on_message(websocket, message)
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info("HUD odpojeny (%d klientov)", len(self._clients))

    def _on_message(self, websocket, message) -> None:
        """HUD nic neposiela; ovladacie okno posiela {"type": "command", "cmd": "mute"|"quit"|"ask", "text": ...}.

        Server pocuva na 0.0.0.0 (kvoli OBS na notebooku) — prikazy sa preto berú len z tohto PC.
        """
        try:
            data = json.loads(message)
        except ValueError:
            return
        if data.get("type") != "command" or self.on_command is None:
            return
        if data.get("cmd") not in protocol.COMMANDS:
            logger.warning("neznamy prikaz %r", data.get("cmd"))
            return
        host = (websocket.remote_address or ("",))[0]
        if host not in ("127.0.0.1", "::1"):
            logger.warning("prikaz %r z %s odmietnuty (len localhost)", data.get("cmd"), host)
            return
        # Prehliadac posiela vzdy hlavicku Origin, ovladacie okno (Python klient) nie. Bez tejto kontroly
        # by lubovolna webova stranka otvorena na tomto PC mohla cez ws://localhost Mirane nieco poslat.
        request = getattr(websocket, "request", None)
        if request is not None and request.headers.get("Origin"):
            logger.warning("prikaz %r z prehliadaca (%s) odmietnuty", data.get("cmd"), request.headers.get("Origin"))
            return
        text = data.get("text")
        self.on_command(str(data.get("cmd")), str(text) if text is not None else None)

    @staticmethod
    def _process_request(connection, request):
        """Obycajny GET (Browser Source v OBS) dostane index.html; WebSocket upgrade ide dalej."""
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None
        if request.path in ("/", "/index.html"):
            response = connection.respond(HTTPStatus.OK, INDEX_PATH.read_text(encoding="utf-8"))
            response.headers["Content-Type"] = "text/html; charset=utf-8"
            return response
        return connection.respond(HTTPStatus.NOT_FOUND, "Not Found")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            logger.exception("overlay server zlyhal — Mirana bezi dalej bez HUD")

    async def _serve(self) -> None:
        async with serve(self._handler, self.host, self.port, process_request=self._process_request):
            logger.info("HUD: http://localhost:%d (OBS Browser Source na IP herneho PC)", self.port)
            await asyncio.Future()
