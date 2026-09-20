"""Pamat: deque poslednych memory.max_exchanges vymen, vklada sa do promptu."""

from collections import deque
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class Memory:
    """Uchovava poslednych max_exchanges vymen (user, assistant) v RAM."""

    def __init__(self, config: dict | None = None):
        config = config or load_config()
        self.max_exchanges = config["memory"]["max_exchanges"]
        self._exchanges: deque[tuple[str, str]] = deque(maxlen=self.max_exchanges)

    def add_exchange(self, user_text: str, assistant_text: str) -> None:
        self._exchanges.append((user_text, assistant_text))

    def as_messages(self) -> list[dict[str, str]]:
        """Vrati vymeny ako zoznam messages pre LLM prompt (user/assistant striedavo)."""
        messages = []
        for user_text, assistant_text in self._exchanges:
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": assistant_text})
        return messages

    def clear(self) -> None:
        self._exchanges.clear()

    def __len__(self) -> int:
        return len(self._exchanges)
