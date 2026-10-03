"""Nahradne komponenty pre testy orchestracie: bez mikrofonu, zvuku, siete a modelu.

Speaker, pamat, rozpocet, momenty na strih aj protokol HUD su skutocne — testuje sa ich spolupraca.
"""

import threading
import time
from types import SimpleNamespace

import numpy as np

from mirana.llm.brain import Answer
from mirana.outputs.overlay import Overlay


class FakeVoice:
    device_rate = 1000

    def __init__(self, config=None):
        self.volume = 1.0
        self.on_level = None
        self.played: list[int] = []
        self._stop = threading.Event()
        self.sentence_sec = 0.15

    def synthesize(self, text, timeout=None):
        return text.encode("utf-8")

    def to_device_audio(self, wav):
        return np.zeros((len(wav), 1), dtype=np.int16)

    def play_audio(self, audio, block=True):
        self.played.append(audio.shape[0])
        self._stop.wait(self.sentence_sec)

    def arm(self):
        self._stop.clear()

    def stop(self):
        self._stop.set()

    @property
    def stopped(self):
        return self._stop.is_set()

    def wait(self):
        pass


class FakeBrain:
    """Odpoved je zoznam viet; kazda pride po `delay` s. Prepis = WAV bytes ako text."""

    def __init__(self, config=None, budget=None, wiki=None):
        self.budget = budget
        self.stt = SimpleNamespace()
        self.wiki = wiki
        self.anthropic_client = None
        self.memory_block = None
        self.reply = ["Prvá veta odpovede je tu.", "Druhá veta ide hneď za ňou."]
        self.delay = 0.05
        self.fail = False
        self.asked: list[str] = []

    def transcribe(self, wav):
        return wav.decode("utf-8")

    def ask_stream(self, user_text, game_state_line, memory_messages, on_sentence=None, should_stop=None,
                   on_lookup=None, image_b64=None):
        self.asked.append(user_text)
        if self.fail:
            return Answer(ok=False, error="spojenie", model="fake")
        said = []
        for sentence in self.reply:
            time.sleep(self.delay)
            if should_stop and should_stop():
                return Answer(ok=True, text=" ".join(said), sentences=said, stop_reason="interrupted", model="fake")
            said.append(sentence)
            on_sentence(sentence)
        return Answer(ok=True, text=" ".join(said), sentences=said, stop_reason="end_turn", model="fake",
                      cost=0.001, total_sec=0.1)


class RecordingOverlay(Overlay):
    """Skutocny protokol (event() kontroluje polia), spravy sa len zapisuju."""

    def __init__(self, config):
        self.sent: list[dict] = []            # uz __init__ Overlay posiela spravu "hud"
        super().__init__(config)

    def _send(self, kind, /, **fields):
        super()._send(kind, **fields)
        self.sent.append({"type": kind, **fields})

    def of(self, kind):
        return [e for e in self.sent if e["type"] == kind]


class FakeFillers:
    def __init__(self, config=None, voice=None):
        self.enabled = False
        self.delay_sec = 10

    def play_random(self):
        return None

    def play_search(self):
        return None

    def search_lines(self, first=None):
        return []


class FakePtt:
    def __init__(self, config=None, on_start=None, on_recording=None):
        self.on_start, self.on_recording = on_start, on_recording
        self.on_level = self.on_panic = self.on_marker = None

    def start(self):
        pass


class FakeGame:
    def __init__(self, config=None, on_event=None, on_snapshot=None):
        self.on_event, self.on_snapshot = on_event, on_snapshot
        self.current = None

    def line(self):
        return None

    def start(self):
        pass


class FakeChat:
    def __init__(self, config=None, on_message=None, on_status=None):
        self.on_message = on_message

    def recent_logins(self):
        return []

    def line(self):
        return None

    def start(self):
        pass


class FakeVision:
    def __init__(self, config=None):
        pass

    def wants(self, question):
        return False

    def capture(self):
        return None
