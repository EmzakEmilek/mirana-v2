"""Spolocne pre testy: nikdy nehrat zvuk, subory len v docasnom priecinku, ziadne volania API."""

import copy
import os
import sys
from pathlib import Path

os.environ["MIRANA_NO_AUDIO"] = "1"        # musi byt pred importom outputs.voice
os.environ["MIRANA_NO_AUDIO_SPEED"] = "50"

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from core.config import load_config  # noqa: E402

_CONFIG = load_config()


@pytest.fixture
def config() -> dict:
    """Skutocny config.yaml (kopia — test ho moze menit)."""
    return copy.deepcopy(_CONFIG)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Vsetky subory Mirany (pamat, statistiky, logy, rozpocet) do docasneho priecinka."""
    import core.budget
    import core.highlights
    import core.longterm
    import core.session
    logs, data = tmp_path / "logs", tmp_path / "data"
    monkeypatch.setattr(core.budget, "BUDGET_PATH", data / "budget.json")
    monkeypatch.setattr(core.highlights, "LOGS_DIR", logs)
    monkeypatch.setattr(core.highlights, "STATS_PATH", data / "stream_stats.json")
    monkeypatch.setattr(core.longterm, "MEMORY_PATH", data / "memory.json")
    monkeypatch.setattr(core.longterm, "LOGS_DIR", logs)
    monkeypatch.setattr(core.session, "LOGS_DIR", logs)
    return tmp_path
