"""Push-to-talk: drz F12, nahravaj z audio.input_device, pusti, vrat WAV v pamati."""

import io
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
import yaml
from pynput import keyboard

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _to_wav_bytes(frames: list[np.ndarray], sample_rate: int) -> bytes:
    audio = np.concatenate(frames, axis=0) if frames else np.zeros((0, 1), dtype=np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(audio.shape[1])
        wav_file.setsampwidth(2)  # int16
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.tobytes())
    return buffer.getvalue()


class PushToTalk:
    """Drz nakonfigurovany kys, nahravaj z input_device. Pustenie vrati WAV bytes cez on_recording."""

    def __init__(self, config: dict | None = None, on_recording=None, on_start=None):
        self.config = config or load_config()
        self.on_recording = on_recording
        self.on_start = on_start

        audio_cfg = self.config["audio"]
        self.input_device = audio_cfg["input_device"]
        self.sample_rate = audio_cfg["sample_rate"]
        self.ptt_key = self._parse_key(audio_cfg["ptt_key"])

        self._recording = False
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._listener: keyboard.Listener | None = None

    @staticmethod
    def _parse_key(name: str):
        return getattr(keyboard.Key, name)

    def _audio_callback(self, indata, frames, time_info, status):
        if self._recording:
            self._frames.append(indata.copy())

    def _start_recording(self):
        if self._recording:
            return
        self._recording = True
        self._frames = []
        if self.on_start is not None:
            self.on_start()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            device=self.input_device,
            channels=1,
            dtype="int16",
            callback=self._audio_callback,
        )
        self._stream.start()

    def _stop_recording(self):
        if not self._recording:
            return
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        wav_bytes = _to_wav_bytes(self._frames, self.sample_rate)
        self._frames = []
        if self.on_recording is not None:
            self.on_recording(wav_bytes)

    def _on_press(self, key):
        if key == self.ptt_key:
            self._start_recording()

    def _on_release(self, key):
        if key == self.ptt_key:
            self._stop_recording()

    def start(self):
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        return self._listener

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


if __name__ == "__main__":
    print("Drz F12 pre nahravanie, pusti pre ulozenie do test.wav. Ctrl+C pre ukoncenie.")

    def _save(wav_bytes: bytes):
        with open("test.wav", "wb") as f:
            f.write(wav_bytes)
        print(f"Ulozene: test.wav ({len(wav_bytes)} bajtov)")

    ptt = PushToTalk(on_recording=_save)
    listener = ptt.start()
    try:
        listener.join()
    except KeyboardInterrupt:
        ptt.stop()
