"""Push-to-talk: drz klaves alebo tlacidlo mysi (audio.ptt_key), nahravaj z audio.input_device, pusti, vrat WAV.

ptt_key / panic_mute_key: klaves ("f4", "insert") alebo tlacidlo mysi ("mouse_x1" = zadne bocne,
"mouse_x2" = predne bocne, "mouse_middle"). Tlacidlo sa neblokuje — hra ho dostane tiez, preto
nech nema v hre priradenu akciu.

Audio stream je otvoreny stale (otvorenie zariadenia trva 50-300 ms a prisiel by si o zaciatok vety);
pri stlaceni sa len zapne zber ramcov.
"""

import io
import logging
import threading
import wave

import numpy as np
import sounddevice as sd
from pynput import keyboard, mouse

logger = logging.getLogger(__name__)


MOUSE_BUTTONS = {"mouse_x1": "x1", "mouse_x2": "x2", "mouse_middle": "middle"}
BUTTON_LABELS = {"mouse_x1": "zadné bočné tlačidlo myši", "mouse_x2": "predné bočné tlačidlo myši",
                 "mouse_middle": "koliesko myši"}


def parse_key(spec: str | None):
    """Nazov z configu -> pynput Key/KeyCode alebo mouse.Button. None ked nie je nastavene."""
    if not spec:
        return None
    spec = spec.strip().lower()
    if spec in MOUSE_BUTTONS:
        return getattr(mouse.Button, MOUSE_BUTTONS[spec])
    if hasattr(keyboard.Key, spec):
        return getattr(keyboard.Key, spec)
    if len(spec) == 1:
        return keyboard.KeyCode.from_char(spec)
    raise ValueError(f"neznamy klaves alebo tlacidlo: {spec}")


def key_label(spec: str | None) -> str:
    """Nazov pre ludi: "F4", "myš – zadné bočné"."""
    spec = (spec or "").strip().lower()
    return BUTTON_LABELS.get(spec) or spec.replace("_", " ").upper()


def _to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(audio.shape[1])
        wav_file.setsampwidth(2)  # int16
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.tobytes())
    return buffer.getvalue()


class PushToTalk:
    """Drz nakonfigurovany klaves, nahravaj z input_device. Pustenie vrati WAV bytes cez on_recording."""

    def __init__(self, config: dict, on_recording=None, on_start=None):
        self.on_recording = on_recording
        self.on_start = on_start
        self.on_panic = None  # callback() pri stlaceni panic_mute_key (F11)
        self.on_level = None  # callback(0..1) pocas nahravania, ~20x/s — HUD reaguje na Erikov hlas
        self.stream_stt = None  # STT so streamovanim (Azure): begin() pri stlaceni, feed() pocas nahravania
        self._level_frames = 0

        audio_cfg = config["audio"]
        self.input_device = audio_cfg["input_device"]
        try:
            sd.query_devices(self.input_device, "input")
        except Exception as e:  # odpojeny mikrofon nesmie zhodit Miranu
            logger.warning("mikrofon %r nie je dostupny (%s), nahravam z predvoleneho", self.input_device, e)
            self.input_device = None
        logger.info("mikrofon: %s", sd.query_devices(self.input_device, "input")["name"])
        # WASAPI neprevzorkuje: null = nativna frekvencia zariadenia (G733 = 48 kHz). Whisper si to prevzorkuje sam.
        self.sample_rate = audio_cfg["sample_rate"] or int(sd.query_devices(self.input_device, "input")["default_samplerate"])
        self.ptt_key = parse_key(audio_cfg["ptt_key"])
        self.panic_key = parse_key(audio_cfg.get("panic_mute_key"))
        self._panic_down = False
        self.marker_key = parse_key(audio_cfg.get("marker_key"))  # znacka na strih (moment vo VOD-ke)
        self.on_marker = None
        self._marker_down = False

        self._recording = False
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._listener: keyboard.Listener | None = None
        self._mouse_listener: mouse.Listener | None = None

    def _audio_callback(self, indata, frames, time_info, status):
        if self._recording:
            self._frames.append(indata.copy())
            if self.stream_stt is not None:
                try:
                    self.stream_stt.feed(indata)
                except Exception:
                    pass  # prepis zlyha neskor sam; audio callback nesmie spadnut
            if self.on_level is not None:
                self._level_frames += frames
                if self._level_frames >= self.sample_rate // 20:
                    self._level_frames = 0
                    rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2))) / 32767.0
                    self.on_level(min(1.0, (rms * 6.0) ** 0.6))

    def _on_click(self, x, y, button, pressed):
        if pressed:
            self._on_press(button)
        else:
            self._on_release(button)

    def _on_press(self, key):
        if key == self.marker_key and self.marker_key is not None:
            if not self._marker_down and self.on_marker is not None:
                self.on_marker()
            self._marker_down = True
            return
        if key == self.panic_key and self.panic_key is not None:
            if not self._panic_down and self.on_panic is not None:  # drzanie posiela opakovane press eventy
                self.on_panic()
            self._panic_down = True
            return
        # pynput posiela opakovane press eventy pocas drzania — flag to zachyti
        if key == self.ptt_key and not self._recording:
            self._frames = []
            if self.stream_stt is not None:
                self.stream_stt.begin(self.sample_rate)
            self._recording = True
            if self.on_start is not None:
                self.on_start()

    def _on_release(self, key):
        if key == self.marker_key:
            self._marker_down = False
            return
        if key == self.panic_key:
            self._panic_down = False
            return
        if key == self.ptt_key and self._recording:
            self._recording = False
            if self.on_level is not None:
                self.on_level(0.0)
            frames, self._frames = self._frames, []
            # spracovanie mimo hooku: pomaly callback mysi by v hre sekal kurzor
            threading.Thread(target=self._finish, args=(frames,), daemon=True).start()

    def _finish(self, frames: list[np.ndarray]) -> None:
        audio = np.concatenate(frames, axis=0) if frames else np.zeros((0, 1), dtype=np.int16)
        # peak < ~100 = mikrofon je mute alebo zly input_device
        peak = int(np.abs(audio).max()) if audio.size else 0
        logger.info("nahravka %.1f s, peak %d/32767", audio.shape[0] / self.sample_rate, peak)
        wav_bytes = _to_wav_bytes(audio, self.sample_rate)
        if self.on_recording is not None:
            self.on_recording(wav_bytes)

    def start(self) -> keyboard.Listener:
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            device=self.input_device,
            channels=1,
            dtype="int16",
            callback=self._audio_callback,
        )
        self._stream.start()
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        if any(isinstance(k, mouse.Button) for k in (self.ptt_key, self.panic_key, self.marker_key)):
            self._mouse_listener = mouse.Listener(on_click=self._on_click)
            self._mouse_listener.start()
        return self._listener

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


if __name__ == "__main__":
    from mirana.config import load_config

    print("Drz PTT (audio.ptt_key) pre nahravanie, pusti pre ulozenie do test.wav. Ctrl+C pre ukoncenie.")

    def _save(wav_bytes: bytes):
        with open("test.wav", "wb") as f:
            f.write(wav_bytes)
        print(f"Ulozene: test.wav ({len(wav_bytes)} bajtov)")

    ptt = PushToTalk(load_config(), on_recording=_save)
    listener = ptt.start()
    try:
        listener.join()
    except KeyboardInterrupt:
        ptt.stop()
