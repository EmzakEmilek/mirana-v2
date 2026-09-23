"""Voice: Azure TTS do pamate (s timeoutom), prehratie cez sounddevice na audio.output_device."""

import ctypes
import io
import os
import re
import sys
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
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


def _ensure_com() -> None:
    """PortAudio WASAPI vyzaduje COM inicializovany v aktualnom vlakne; hlavne vlakno ho ma, nove nie.

    CoInitializeEx je idempotentne (S_FALSE pri opakovani, RPC_E_CHANGED_MODE pri inom modeli — oboje neskodne).
    """
    if sys.platform == "win32":
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED


def _level(chunk: np.ndarray) -> float:
    """RMS int16 kusu -> 0..1, s miernou kompresiou, aby aj tichsia rec hybala vizualom."""
    rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 32767.0
    return min(1.0, (rms * 4.0) ** 0.6)


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linearna interpolacia — pre rec staci, pouzije sa len ak Azure nevie nativnu frekvenciu vystupu."""
    src_len = audio.shape[0]
    dst_len = int(round(src_len * dst_rate / src_rate))
    positions = np.linspace(0, src_len - 1, dst_len)
    channels = [np.interp(positions, np.arange(src_len), audio[:, c]) for c in range(audio.shape[1])]
    return np.stack(channels, axis=1).astype(np.int16)


_NON_LATIN_PATTERN = re.compile(r"[Ѐ-ӿԀ-ԯ　-鿿가-힯豈-﫿]")


# Slovenske koncovky, ktore sa smu pripojit k dlhsiemu klucu (Silverhandom, Dogtownu, questy, netrunnera)
_SUFFIX = r"(?P<suf>[a-záäčďéíĺľňóôŕšťúýž]{0,4})"


def load_phonetics(path) -> list[tuple[re.Pattern, str]]:
    """Nacita phonetics.yaml -> zoznam (regex, nahrada), najdlhsi kluc prvy.

    Vzdy cele slovo. Kluc od 5 znakov smie mat slovensku koncovku (Silverhandom -> Silverhendom);
    kratsi kluc (OS, RAM, HP, tech) plati len ako samostatne slovo a pri skratkach aj s presnou
    velkostou pismen — inak by prepisal bezne slova (ostatni -> "ó estatní", technika -> "teknika").
    """
    with open(path, "r", encoding="utf-8") as f:
        mapping = yaml.safe_load(f) or {}
    rules = []
    for key, value in sorted(mapping.items(), key=lambda kv: -len(str(kv[0]))):
        key = str(key)
        suffix = _SUFFIX if len(key) >= 5 else "(?P<suf>)"
        flags = 0 if (len(key) <= 3 and key.isupper()) else re.IGNORECASE
        pattern = re.compile(r"(?<!\w)" + re.escape(key) + suffix + r"(?!\w)", flags)
        rules.append((pattern, str(value)))
    return rules


def apply_phonetics(text: str, rules: list[tuple[re.Pattern, str]]) -> str:
    """Prepise anglicizmy foneticky pre TTS. Velke zaciatocne pismeno sa preberie z originalu."""
    for pattern, replacement in rules:
        def _sub(match, replacement=replacement):
            found = match.group(0)
            out = replacement
            if found[:1].isupper() and not out[:1].isupper():
                out = out[:1].upper() + out[1:]
            elif found[:1].islower() and out[:1].isupper():
                out = out[:1].lower() + out[1:]
            return out + match.group("suf")
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
        self._play_lock = threading.Lock()   # naraz hra len jedno
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_level = None  # callback(0..1) pre kazdy prehrany kus — HUD vizualizacia hlasu
        output_format = _AZURE_FORMATS.get(self.device_rate, speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm)
        speech_config.set_speech_synthesis_output_format(output_format)
        self._synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        # Jedno vlakno: Azure synthesizer nie je stavany na paralelne volania z viacerych vlakien
        self._synth_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")

    def _build_ssml(self, clean_text: str) -> str:
        return (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="sk-SK">'
            f'<voice name="{self._voice}">'
            f'<prosody rate="{self._rate}" pitch="{self._pitch}">{xml_escape(clean_text)}</prosody>'
            "</voice></speak>"
        )

    def synthesize(self, text: str, timeout: float | None = None) -> bytes:
        """Sanitizuje text a syntetizuje ho do WAV bytes v pamati. Pri prekroceni timeoutu TimeoutError."""
        spoken = apply_phonetics(sanitize_text(text), self._phonetics)
        future = self._synth_pool.submit(lambda: self._synthesizer.speak_ssml_async(self._build_ssml(spoken)).get())
        result = future.result(timeout=timeout)  # concurrent.futures.TimeoutError je podtrieda TimeoutError
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            details = result.cancellation_details
            reason = details.reason if details else result.reason
            raise RuntimeError(f"Azure TTS zlyhalo: {reason}")
        return result.audio_data

    def to_device_audio(self, wav_bytes: bytes) -> np.ndarray:
        """WAV bytes -> int16 pole vo frekvencii vystupneho zariadenia (pripravene na sd.play)."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            frames = wav_file.readframes(wav_file.getnframes())

        audio = np.frombuffer(frames, dtype=np.int16).reshape(-1, channels)
        if sample_rate != self.device_rate:
            audio = _resample(audio, sample_rate, self.device_rate)
        return audio

    def play_audio(self, audio: np.ndarray, block: bool = True) -> None:
        """Prehra pripravene pole na vystupne zariadenie.

        Vlastny OutputStream s blokujucim write po 50 ms kusoch: stop() len nastavi flag, ktory
        prehravacie vlakno skontroluje pred dalsim kusom. sd.stop() z ineho vlakna WASAPI stream
        zhadzoval (crash procesu), toto je bezpecne z ktorehokolvek vlakna.
        """
        if block:
            self._play_blocking(audio)
            return
        self._thread = threading.Thread(target=self._play_blocking, args=(audio,), daemon=True)
        self._thread.start()

    def arm(self) -> None:
        """Zrusi predchadzajuci stop — volat na zaciatku novej ulohy (novy job), nie pred kazdou vetou.

        Keby sa stop nuloval pri kazdom prehrati, barge-in tesne pred startom vety by sa stratil.
        """
        self._stop_event.clear()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def _play_blocking(self, audio: np.ndarray) -> None:
        _ensure_com()  # WASAPI stream z ineho vlakna (filler timer, worker) inak zlyha
        with self._play_lock:
            if self._stop_event.is_set():
                return
            chunk = int(self.device_rate * 0.05)
            with sd.OutputStream(
                samplerate=self.device_rate, device=self.output_device, channels=audio.shape[1], dtype="int16"
            ) as stream:
                for start in range(0, audio.shape[0], chunk):
                    if self._stop_event.is_set():
                        break
                    piece = np.ascontiguousarray(audio[start:start + chunk])
                    if self.on_level is not None:
                        self.on_level(_level(piece))
                    stream.write(piece)
            if self.on_level is not None:
                self.on_level(0.0)

    def play(self, wav_bytes: bytes) -> None:
        """Prehra WAV bytes na nakonfigurovane vystupne zariadenie (blokuje do konca). Pre testy a nastroje."""
        self.arm()
        self.play_audio(self.to_device_audio(wav_bytes))

    def wait(self) -> None:
        """Pocka na koniec neblokujuceho prehravania (napr. filler pred odpovedou)."""
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def stop(self) -> None:
        """Okamzite zastavi prehravanie (barge-in). Bezpecne z ktorehokolvek vlakna."""
        self._stop_event.set()

    def say(self, text: str) -> None:
        self.play(self.synthesize(text))
