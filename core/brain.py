"""Brain: STT (Whisper API) -> LLM (Claude). System prompt = persona (cacheable) + stav hry + pamat."""

import os
from pathlib import Path

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
PERSONA_PATH = BASE_DIR / "persona.md"

load_dotenv(BASE_DIR / ".env")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_persona() -> str:
    return PERSONA_PATH.read_text(encoding="utf-8")


class Brain:
    """STT (Whisper) -> LLM (Claude Sonnet 5) -> text. Kazde API volanie: timeout, 1 retry, fallback."""

    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self.persona = load_persona()

        self.stt_cfg = self.config["stt"]
        self.llm_cfg = self.config["llm"]
        self.limits_cfg = self.config["limits"]
        self.fallback_phrases = self.config["fallback_phrases"]

        self.timeout = self.limits_cfg["api_timeout_sec"]
        self.retries = self.limits_cfg["api_retries"]

        self.openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=self.timeout)
        self.anthropic_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"), timeout=self.timeout)

    def transcribe(self, wav_bytes: bytes) -> str | None:
        """Whisper API, jazyk podla config. None pri zlyhani po vsetkych pokusoch."""
        for _ in range(self.retries + 1):
            try:
                result = self.openai_client.audio.transcriptions.create(
                    model=self.stt_cfg["api_model"],
                    file=("audio.wav", wav_bytes, "audio/wav"),
                    language=self.stt_cfg["language"],
                )
                return result.text
            except Exception:
                continue
        return None

    def _build_system(self, game_state_line: str | None) -> list[dict]:
        persona_block = {"type": "text", "text": self.persona}
        if self.llm_cfg.get("cache_persona"):
            persona_block["cache_control"] = {"type": "ephemeral"}

        system = [persona_block]
        if game_state_line:
            system.append({"type": "text", "text": game_state_line})
        return system

    def ask(
        self,
        user_text: str,
        game_state_line: str | None,
        memory_messages: list[dict],
    ) -> str | None:
        """Claude Sonnet, system = persona (cacheable) + stav hry. None pri zlyhani po vsetkych pokusoch."""
        system = self._build_system(game_state_line)
        messages = [*memory_messages, {"role": "user", "content": user_text}]

        for _ in range(self.retries + 1):
            try:
                response = self.anthropic_client.messages.create(
                    model=self.llm_cfg["model"],
                    max_tokens=self.llm_cfg["max_tokens"],
                    temperature=self.llm_cfg["temperature"],
                    system=system,
                    messages=messages,
                )
                return "".join(block.text for block in response.content if block.type == "text")
            except Exception:
                continue
        return None

    def process(
        self,
        wav_bytes: bytes,
        game_state_line: str | None,
        memory_messages: list[dict],
    ) -> tuple[str | None, str]:
        """STT -> LLM -> (transcript, text). Pri zlyhani ktorejkolvek casti vrati fallback hlasku z config.yaml.

        transcript je None ak zlyhalo STT (nema zmysel ho ukladat do pamate).
        """
        transcript = self.transcribe(wav_bytes)
        if transcript is None:
            return None, self.fallback_phrases["stt_failed"]

        answer = self.ask(transcript, game_state_line, memory_messages)
        if answer is None:
            return transcript, self.fallback_phrases["llm_failed"]

        return transcript, answer
