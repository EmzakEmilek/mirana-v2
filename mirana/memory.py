"""Pamat: posledne vymeny (Erik, Mirana), vkladaju sa do promptu.

Pamat sa nezahadzuje po jednej vymene, ale po blokoch: pri dosiahnuti max_exchanges sa oreze
na trim_to. Zaciatok historie tak ostava rovnaky viac otazok po sebe a prompt cache ho vie
znovu pouzit (cache je zhoda prefixu — posuvne okno po jednej by ju zrusilo pri kazdej otazke).
"""


class Memory:
    def __init__(self, config: dict):
        cfg = config["memory"]
        self.max_exchanges = cfg["max_exchanges"]
        self.trim_to = cfg.get("trim_to", self.max_exchanges)
        self._exchanges: list[tuple[str, str]] = []

    def add_exchange(self, user_text: str, assistant_text: str) -> None:
        self._exchanges.append((user_text, assistant_text))
        if len(self._exchanges) > self.max_exchanges:
            self._exchanges = self._exchanges[-self.trim_to:]

    def as_messages(self) -> list[dict[str, str]]:
        """Vymeny ako messages pre LLM prompt (user/assistant striedavo)."""
        messages = []
        for user_text, assistant_text in self._exchanges:
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": assistant_text})
        return messages

    def clear(self) -> None:
        self._exchanges.clear()

    def __len__(self) -> int:
        return len(self._exchanges)
