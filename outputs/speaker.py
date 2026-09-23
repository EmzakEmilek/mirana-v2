"""Speaker: streaming reci po vetach. Vety -> TTS (vlakno) -> prehravanie (vlakno).

Kym sa prehrava prva veta, druha sa uz syntetizuje, takze medzi vetami nie je pauza.
Kazda polozka nesie svoj job; zruseny job (barge-in) sa preskoci v oboch vlaknach.
Ked TTS zlyha alebo prekroci timeout, veta sa aspon vypise na HUD.
"""

import logging
import queue
import threading

logger = logging.getLogger(__name__)

_END = object()


class Speaker:
    def __init__(self, config: dict, voice, overlay, on_start, on_done):
        self.voice = voice
        self.overlay = overlay
        self.on_start = on_start  # on_start(job) — prva veta prave zaznieva
        self.on_done = on_done    # on_done(job) — dohovorila (alebo nebolo co povedat)
        self.tts_timeout = config["limits"].get("tts_timeout_sec", 10)
        self.tts_failed_text = config["fallback_phrases"]["tts_failed"]
        self.ms_per_char = config["overlay"]["typewriter_ms_per_char"]
        self._synth_q: queue.Queue = queue.Queue()
        self._play_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._synth_loop, name="speaker-tts", daemon=True).start()
        threading.Thread(target=self._play_loop, name="speaker-play", daemon=True).start()

    # --- verejne API (z ktorehokolvek vlakna) -----------------------------------------------

    def say(self, job, sentence: str) -> None:
        self._synth_q.put((job, sentence))

    def end(self, job) -> None:
        """Ziadne dalsie vety pre tento job — po poslednej zavola on_done."""
        self._synth_q.put((job, _END))

    def say_all(self, job, text: str) -> None:
        self.say(job, text)
        self.end(job)

    # --- vlakna -------------------------------------------------------------------------------

    def _synth_loop(self) -> None:
        while True:
            job, item = self._synth_q.get()
            if job.cancelled:
                continue
            if item is _END:
                self._play_q.put((job, _END, None))
                continue
            audio = None
            try:
                audio = self.voice.to_device_audio(self.voice.synthesize(item, timeout=self.tts_timeout))
            except Exception as e:
                logger.warning("TTS zlyhalo pre vetu %r: %s", item[:40], e)
            self._play_q.put((job, item, audio))

    def _play_loop(self) -> None:
        while True:
            job, item, audio = self._play_q.get()
            try:
                if job.cancelled:
                    continue
                if item is _END:
                    self.on_done(job)
                    continue
                self.voice.wait()  # filler musi dohrat, odpoved nesmie zacat cez neho
                if job.cancelled:
                    continue
                if not job.started:
                    job.started = True
                    self.overlay.answer_start()
                    self.on_start(job)
                job.spoken.append(item)
                if audio is None:
                    if not job.tts_failed:
                        job.tts_failed = True
                        self.overlay.question(self.tts_failed_text)
                    self.overlay.answer_append(item, ms_per_char=self.ms_per_char)
                    continue
                # HUD pise v tempe hlasu (93 % dlzky, nech text dobehne tesne pred koncom vety)
                duration = audio.shape[0] / self.voice.device_rate
                self.overlay.answer_append(item, duration_sec=duration * 0.93)
                self.voice.play_audio(audio, block=True)
            except Exception:
                logger.exception("prehravanie vety zlyhalo")
