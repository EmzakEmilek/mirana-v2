"""Spolocne pre testy: nikdy nehrat zvuk, subory len v docasnom priecinku, ziadne volania API."""

import copy
import os
import sys
from pathlib import Path

os.environ["MIRANA_NO_AUDIO"] = "1"        # musi byt pred importom mirana.outputs.voice
os.environ["MIRANA_NO_AUDIO_SPEED"] = "50"

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from mirana.config import load_config  # noqa: E402

_CONFIG = load_config()


@pytest.fixture
def config() -> dict:
    """Skutocny config.yaml (kopia — test ho moze menit)."""
    return copy.deepcopy(_CONFIG)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Vsetky subory Mirany (pamat, statistiky, logy, rozpocet) do docasneho priecinka."""
    import mirana.budget
    import mirana.features.highlights
    import mirana.features.longterm
    import mirana.session
    logs, data = tmp_path / "logs", tmp_path / "data"
    monkeypatch.setattr(mirana.budget, "BUDGET_PATH", data / "budget.json")
    monkeypatch.setattr(mirana.features.highlights, "LOGS_DIR", logs)
    monkeypatch.setattr(mirana.features.highlights, "STATS_PATH", data / "stream_stats.json")
    monkeypatch.setattr(mirana.features.longterm, "MEMORY_PATH", data / "memory.json")
    monkeypatch.setattr(mirana.features.longterm, "LOGS_DIR", logs)
    monkeypatch.setattr(mirana.session, "LOGS_DIR", logs)
    return tmp_path
