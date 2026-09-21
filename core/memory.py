"""Pamat: deque poslednych memory.max_exchanges vymen, vklada sa do promptu."""

from collections import deque


class Memory:
    """Uchovava poslednych max_exchanges vymen (user, assistant) v RAM."""

    def __init__(self, config: dict):
        self._exchanges: deque[tuple[str, str]] = deque(maxlen=config["memory"]["max_exchanges"])

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
