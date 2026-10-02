"""Twitch chat len na citanie: anonymne IRC cez WebSocket, bez tokenu a bez bota.

Mirana chat len "vidi": posledne spravy idu ako riadok [CHAT] k Erikovej otazke a persona hovori,
ze ich sama nekomentuje — pouzije ich, iba ked sa Erik na chat alebo divaka opyta. Do chatu nic nepise.
Spravy divakov su cudzi text: v prompte su oznacene ako udaje, odkazy sa nahradia, dlzka je orezana.
"""

import asyncio
import logging
import random
import re
import threading
import time
from collections import deque
from dataclasses import dataclass

import websockets

logger = logging.getLogger(__name__)

URL = "wss://irc-ws.chat.twitch.tv:443"
URL_RE = re.compile(r"(https?://|www\.)\S+", re.I)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
BADGE_LABELS = (("broadcaster", "streamer"), ("moderator", "mod"), ("vip", "vip"), ("subscriber", "sub"))


@dataclass
class ChatMessage:
    at: float
    login: str
    nick: str
    text: str
    badges: tuple[str, ...]


def parse_privmsg(line: str) -> ChatMessage | None:
    """IRC riadok s tagmi -> sprava, alebo None, ak to nie je sprava do chatu.

    @badges=subscriber/12;display-name=Kubo :kubo!kubo@kubo.tmi.twitch.tv PRIVMSG #kanal :ahoj
    """
    tags = {}
    if line.startswith("@"):
        raw, _, line = line[1:].partition(" ")
        for item in raw.split(";"):
            key, _, value = item.partition("=")
            tags[key] = value
    if not line.startswith(":"):
        return None
    prefix, _, rest = line[1:].partition(" ")
    command, _, rest = rest.partition(" ")
    if command != "PRIVMSG":
        return None
    _channel, _, text = rest.partition(" :")
    login = prefix.split("!", 1)[0].lower()
    nick = (tags.get("display-name") or login).replace("\\s", " ").strip() or login
    badges = tuple(b.split("/", 1)[0] for b in tags.get("badges", "").split(",") if b)
    if text.startswith("\x01ACTION "):  # /me sprava
        text = text[len("\x01ACTION "):].rstrip("\x01")
    return ChatMessage(time.time(), login, nick, text, badges)


def clean_text(text: str, max_chars: int) -> str:
    text = CONTROL_RE.sub(" ", text)
    text = URL_RE.sub("[odkaz]", text)
    text = " ".join(text.replace("|", "/").split())
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"


def channel_name(raw: str | None) -> str:
    """"https://www.twitch.tv/Emzo", "#emzo", "Emzo" -> "emzo"."""
    raw = (raw or "").strip().rstrip("/")
    return raw.rsplit("/", 1)[-1].lstrip("#").lower()


class TwitchChat:
    """Cita chat vo vlastnom vlakne. on_message(ChatMessage) a on_status(text) vola z toho vlakna."""

    def __init__(self, config: dict, on_message=None, on_status=None):
        cfg = config.get("twitch_chat", {})
        self.enabled = cfg.get("enabled", False)
        self.channel = channel_name(cfg.get("channel"))
        self.max_messages = cfg.get("max_messages", 15)
        self.max_age = cfg.get("max_age_sec", 300)
        self.max_chars = cfg.get("max_chars", 150)
        self.ignore = {u.lower() for u in cfg.get("ignore_users") or []}
        self.on_message = on_message
        self.on_status = on_status
        self._messages: deque[ChatMessage] = deque(maxlen=200)
        self._lock = threading.Lock()
        self.connected = False

    def start(self) -> None:
        if not self.enabled:
            return
        if not self.channel:
            logger.warning("twitch chat je zapnuty, ale chyba kanal — Nastavenia -> Chat")
            self._status("chat: chýba názov kanála")
            return
        threading.Thread(target=lambda: asyncio.run(self._run()), name="twitch-chat", daemon=True).start()

    # --- pre prompt ---------------------------------------------------------------------------

    def line(self) -> str | None:
        """Posledne spravy (najnovsia na konci) ako jeden riadok, alebo None, ked je chat ticho."""
        now = time.time()
        with self._lock:
            recent = [m for m in self._messages if now - m.at <= self.max_age][-self.max_messages:]
        if not recent:
            return None
        parts = []
        for m in recent:
            label = next((sk for badge, sk in BADGE_LABELS if badge in m.badges), None)
            parts.append(f"{m.nick}{f' ({label})' if label else ''}: {m.text}")
        return "[CHAT] " + " | ".join(parts)

    # --- vnutro -------------------------------------------------------------------------------

    def _status(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _add(self, msg: ChatMessage) -> None:
        if msg.login in self.ignore or msg.text.lstrip().startswith("!"):
            return  # boti a prikazy (!song, !discord) nie su rozhovor
        msg.text = clean_text(msg.text, self.max_chars)
        if not msg.text:
            return
        with self._lock:
            self._messages.append(msg)
        logger.info("chat %s: %s", msg.nick, msg.text)
        if self.on_message:
            self.on_message(msg)

    async def _run(self) -> None:
        delay = 2
        while True:
            try:
                async with websockets.connect(URL, ping_interval=None, open_timeout=15, close_timeout=5) as ws:
                    await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                    await ws.send("PASS SCHMOOPIIE")
                    await ws.send(f"NICK justinfan{random.randint(10000, 99999)}")  # anonymne citanie
                    await ws.send(f"JOIN #{self.channel}")
                    async for frame in ws:
                        for line in str(frame).split("\r\n"):
                            if not line:
                                continue
                            if line.startswith("PING"):
                                await ws.send("PONG" + line[4:])
                            elif " RECONNECT" in line:
                                raise ConnectionError("Twitch ziada reconnect")
                            elif f" 366 " in line and not self.connected:  # koniec zoznamu mien = sme v kanali
                                self.connected = True
                                delay = 2
                                logger.info("twitch chat pripojeny: #%s", self.channel)
                                self._status(f"chat: #{self.channel} pripojený")
                            else:
                                msg = parse_privmsg(line)
                                if msg:
                                    self._add(msg)
            except Exception as e:
                logger.warning("twitch chat odpojeny (%s), skusim znova o %d s", e, delay)
            if self.connected:
                self._status(f"chat: #{self.channel} odpojený, pripájam znova…")
            self.connected = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
