"""Brain: STT (mirana.llm.stt, api|local) -> LLM (Claude, streaming). System prompt = persona (cacheable) + stav hry.

Odpoved sa streamuje a po celych vetach posiela cez on_sentence, aby hlas mohol zacat hovorit prvu
vetu, kym model pise dalsie. Retry a timeout riesi SDK (max_retries / timeout na klientovi).
Pri zlyhani ask_stream vrati Answer s ok=False; o fallbacku rozhoduje jadro (mirana/app.py).
"""

import logging
import os
import re
import time
from dataclasses import dataclass, field

from anthropic import Anthropic

from mirana.budget import Budget
from mirana.config import load_persona
from mirana.llm.stt import create_stt
from mirana.features.wiki import TOOL as WIKI_TOOL, Wiki

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
    lookups: int = 0                     # kolkokrat model hladal vo wiki


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


SCREEN_TOOL = {
    "name": "obrazovka",
    "description": ("Pozrie sa na aktuálny obraz hry (snímka okna Cyberpunku). Použi, len keď na odpoveď naozaj "
                    "potrebuješ vidieť, čo Erik práve vidí, a v správe nemáš [OBRAZOVKA]."),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}


class Brain:
    """STT (Whisper) -> LLM (Claude, streaming) -> vety."""

    def __init__(self, config: dict, budget: Budget, wiki: Wiki | None = None):
        self.persona = load_persona()
        self.llm_cfg = config["llm"]
        self.budget = budget
        limits = config["limits"]

        self.stt = create_stt(config)
        self.wiki = wiki if wiki is not None else Wiki(config)  # index nacitava WikiFeature.start()
        self.max_lookups = config.get("wiki", {}).get("max_lookups", 2)
        # API kluc si SDK cita z ANTHROPIC_API_KEY (nacitane v mirana.config). Kluc bez workspace
        # vyzaduje hlavicku anthropic-workspace-id — ANTHROPIC_WORKSPACE_ID v .env (alebo kluc vytvoreny vo workspace).
        headers = {}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        self.anthropic_client = Anthropic(
            timeout=limits["api_timeout_sec"], max_retries=limits["api_retries"], default_headers=headers
        )
        self._cache_checked = False
        self.memory_block = None  # callable -> [PAMÄŤ] text (mirana.features.longterm), nastavuje LongTermFeature
        self.screen = None        # callable -> snimka hry (base64 JPEG) alebo None; nastavuje VisionFeature

    def transcribe(self, wav_bytes: bytes) -> str | None:
        """Whisper (api|local podla config), jazyk podla config. None pri zlyhani."""
        return self.stt.transcribe(wav_bytes)

    def _build_system(self, game_state_line: str | None) -> list[dict]:
        # Persona je prvy (stabilny) blok s cache breakpointom, stav hry ide az za nim.
        persona_block = {"type": "text", "text": self.persona}
        if self.llm_cfg.get("cache_persona"):
            persona_block["cache_control"] = {"type": "ephemeral"}

        system = [persona_block]
        memory = self.memory_block() if self.memory_block else None
        if memory:  # dlhodoba pamat: meni sa len pri starte a po zhrnuti, preto vlastny cache breakpoint
            system.append({"type": "text", "text": memory, "cache_control": {"type": "ephemeral"}})
        if game_state_line:
            system.append({"type": "text", "text": game_state_line})
        return system

    def _messages(self, memory_messages: list[dict], user_text: str, image_b64: str | None = None) -> list[dict]:
        """Pamat rozhovoru + nova otazka. Cache breakpoint je na poslednej sprave PAMATE, nie na novej
        otazke: do pamate ide len otazka bez [HRA]/[CHAT], takze nova otazka (aj s nimi) by sa pri dalsom
        volani s cache nezhodovala a cela historia by sa zakazdym zapisovala nanovo (test 3.10.: 4-6 tisic
        tokenov zapisu na kazdu otazku). Takto sa historia cita z cache a dopise sa len posledna vymena.
        image_b64 = snimka hry (JPEG) pred textom; do pamate nejde."""
        messages = [dict(m) for m in memory_messages]
        if messages and self.llm_cfg.get("cache_memory", True):
            last = messages[-1]
            text = last["content"] if isinstance(last["content"], str) else None
            if text is not None:
                last["content"] = [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
        content = [{"type": "text", "text": user_text}]
        if image_b64:
            content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
        return messages + [{"role": "user", "content": content}]

    def _screen_result(self):
        """Vysledok nastroja obrazovka: snimka hry, alebo veta, preco sa neda."""
        image = None
        try:
            image = self.screen() if self.screen is not None else None
        except Exception as e:
            logger.warning("snimka pre nastroj obrazovka zlyhala: %s", e)
        if not image:
            return "Snímka sa nedá urobiť — hra nebeží v okne alebo je minimalizovaná."
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}}]

    def _log_usage(self, message, cost: float, started: float, answer: "Answer") -> None:
        usage = message.usage
        logger.info(
            "tokens (%s): input=%s cache_read=%s cache_create=%s output=%s | $%.4f | prva veta %.1f s, %s %.1f s",
            message.model, usage.input_tokens, usage.cache_read_input_tokens, usage.cache_creation_input_tokens,
            usage.output_tokens, cost, answer.first_sentence_sec or -1,
            "wiki po" if message.stop_reason == "tool_use" else "spolu", time.perf_counter() - started,
        )

    def ask_stream(self, user_text: str, game_state_line: str | None, memory_messages: list[dict],
                   on_sentence=None, should_stop=None, on_lookup=None, image_b64: str | None = None,
                   on_look=None) -> Answer:
        """Streamuje odpoved; kazdu hotovu vetu posle cez on_sentence(veta).

        should_stop() -> True preruší stream (barge-in) — dalsie tokeny sa uz neplatia.
        Ked model siahne po wiki, on_lookup() sa zavola hned na zaciatku volania nastroja (hlaska
        "hladam v databaze"), vysledok ide spat modelu a odpoved pokracuje v dalsom kole.
        Nastrojom obrazovka sa model pozrie na hru sam (on_look() hned na zaciatku — HUD ukaze sken).
        """
        model, effort = self.llm_cfg["model"], self.llm_cfg["effort"]
        started = time.perf_counter()
        answer = Answer(ok=False, model=model)
        kwargs = dict(
            model=model,
            max_tokens=self.llm_cfg["max_tokens"],
            output_config={"effort": effort},
            system=self._build_system(game_state_line),
            messages=self._messages(memory_messages, user_text, image_b64),
        )
        fallbacks = self.llm_cfg.get("fallbacks")
        if fallbacks and (model.startswith("claude-opus") or model == "claude-sonnet-5-5"):
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

        tools = [WIKI_TOOL] if self.wiki.enabled else []
        if self.screen is not None and not image_b64:  # snimka uz je pri otazke -> netreba
            tools.append(SCREEN_TOOL)
        if tools:
            kwargs["tools"] = tools
        lookups, cost, message = 0, 0.0, None
        try:
            while True:
                with self.anthropic_client.beta.messages.stream(**kwargs) as stream:
                    for event in stream:
                        if should_stop is not None and should_stop():
                            answer.error = "prerusene"
                            break
                        if event.type == "content_block_start" and event.content_block.type == "tool_use":
                            if getattr(event.content_block, "name", "") == SCREEN_TOOL["name"]:
                                if on_look is not None:
                                    on_look()
                            elif on_lookup is not None:
                                on_lookup(None)
                        elif event.type == "text":
                            for sentence in splitter.feed(event.text):
                                emit(sentence)
                    if answer.error is not None:
                        # prerusene (barge-in): zaplati sa aj to, co model stihol vygenerovat
                        partial = getattr(stream, "current_message_snapshot", None)
                        if partial is not None and getattr(partial, "usage", None) is not None:
                            cost += self.budget.add(model, partial.usage)
                        break
                    message = stream.get_final_message()
                cost += self.budget.add(model, message.usage)
                self._log_usage(message, cost, started, answer)
                calls = [b for b in message.content if b.type == "tool_use"]
                if message.stop_reason != "tool_use" or not calls:
                    break
                lookups += len(calls)
                results = []
                for c in calls:
                    if c.name == SCREEN_TOOL["name"]:
                        results.append({"type": "tool_result", "tool_use_id": c.id, "content": self._screen_result()})
                        continue
                    title, text = self.wiki.search((c.input or {}).get("query", ""))
                    if on_lookup is not None and title:
                        on_lookup(title)
                    results.append({"type": "tool_result", "tool_use_id": c.id, "content": text})
                # append-only: odpoved modelu (aj s thinking blokmi) presne tak, ako prisla, potom vysledky
                kwargs["messages"] = [*kwargs["messages"], {"role": "assistant", "content": message.content},
                                      {"role": "user", "content": results}]
                if lookups >= self.max_lookups:
                    kwargs["tool_choice"] = {"type": "none"}  # dost hladania, teraz odpovedz
        except Exception as e:
            logger.warning("Claude ask zlyhalo: %s", e)
            answer.error = str(e)
            answer.cost = cost
            answer.total_sec = time.perf_counter() - started
            return answer

        answer.total_sec = time.perf_counter() - started
        answer.cost = cost
        answer.lookups = lookups
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
        usage = message.usage
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
