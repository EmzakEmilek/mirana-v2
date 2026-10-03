"""Snimka okna hry pre otazky typu "co je toto?" — Mirana vidi, co Erik.

Fotí sa VYLUCNE okno hry (podla nazvu okna, predvolene "Cyberpunk 2077"), nikdy cely monitor:
na obrazovke moze byt Discord, prehliadac a pod. Ked okno hry nie je otvorene alebo je minimalizovane,
snimka sa neposle. Obrazok sa zmensi (vision.max_width, predvolene 1280 px = ~1200 tokenov, ~0,24 c
na Sonnete 5.5), posle sa len s jednou otazkou a do pamate nejde.

Hra musi bezat v okne alebo v okne bez okrajov — pri exkluzivnej celej obrazovke byva snimka cierna
(vtedy sa neposle a v logu je varovanie).
"""

import base64
import ctypes
import io
import logging
import sys
from ctypes import wintypes

from mirana import intents
from mirana.features import Feature

logger = logging.getLogger(__name__)

_dpi_done = False


def _dpi_aware() -> None:
    """Bez toho by Windows pri zvacseni (125 %, 150 %) vracal zmensene suradnice okna."""
    global _dpi_done
    if not _dpi_done and sys.platform == "win32":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass
        _dpi_done = True


def find_window(title: str, exact: bool = False) -> tuple[int, int, int, int] | None:
    """Obdlznik klientskej casti (bez ramu) prveho viditelneho okna s danym nazvom, v suradniciach obrazovky."""
    if sys.platform != "win32":
        return None
    _dpi_aware()
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        name = buf.value
        if (name == title) if exact else (title in name):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback, 0)
    if not found:
        return None
    rect = wintypes.RECT()
    user32.GetClientRect(found[0], ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(found[0], ctypes.byref(origin))
    if rect.right - rect.left < 200 or rect.bottom - rect.top < 150:
        return None
    return origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom


def capture(title: str, max_width: int = 1280, exact: bool = False) -> str | None:
    """JPEG snimka okna ako base64, alebo None (okno nie je, je minimalizovane, snimka je cierna)."""
    box = find_window(title, exact)
    if box is None:
        logger.info("snimka: okno %r nie je otvorene", title)
        return None
    from PIL import ImageGrab, ImageStat

    image = ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")
    if max(ImageStat.Stat(image).mean) < 4:
        logger.warning("snimka hry je cierna — hra je asi v exkluzivnej celej obrazovke (prepni na okno bez okrajov)")
        return None
    if image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)))
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=80)
    logger.info("snimka hry %dx%d, %d kB", image.width, image.height, len(buf.getvalue()) // 1024)
    return base64.b64encode(buf.getvalue()).decode()


class Vision:
    def __init__(self, config: dict):
        cfg = config.get("vision") or {}
        self.enabled = cfg.get("enabled", False)
        self.title = cfg.get("window_title", "Cyberpunk 2077")
        self.max_width = int(cfg.get("max_width", 1280))

    def wants(self, question: str) -> bool:
        return self.enabled and intents.wants_vision(question)

    def capture(self) -> str | None:
        try:
            return capture(self.title, self.max_width)
        except Exception as e:
            logger.warning("snimka hry zlyhala: %s", e)
            return None


class VisionFeature(Feature):
    """"co je toto?" — snimka okna hry (len hra, nikdy cely monitor), ~50 ms + ~0.2 s pre model."""

    def __init__(self, app):
        super().__init__(app)
        self.vision = Vision(app.config)

    def context(self, turn) -> None:
        if not turn.from_erik or not self.vision.wants(turn.question):
            return
        turn.image = self.vision.capture()
        if turn.image:
            turn.add("OBRAZOVKA", "[OBRAZOVKA] priložená snímka hry")
            if not turn.cancelled:
                from mirana.inputs.game_state import target_info
                self.app.overlay.scan(target_info(self.app.game.current))
