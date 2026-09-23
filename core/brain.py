"""Brain: STT (core.stt, api|local) -> LLM (Claude, streaming). System prompt = persona (cacheable) + stav hry.

Odpoved sa streamuje a po celych vetach posiela cez on_sentence, aby hlas mohol zacat hovorit prvu
vetu, kym model pise dalsie. Retry a timeout riesi SDK (max_retries / timeout na klientovi).
Pri zlyhani ask_stream vrati Answer s ok=False; o fallbacku rozhoduje main.py.
"""

import logging
import os
import re
import time
from dataclasses import dataclass, field

from anthropic import Anthropic

from core.budget import Budget
from core.config import load_persona
from core.stt import create_stt

logger = logging.getLogger(__name__)

# Koniec vety: .!?… a medzera, za ktorou ide velke pismeno alebo uvodzovka. Skratky ako "Mr." a
# jednopismenove "V." sa nedelia, cisla typu "2077." tiez nie.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ„\"])")
_NO_SPLIT_BEFORE = re.compile(r"(?:\b(?:Mr|Mrs|Dr|Mk|St|napr|tzv|resp|č)\.|\b[A-Z]\.|\d\.)$")
_MIN_FIRST_SENTENCE = 12  # velmi kratky zaciatok ("Nie.") pockame, kym pride dalsia veta


@dataclass
class Answer:
    ok: bool
    text: str = ""
    sentences: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    model: str | None = None
    cost: float = 0.0
    first_sentence_sec: float | None = None
    total_sec: float = 0.0
    error: str | None = None


class SentenceSplitter:
    """Sklada stream textu na cele vety."""

    def __init__(self):
        self._buffer = ""
        self._emitted = 0

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        out = []
        while True:
            match = None
            for m in _SENTENCE_END.finditer(self._buffer):
                if not _NO_SPLIT_BEFORE.search(self._buffer[: m.start()]):
                    match = m
                    break
            if match is None:
                return out
            sentence = self._buffer[: match.start()].strip()
            if self._emitted == 0 and len(sentence) < _MIN_FIRST_SENTENCE and not out:
                # spoj kratky zaciatok s nasledujucou vetou — zbytocne krátky prvy kus TTS znie useknuto
                nxt = _SENTENCE_END.search(self._buffer, match.end())
                if nxt is None:
                    return out
                sentence = self._buffer[: nxt.start()].strip()
                self._buffer = self._buffer[nxt.end():]
            else:
                self._buffer = self._buffer[match.end():]
            if sentence:
                out.append(sentence)
                self._emitted += 1

    def flush(self) -> str:
        rest, self._buffer = self._buffer.strip(), ""
        return rest


class Brain:
    """STT (Whisper) -> LLM (Claude, streaming) -> vety."""

    def __init__(self, config: dict, budget: Budget):
        self.persona = load_persona()
        self.llm_cfg = config["llm"]
        self.budget = budget
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

    def _route(self, user_text: str) -> tuple[str, str]:
        if user_text.startswith("[CHAT_") and self.llm_cfg.get("chat_model"):
            return self.llm_cfg["chat_model"], self.llm_cfg.get("chat_effort", self.llm_cfg["effort"])
        return self.llm_cfg["model"], self.llm_cfg["effort"]

    def ask_stream(self, user_text: str, game_state_line: str | None, memory_messages: list[dict],
                   on_sentence=None, should_stop=None) -> Answer:
        """Streamuje odpoved; kazdu hotovu vetu posle cez on_sentence(veta).

        should_stop() -> True preruší stream (barge-in) — dalsie tokeny sa uz neplatia.
        """
        model, effort = self._route(user_text)
        started = time.perf_counter()
        answer = Answer(ok=False, model=model)
        kwargs = dict(
            model=model,
            max_tokens=self.llm_cfg["max_tokens"],
            output_config={"effort": effort},
            system=self._build_system(game_state_line),
            messages=[*memory_messages, {"role": "user", "content": user_text}],
        )
        fallbacks = self.llm_cfg.get("fallbacks")
        if fallbacks and model.startswith("claude-opus"):
            # Ked bezpecnostny klasifikator odmietne (napr. falosny poplach pri "zabi ho katanou"),
            # server otazku potichu zopakuje na odporucanom modeli namiesto ticha.
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks=fallbacks)

        splitter = SentenceSplitter()

        def emit(sentence: str) -> None:
            if answer.first_sentence_sec is None:
                answer.first_sentence_sec = time.perf_counter() - started
            answer.sentences.append(sentence)
            if on_sentence is not None:
                on_sentence(sentence)

        try:
            with self.anthropic_client.beta.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    if should_stop is not None and should_stop():
                        answer.error = "prerusene"
                        break
                    for sentence in splitter.feed(text):
                        emit(sentence)
                if answer.error is None:
                    message = stream.get_final_message()
        except Exception as e:
            logger.warning("Claude ask zlyhalo: %s", e)
            answer.error = str(e)
            answer.total_sec = time.perf_counter() - started
            return answer

        answer.total_sec = time.perf_counter() - started
        if answer.error == "prerusene":
            return answer

        answer.stop_reason = message.stop_reason
        answer.model = message.model
        if message.stop_reason != "refusal":
            rest = splitter.flush()
            if message.stop_reason == "max_tokens":
                # Useknuta posledna veta by znela divne — ak nekonci interpunkciou, zahodime ju
                logger.warning("odpoved narazila na max_tokens (%s), zvysok: %r", self.llm_cfg["max_tokens"], rest[:60])
                if rest and rest[-1] not in ".!?…":
                    rest = ""
            if rest:
                emit(rest)
        answer.cost = self.budget.add(model, message.usage)
        usage = message.usage
        logger.info(
            "tokens (%s): input=%s cache_read=%s cache_create=%s output=%s | $%.4f | prva veta %.1f s, spolu %.1f s",
            message.model, usage.input_tokens, usage.cache_read_input_tokens, usage.cache_creation_input_tokens,
            usage.output_tokens, answer.cost, answer.first_sentence_sec or -1, answer.total_sec,
        )
        if not self._cache_checked and memory_messages:
            self._cache_checked = True
            if not usage.cache_read_input_tokens:
                logger.warning("persona sa necachuje — je kratsia nez cache minimum? Skontroluj SPEC §8.")

        if message.stop_reason == "refusal":
            # Aj zalozny model odmietol. Uz vyslovene vety ostanu, zvysok zahodime.
            details = getattr(message, "stop_details", None)
            logger.warning("model odmietol odpovedat (%s)", getattr(details, "category", None))
            answer.text = " ".join(answer.sentences)
            answer.ok = bool(answer.sentences)
            return answer

        answer.text = " ".join(answer.sentences)
        answer.ok = bool(answer.text)
        if not answer.ok:
            logger.warning("prazdna odpoved (stop_reason=%s)", message.stop_reason)
        return answer
