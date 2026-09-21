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

    # --- verejne API (thread-safe) --------------------------------------------------------

    def start(self) -> None:
        if not self.enabled:
            return
        threading.Thread(target=self._run, name="overlay", daemon=True).start()

    def state(self, name: str) -> None:
        self._send({"type": "state", "state": name})

    def filler(self, text: str) -> None:
        self._send({"type": "filler", "text": text}, remember=False)

    def answer(self, text: str, duration_sec: float | None = None) -> None:
        """Pisaci stroj; ak pozname dlzku audia, tempo sa nastavi tak, aby text dobehol s hlasom."""
        ms_per_char = self.ms_per_char
        if duration_sec and text:
            ms_per_char = max(15, int(duration_sec * 1000 / len(text)))
        self._send({"type": "answer", "text": text, "ms_per_char": ms_per_char})

    def question(self, text: str) -> None:
        """Len pre [SYSTEM] hlasky — Erikove otazky sa na HUD nezobrazuju (rozhodnutie 2026-09-21)."""
        self._send({"type": "question", "text": text})

    def telemetry(self, location: str, quest: str, combat: bool = False) -> None:
        """HP sa na HUD neukazuje (ma ho hra), len lokacia + quest; combat zafarbi jadro."""
        self._send({"type": "telemetry", "location": location, "quest": quest, "combat": combat})

    def level(self, value: float) -> None:
        """Hlasitost 0..1 (hlas Mirany alebo Erikov mikrofon), ~20x/s. Nepamata sa."""
        self._send({"type": "level", "v": round(value, 3)}, remember=False)

    def queue(self, n: int) -> None:
        self._send({"type": "queue", "n": n})

    # --- vnutro ---------------------------------------------------------------------------

    def _send(self, event: dict, remember: bool = True) -> None:
        if remember:
            self._last[event["type"]] = event
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
            async for _ in websocket:
                pass  # HUD nic neposiela, len drzime spojenie
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info("HUD odpojeny (%d klientov)", len(self._clients))

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
