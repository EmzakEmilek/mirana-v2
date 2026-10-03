"""Frekvencne pasma hlasu pre HUD (gula reaguje na vysku hlasu, nielen na hlasitost).

Kus zvuku (~50 ms) -> 12 cisel 0..1 od hlbok (~90 Hz) po sykavky (~8 kHz), logaritmicky ako sluch.
Pocita sa pre hlas Mirany (mirana/outputs/voice.py) aj pre mikrofon pocas PTT (mirana/inputs/ptt.py).
"""

import numpy as np

N_BANDS = 12
LOW_HZ, HIGH_HZ = 90.0, 8000.0
FLOOR_DB, RANGE_DB = -78.0, 54.0       # -78 dB = nic, -24 dB = plne pasmo (nastavene na hlas Mirany a mikrofon)

_edges_cache: dict[tuple[int, int], np.ndarray] = {}


def _edges(n_fft: int, rate: int) -> np.ndarray:
    key = (n_fft, rate)
    if key not in _edges_cache:
        hz = np.geomspace(LOW_HZ, min(HIGH_HZ, rate / 2 - 1), N_BANDS + 1)
        _edges_cache[key] = np.clip(np.round(hz * n_fft / rate).astype(int), 1, n_fft // 2)
    return _edges_cache[key]


def bands(samples: np.ndarray, rate: int) -> list[float]:
    """int16 alebo float zvuk (mono alebo viac kanalov) -> N_BANDS hodnot 0..1 (zaokruhlene na 2 miesta)."""
    x = np.asarray(samples)
    if x.ndim > 1:
        x = x[:, 0]
    if x.size < 64:
        return [0.0] * N_BANDS
    x = x.astype(np.float32)
    if np.issubdtype(np.asarray(samples).dtype, np.integer):
        x /= 32768.0
    n_fft = 1 << int(np.ceil(np.log2(x.size)))
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size), n=n_fft)) / x.size
    edges = _edges(n_fft, rate)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mag = float(np.sqrt(np.mean(spec[lo:max(hi, lo + 1)] ** 2)))
        db = 20.0 * np.log10(mag + 1e-9)
        out.append(round(min(1.0, max(0.0, (db - FLOOR_DB) / RANGE_DB)), 2))
    return out
