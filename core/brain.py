"""Brain: STT (core.stt, api|local) -> LLM (Claude). System prompt = persona (cacheable) + stav hry.

Retry a timeout riesi SDK (max_retries / timeout na klientovi). Kazda metoda vrati None pri zlyhani,
o fallbacku rozhoduje main.py.
"""

import logging
import os

from anthropic import Anthropic

from core.config import load_persona
from core.stt import create_stt

logger = logging.getLogger(__name__)


class Brain:
    """STT (Whisper) -> LLM (Claude Sonnet 5) -> text."""

    def __init__(self, config: dict):
        self.persona = load_persona()
        self.llm_cfg = config["llm"]
        limits = config["limits"]

        self.stt = create_stt(config)
        # API kluc si SDK cita z ANTHROPIC_API_KEY (nacitane v core.config). Kluc bez workspace
        # vyzaduje hlavicku anthropic-workspace-id — ANTHROPIC_WORKSPACE_ID v .env (alebo kluc vytvoreny vo workspace).
        headers = {}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        self.anthropic_client = Anthropic(
            timeout=limits["api_timeout_sec"], max_retries=limits["api_retries"], default_headers=headers
        )
        self._cache_checked = False

    def transcribe(self, wav_bytes: bytes) -> str | None:
        """Whisper (api|local podla config), jazyk podla config. None pri zlyhani."""
        return self.stt.transcribe(wav_bytes)

    def _build_system(self, game_state_line: str | None) -> list[dict]:
        # Persona je prvy (stabilny) blok s cache breakpointom, stav hry ide az za nim.
        persona_block = {"type": "text", "text": self.persona}
        if self.llm_cfg.get("cache_persona"):
            persona_block["cache_control"] = {"type": "ephemeral"}

        system = [persona_block]
        if game_state_line:
            system.append({"type": "text", "text": game_state_line})
        return system

    def ask(self, user_text: str, game_state_line: str | None, memory_messages: list[dict]) -> str | None:
        """Claude, system = persona (cacheable) + stav hry. None pri zlyhani."""
        model, effort = self.llm_cfg["model"], self.llm_cfg["effort"]
        try:
            response = self.anthropic_client.messages.create(
                model=model,
                max_tokens=self.llm_cfg["max_tokens"],
                output_config={"effort": effort},
                system=self._build_system(game_state_line),
                messages=[*memory_messages, {"role": "user", "content": user_text}],
            )
        except Exception as e:
            logger.warning("Claude ask zlyhalo: %s", e)
            return None

        usage = response.usage
        logger.info(
            "tokens (%s): input=%s cache_read=%s cache_create=%s output=%s",
            model, usage.input_tokens, usage.cache_read_input_tokens, usage.cache_creation_input_tokens, usage.output_tokens,
        )
        # Jednorazova kontrola, ci sa persona naozaj cachuje (min. 1024 tokenov pre Sonnet 5).
        if not self._cache_checked and memory_messages:
            self._cache_checked = True
            if not usage.cache_read_input_tokens:
                logger.warning("persona sa necachuje — je kratsia nez cache minimum? Skontroluj SPEC §9.")

        return "".join(block.text for block in response.content if block.type == "text")
