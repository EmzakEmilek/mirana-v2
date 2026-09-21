"""Voice: Azure TTS (sk-SK-ViktoriaNeural) do pamate, prehratie cez sounddevice na audio.output_device."""

import io
import os
import re
import wave
from xml.sax.saxutils import escape as xml_escape

import azure.cognitiveservices.speech as speechsdk
import numpy as np
import sounddevice as sd
import yaml

from core.config import BASE_DIR

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


_AZURE_FORMATS = {
    16000: speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm,
    22050: speechsdk.SpeechSynthesisOutputFormat.Riff22050Hz16BitMonoPcm,
    24000: speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm,
    44100: speechsdk.SpeechSynthesisOutputFormat.Riff44100Hz16BitMonoPcm,
    48000: speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm,
}


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linearna interpolacia — pre rec staci, pouzije sa len ak Azure nevie nativnu frekvenciu vystupu."""
    src_len = audio.shape[0]
    dst_len = int(round(src_len * dst_rate / src_rate))
    positions = np.linspace(0, src_len - 1, dst_len)
    channels = [np.interp(positions, np.arange(src_len), audio[:, c]) for c in range(audio.shape[1])]
    return np.stack(channels, axis=1).astype(np.int16)


_NON_LATIN_PATTERN = re.compile(r"[Ѐ-ӿԀ-ԯ　-鿿가-힯豈-﫿]")


def load_phonetics(path) -> list[tuple[re.Pattern, str]]:
    """Nacita phonetics.yaml -> zoznam (regex, nahrada), najdlhsi kluc prvy.

    Regex chyta kluc na zaciatku slova bez ohladu na velkost pismen; koniec slova neviaze,
    aby preslo aj sklonovanie (Silverhandom -> Silverhendom).
    """
    with open(path, "r", encoding="utf-8") as f:
        mapping = yaml.safe_load(f) or {}
    rules = []
    for key, value in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        pattern = re.compile(r"(?<![\w])" + re.escape(str(key)), re.IGNORECASE)
        rules.append((pattern, str(value)))
    return rules


def apply_phonetics(text: str, rules: list[tuple[re.Pattern, str]]) -> str:
    """Prepise anglicizmy foneticky pre TTS. Velke zaciatocne pismeno sa preberie z originalu."""
    for pattern, replacement in rules:
        def _sub(match, replacement=replacement):
            found = match.group(0)
            if found[:1].isupper() and not replacement[:1].isupper():
                return replacement[:1].upper() + replacement[1:]
            if found[:1].islower() and replacement[:1].isupper():
                return replacement[:1].lower() + replacement[1:]
            return replacement
        text = pattern.sub(_sub, text)
    return text


def sanitize_text(text: str) -> str:
    """Vycisti text pred TTS: preč markdown formatovanie a emoji, ostane len ciste znenie."""
    text = _MARKDOWN_LINK_PATTERN.sub(r"\1", text)
    text = _EMOJI_PATTERN.sub("", text)
    text = re.sub(r"[*_`~#>]", "", text)
    # Model obcas pusti znak z ineho pisma (cyrilika, CJK) — TTS by ho precitala nezmyselne
    text = _NON_LATIN_PATTERN.sub("", text)
    text = re.sub(r"^\s*[-•+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


class Voice:
    """Azure TTS -> WAV v pamati -> prehratie na audio.output_device."""

    def __init__(self, config: dict):
        tts_cfg = config["tts"]
        self.output_device = config["audio"]["output_device"]
        self._voice = tts_cfg["voice"]
        self._rate = tts_cfg["rate"]
        self._pitch = tts_cfg["pitch"]
        # Fonetika anglicizmov ide len do TTS; log a titulky dostavaju povodny text.
        phonetics_file = tts_cfg.get("phonetics_file")
        self._phonetics = load_phonetics(BASE_DIR / phonetics_file) if phonetics_file else []

        speech_config = speechsdk.SpeechConfig(
            subscription=os.environ.get("AZURE_SPEECH_KEY"),
            region=os.environ.get("AZURE_SPEECH_REGION"),
        )
        speech_config.speech_synthesis_voice_name = self._voice
        # WASAPI neprevzorkuje — necham Azure vratit WAV rovno v nativnej frekvencii vystupu
        # (VoiceMeeter 48 kHz, G733 44.1 kHz). Ine frekvencie preveziem v play() cez numpy.
        self.device_rate = int(sd.query_devices(self.output_device, "output")["default_samplerate"])
        output_format = _AZURE_FORMATS.get(self.device_rate, speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm)
        speech_config.set_speech_synthesis_output_format(output_format)
        self._synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)

    def _build_ssml(self, clean_text: str) -> str:
        return (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="sk-SK">'
            f'<voice name="{self._voice}">'
            f'<prosody rate="{self._rate}" pitch="{self._pitch}">{xml_escape(clean_text)}</prosody>'
            "</voice></speak>"
        )

    def synthesize(self, text: str) -> bytes:
        """Sanitizuje text a syntetizuje ho do WAV bytes v pamati."""
        spoken = apply_phonetics(sanitize_text(text), self._phonetics)
        result = self._synthesizer.speak_ssml_async(self._build_ssml(spoken)).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            details = result.cancellation_details
            reason = details.reason if details else result.reason
            raise RuntimeError(f"Azure TTS zlyhalo: {reason}")
        return result.audio_data

    def play(self, wav_bytes: bytes) -> None:
        """Prehra WAV bytes na nakonfigurovane vystupne zariadenie (blokuje do konca)."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            frames = wav_file.readframes(wav_file.getnframes())

        audio = np.frombuffer(frames, dtype=np.int16).reshape(-1, channels)
        if sample_rate != self.device_rate:
            audio = _resample(audio, sample_rate, self.device_rate)
        sd.play(audio, samplerate=self.device_rate, device=self.output_device)
        sd.wait()

    def stop(self) -> None:
        """Okamzite zastavi prehravanie (barge-in)."""
        sd.stop()

    def say(self, text: str) -> None:
        self.play(self.synthesize(text))
