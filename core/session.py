"""Beh jednej session: logovanie do suboru, zaznam rozhovoru a zamok proti druhej instancii."""

import logging
import socket
import sys
from datetime import datetime

from core.config import BASE_DIR
from core.store import append_jsonl

LOGS_DIR = BASE_DIR / "logs"

# Lubovolny volny port na localhoste. Bind drzi OS, takze zamok zmizne aj pri pade procesu (lock subor by ostal visiet).
_LOCK_PORT = 47651
_lock_socket: socket.socket | None = None
EXIT_ALREADY_RUNNING = 3  # run.py pri tomto kode nerestartuje
HEARTBEAT_PATH = BASE_DIR / "data" / "heartbeat"


def ensure_single_instance() -> None:
    """Druha Mirana by pocuvala na ten isty PTT a odpovedala dvakrat. Ak uz jedna bezi, skonci."""
    global _lock_socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", _LOCK_PORT))
    except OSError:
        print("Mirana uz bezi (iny proces drzi zamok). Zavri ju a spusti znova.")
        sys.exit(EXIT_ALREADY_RUNNING)
    _lock_socket = sock


def setup_logging(config: dict) -> str:
    """Konzola + logs/mirana-<cas>.log pre kazdu session. Vrati ID session (cas startu)."""
    session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    LOGS_DIR.mkdir(exist_ok=True)
    level = getattr(logging, config.get("logging", {}).get("level", "INFO"))
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    handlers = [logging.FileHandler(LOGS_DIR / f"mirana-{session_id}.log", encoding="utf-8")]
    if sys.stderr is not None:  # pod pythonw.exe (spustenie z ikony) konzola nie je
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(fmt)
        root.addHandler(handler)
    # HTTP kniznice by zahltili log kazdym requestom
    for noisy in ("httpx", "httpx2", "httpcore", "websockets", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return session_id


class ConversationLog:
    """logs/rozhovor-<session>.jsonl — jeden riadok na otazku: prepis, odpoved, model, casy, cena, stav."""

    def __init__(self, session_id: str):
        self.path = LOGS_DIR / f"rozhovor-{session_id}.jsonl"

    def write(self, **record) -> None:
        append_jsonl(self.path, {"cas": datetime.now().isoformat(timespec="seconds"), **record})
