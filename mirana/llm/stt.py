"""STT: Whisper API alebo lokalny faster-whisper (CUDA). Prepinac stt.provider v config.yaml.

Oba providery maju rovnake rozhranie: transcribe(wav_bytes) -> str | None.
Lokalny model sa nacita raz pri starte (medium ~ 3-5 s), potom je prepis rychlejsi nez API.
"""

import difflib
import io
import logging
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def _register_cuda_dlls() -> None:
    """CTranslate2 na Windows hlada cublas64_12.dll / cudnn64_9.dll v PATH.

    Dodavaju ich pip balicky nvidia-cublas-cu12 / nvidia-cudnn-cu12 (bez instalacie CUDA toolkitu),
    ale ich bin/ adresare treba pred importom zaregistrovat.
    """
    if sys.platform != "win32":
        return
    nvidia_dir = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for bin_dir in sorted(nvidia_dir.glob("*/bin")):
        os.add_dll_directory(str(bin_dir))
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


class ApiStt:
    """OpenAI Whisper API (whisper-1)."""

    def __init__(self, stt_cfg: dict, limits: dict):
        from openai import OpenAI

        self.model = stt_cfg["api_model"]
        self.language = stt_cfg["language"]
        # API kluc si SDK cita z OPENAI_API_KEY (nacitane v mirana.config)
        self.client = OpenAI(timeout=limits["api_timeout_sec"], max_retries=limits["api_retries"])

    def transcribe(self, wav_bytes: bytes) -> str | None:
        try:
            result = self.client.audio.transcriptions.create(
                model=self.model,
                file=("audio.wav", wav_bytes, "audio/wav"),
                language=self.language,
            )
            return result.text
        except Exception as e:
            logger.warning("Whisper API zlyhalo: %s", e)
            return None


class LocalStt:
    """faster-whisper na GPU. Model sa stiahne pri prvom spusteni do HF cache (~1.5 GB pre medium)."""

    def __init__(self, stt_cfg: dict):
        _register_cuda_dlls()
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")  # Windows bez dev mode: HF cache bez symlinkov
        from faster_whisper import WhisperModel

        self.language = stt_cfg["language"]
        # Slovnik nazvov ako initial_prompt — Whisper ho berie ako predchadzajuci kontext a preferuje tieto tvary.
        vocabulary = stt_cfg.get("local_vocabulary") or []
        prefix = stt_cfg.get("local_prompt_prefix") or ""
        self.initial_prompt = f"{prefix} {', '.join(vocabulary)}.".strip() if vocabulary else None
        self.prompt_prefix = prefix
        started = time.perf_counter()
        args = dict(device=stt_cfg["local_device"], compute_type=stt_cfg["local_compute_type"])
        try:
            # Z disku bez kontroly novej verzie na internete — Mirana nastartuje aj offline
            self.model = WhisperModel(stt_cfg["local_model"], local_files_only=True, **args)
        except Exception:
            self.model = WhisperModel(stt_cfg["local_model"], **args)  # prvy start: stiahne model
        logger.info(
            "faster-whisper %s (%s/%s) nacitany za %.1f s",
            stt_cfg["local_model"], stt_cfg["local_device"], stt_cfg["local_compute_type"],
            time.perf_counter() - started,
        )
        if self.initial_prompt:
            # Whisper pouzije len poslednych 224 tokenov promptu — dlhsi slovnik by ticho stratil zaciatok.
            prompt_tokens = len(self.model.hf_tokenizer.encode(" " + self.initial_prompt).ids)
            if prompt_tokens > 224:
                logger.warning("stt.local_vocabulary ma %d tokenov (max 224), zaciatok zoznamu sa ignoruje", prompt_tokens)
        # Prvy prepis po starte je ~3x pomalsi (CUDA kernely) — zahrejeme sekundou ticha, nie Erikovou vetou.
        # vad_filter=True: VAD model (Silero) sa inak nacita az pri prvej otazke a ta trva o 2-3 s dlhsie
        list(self.model.transcribe(np.zeros(16000, dtype=np.float32), language=self.language, vad_filter=True)[0])

    def transcribe(self, wav_bytes: bytes) -> str | None:
        try:
            # beam_size 5 = default whispera; VAD odfiltruje ticho na zaciatku/konci PTT nahravky
            segments, _info = self.model.transcribe(
                io.BytesIO(wav_bytes),
                language=self.language,
                initial_prompt=self.initial_prompt,
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(segment.text.strip() for segment in segments)
        except Exception as e:
            logger.warning("faster-whisper zlyhalo: %s", e)
            return None
        if self._echoes_prompt(text):
            logger.info("prepis zahodeny, Whisper zopakoval slovnik z promptu: %s", text)
            return ""
        return text

    def _echoes_prompt(self, text: str) -> bool:
        """Z nezrozumitelneho zvuku Whisper obcas "prepise" vlastny initial_prompt (prefix alebo kus slovnika)."""
        if not self.initial_prompt or not text.strip():
            return False
        words = re.findall(r"\w+", text.lower())
        prompt_words = set(re.findall(r"\w+", self.initial_prompt.lower()))
        if len(words) >= 3 and all(w in prompt_words for w in words):
            return True
        prefix = self.prompt_prefix.lower()
        return bool(prefix) and difflib.SequenceMatcher(None, text.lower().strip(" .:"), prefix.strip(" .:")).ratio() > 0.7


def create_stt(config: dict):
    provider = config["stt"]["provider"]
    if provider == "local":
        return LocalStt(config["stt"])
    if provider == "api":
        return ApiStt(config["stt"], config["limits"])
    raise ValueError(f"neznamy stt.provider: {provider!r} (local | api)")


if __name__ == "__main__":
    # python -m mirana.llm.stt test.wav [dalsie.wav ...]  — prepis + latencia pre nakonfigurovany provider
    from mirana.config import load_config

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) < 2:
        sys.exit("pouzitie: python -m mirana.llm.stt subor.wav [...]  (nahravku vyrobis cez python -m mirana.inputs.ptt)")

    stt = create_stt(load_config())
    for path in sys.argv[1:]:
        wav = Path(path).read_bytes()
        started = time.perf_counter()
        text = stt.transcribe(wav)
        print(f"{path} [{time.perf_counter() - started:.2f} s]: {text!r}")
