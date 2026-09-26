"""Efekty na Miranin hlas: z Azure hlasu spravi AI z Night City.

Retaz: horna a dolna priepust (radiovy, "implantovy" zvuk) -> bitcrusher (digitalna zrnitost)
-> ring modulacia (kovovy, strojovy nadych) -> chorus (zdvojeny synteticky hlas) -> kratke echo
-> kompresor a vyrovnanie hlasitosti (rovnako hlasna ako bez efektov, ziadne orezanie).

Efekty sa aplikuju v Voice.to_device_audio, takze ich maju odpovede, fillery aj nahravka v Nastaveniach
a funguju na sluchadlach aj cez Voicemeeter. Kazda veta sa spracuje samostatne; echo dostane chvost
ticha, ktory sa potom oreze, aby sa medzi vetami nerobili dlhe pauzy.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Hodnoty 0 = efekt vypnuty. Poradie v GUI: od najjemnejsieho.
PRESETS = {
    "jemny": {
        "highpass_hz": 120, "lowpass_hz": 9000, "bitcrush_bits": 0, "ring_hz": 0, "ring_mix": 0.0,
        "chorus_mix": 0.15, "echo_ms": 60, "echo_mix": 0.08,
    },
    "night_city": {
        "highpass_hz": 170, "lowpass_hz": 7000, "bitcrush_bits": 12, "ring_hz": 55, "ring_mix": 0.12,
        "chorus_mix": 0.22, "echo_ms": 80, "echo_mix": 0.12,
    },
    "robot": {
        "highpass_hz": 250, "lowpass_hz": 5200, "bitcrush_bits": 9, "ring_hz": 90, "ring_mix": 0.35,
        "chorus_mix": 0.3, "echo_ms": 110, "echo_mix": 0.18,
    },
}
PRESET_LABELS = {"vypnute": "vypnuté", "jemny": "jemný", "night_city": "Night City", "robot": "robot"}

TAIL_SEC = 0.4          # ticho na koniec, aby echo doznelo
PEAK = 0.89             # -1 dBFS
SILENCE_LEVEL = 0.002   # pod touto urovnou sa chvost po spracovani oreze (~ -54 dB)


def resolve(cfg: dict | None) -> dict | None:
    """tts.effects z configu -> parametre retaze, alebo None ked su efekty vypnute."""
    cfg = cfg or {}
    preset = cfg.get("preset", "vypnute")
    if not cfg.get("enabled", True) or preset not in PRESETS:
        return None
    params = dict(PRESETS[preset])
    params.update({k: v for k, v in (cfg.get("params") or {}).items() if k in params})  # jemne doladenie v configu
    return params


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2)))


class VoiceFx:
    def __init__(self, cfg: dict | None):
        self.params = resolve(cfg)
        if self.params is not None:
            try:
                import pedalboard  # noqa: F401
            except ImportError:
                logger.warning("pedalboard nie je nainstalovany (pip install pedalboard) — hlas ide bez efektov")
                self.params = None
        if self.params:
            logger.info("efekty hlasu: %s", (cfg or {}).get("preset"))

    @property
    def enabled(self) -> bool:
        return self.params is not None

    def _board(self, p: dict):
        # Nova retaz pre kazde volanie: filler a odpoved sa spracuvaju v roznych vlaknach naraz
        import pedalboard as pb

        chain = []
        if p["highpass_hz"]:
            chain.append(pb.HighpassFilter(cutoff_frequency_hz=float(p["highpass_hz"])))
        if p["lowpass_hz"]:
            chain.append(pb.LowpassFilter(cutoff_frequency_hz=float(p["lowpass_hz"])))
        if p["bitcrush_bits"]:
            chain.append(pb.Bitcrush(bit_depth=float(p["bitcrush_bits"])))
        post = []
        if p["chorus_mix"]:
            post.append(pb.Chorus(rate_hz=0.8, depth=0.15, centre_delay_ms=7.0, feedback=0.0, mix=float(p["chorus_mix"])))
        if p["echo_ms"] and p["echo_mix"]:
            post.append(pb.Delay(delay_seconds=p["echo_ms"] / 1000, feedback=0.2, mix=float(p["echo_mix"])))
        post.append(pb.Compressor(threshold_db=-18, ratio=3, attack_ms=5, release_ms=80))
        return pb.Pedalboard(chain), pb.Pedalboard(post)

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """int16 (vzorky, kanaly) -> int16 rovnakeho tvaru s efektmi. Pri chybe vrati povodne audio."""
        if self.params is None or audio.size == 0:
            return audio
        try:
            p = self.params
            x = audio.astype(np.float32).T / 32768.0          # pedalboard chce (kanaly, vzorky)
            x = np.pad(x, ((0, 0), (0, int(sample_rate * TAIL_SEC))))
            pre, post = self._board(p)
            level_in = _rms(x)
            x = pre(x, sample_rate)
            if p["ring_hz"] and p["ring_mix"]:
                t = np.arange(x.shape[1], dtype=np.float32) / sample_rate
                carrier = np.sin(2 * np.pi * p["ring_hz"] * t)
                x = x * (1 - p["ring_mix"]) + x * carrier * p["ring_mix"]
            x = post(x, sample_rate)
            # filtre a kompresor hlas stisia — vrat ho na povodnu hlasitost (max +9 dB), spicky najviac -1 dB
            x = x * min(level_in / max(_rms(x), 1e-6), 2.8)
            peak = float(np.abs(x).max())
            if peak > PEAK:
                x = x * (PEAK / peak)
            loud = np.nonzero(np.abs(x).max(axis=0) > SILENCE_LEVEL)[0]
            end = max(audio.shape[0], int(loud[-1]) + 1) if loud.size else audio.shape[0]
            x = x[:, :end]
            return (np.clip(x.T, -1.0, 1.0) * 32767).astype(np.int16)
        except Exception:
            logger.exception("efekty hlasu zlyhali, veta ide bez nich")
            return audio
