"""Voice: Azure TTS (sk-SK-ViktoriaNeural) do pamate, prehratie cez sounddevice na audio.output_device."""

import io
import os
import re
import wave
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import azure.cognitiveservices.speech as speechsdk
import numpy as np
import sounddevice as sd
import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"

load_dotenv(BASE_DIR / ".env")

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "]+",
    flags=re.UNICODE,
)

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def sanitize_text(text: str) -> str:
    """Vycisti text pred TTS: preč markdown formatovanie a emoji, ostane len ciste znenie."""
    text = _MARKDOWN_LINK_PATTERN.sub(r"\1", text)
    text = _EMOJI_PATTERN.sub("", text)
    text = re.sub(r"[*_`~#>]", "", text)
    text = re.sub(r"^\s*[-•+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


class Voice:
    """Azure TTS -> WAV v pamati -> prehratie na audio.output_device."""

    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        tts_cfg = self.config["tts"]
        audio_cfg = self.config["audio"]

        self.output_device = audio_cfg["output_device"]
        self._rate = tts_cfg["rate"]
        self._pitch = tts_cfg["pitch"]

        self.speech_config = speechsdk.SpeechConfig(
            subscription=os.environ.get("AZURE_SPEECH_KEY"),
            region=os.environ.get("AZURE_SPEECH_REGION"),
        )
        self.speech_config.speech_synthesis_voice_name = tts_cfg["voice"]
        self.speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
        )

        self._synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.speech_config, audio_config=None)

    def _build_ssml(self, clean_text: str) -> str:
        voice = self.speech_config.speech_synthesis_voice_name
        return (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="sk-SK">'
            f'<voice name="{voice}">'
            f'<prosody rate="{self._rate}" pitch="{self._pitch}">{xml_escape(clean_text)}</prosody>'
            "</voice></speak>"
        )

    def synthesize(self, text: str) -> bytes:
        """Sanitizuje text a syntetizuje ho do WAV bytes v pamati."""
        clean_text = sanitize_text(text)
        ssml = self._build_ssml(clean_text)
        result = self._synthesizer.speak_ssml_async(ssml).get()

        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            details = result.cancellation_details
            reason = details.reason if details else result.reason
            raise RuntimeError(f"Azure TTS zlyhalo: {reason}")

        return result.audio_data

    def play(self, wav_bytes: bytes) -> None:
        """Prehra WAV bytes na nakonfigurovane vystupne zariadenie."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            frames = wav_file.readframes(wav_file.getnframes())

        audio = np.frombuffer(frames, dtype=np.int16).reshape(-1, channels)
        sd.play(audio, samplerate=sample_rate, device=self.output_device)
        sd.wait()

    def stop(self) -> None:
        """Okamzite zastavi prehravanie."""
        sd.stop()

    def say(self, text: str) -> None:
        """Sanitizuje, syntetizuje a prehra text na nakonfigurovanom zariadeni."""
        wav_bytes = self.synthesize(text)
        self.play(wav_bytes)
