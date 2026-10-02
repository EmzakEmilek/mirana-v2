"""Orchestracia Mirany s nahradnymi komponentmi: otazka, barge-in, mute, urgentna hlaska, pripomienka, rozpocet.

Udalosti z fronty spracuva rovnaka funkcia ako hlavna slucka (_handle_event), len v teste.
"""

import queue
import time

import pytest

import main
from core.events import Quit
from inputs.game_state import Snapshot
from tests import fakes


@pytest.fixture
def mirana(config, data_dir, monkeypatch):
    for name, fake in (("Brain", fakes.FakeBrain), ("Voice", fakes.FakeVoice), ("Fillers", fakes.FakeFillers),
                       ("Overlay", fakes.RecordingOverlay), ("PushToTalk", fakes.FakePtt),
                       ("GameState", fakes.FakeGame), ("TwitchChat", fakes.FakeChat), ("Vision", fakes.FakeVision)):
        monkeypatch.setattr(main, name, fake)
    monkeypatch.setattr(main, "NOTES_PATH", data_dir / "logs" / "poznamky.md")
    config["idle_nudge"] = {"enabled": True, "after_min": 10, "max_in_row": 2}
    return main.Mirana(config, "20261002-200000")


def pump(m, until, timeout=5.0):
    """Spracuva udalosti z fronty, kym until() neplati (alebo timeout)."""
    end = time.time() + timeout
    while time.time() < end:
        if until():
            return
        try:
            event = m._events.get(timeout=0.02)
        except queue.Empty:
            continue
        assert not isinstance(event, Quit)
        m._handle_event(event)
    raise AssertionError(f"nesplnilo sa do {timeout} s, stav {m.state}")


def idle(m):
    return m.state is main.State.IDLE and m._events.empty()


def ask_by_voice(m, text):
    m._on_ptt_press()
    assert m.state is main.State.LISTENING
    m.ptt.on_recording(text.encode("utf-8"))


def test_voice_question_full_cycle(mirana):
    ask_by_voice(mirana, "kto je Padre?")
    pump(mirana, lambda: mirana.memory.as_messages() and idle(mirana))
    assert mirana.brain.asked[-1].endswith("[ERIK] kto je Padre?")
    assert mirana.memory.as_messages() == [
        {"role": "user", "content": "[ERIK] kto je Padre?"},
        {"role": "assistant", "content": "Prvá veta odpovede je tu. Druhá veta ide hneď za ňou."}]
    states = [e["state"] for e in mirana.overlay.of("state")]
    assert states == ["listening", "processing", "speaking", "idle"]
    assert len(mirana.voice.played) == 2
    assert mirana.conversation.path.exists()


def test_typed_question_interrupts_answer(mirana):
    mirana.brain.reply = [f"Toto je dlhá veta číslo {i} v odpovedi." for i in range(6)]
    mirana._handle_typed("prvá otázka")
    pump(mirana, lambda: mirana.state is main.State.SPEAKING)
    mirana.brain.reply = ["Krátka odpoveď na druhú otázku."]
    mirana._handle_typed("druhá otázka")
    pump(mirana, lambda: len(mirana.memory) == 2 and idle(mirana))
    first, second = mirana.memory.as_messages()[1], mirana.memory.as_messages()[3]
    assert first["content"].endswith(" …") and "číslo 5" not in first["content"]  # len to, co zaznelo
    assert second["content"] == "Krátka odpoveď na druhú otázku."


def test_barge_in_by_ptt(mirana):
    mirana.brain.reply = [f"Toto je dlhá veta číslo {i} v odpovedi." for i in range(6)]
    mirana._handle_typed("rozprávaj")
    pump(mirana, lambda: mirana.state is main.State.SPEAKING)
    mirana._on_ptt_press()  # Erik skoci do reci
    assert mirana.state is main.State.LISTENING and mirana.voice.stopped
    mirana.brain.reply = ["Dobre, počúvam."]
    mirana.ptt.on_recording("stop".encode("utf-8"))
    pump(mirana, lambda: len(mirana.memory) == 2 and idle(mirana))
    assert mirana.memory.as_messages()[-1]["content"] == "Dobre, počúvam."


def test_empty_transcript_is_silent(mirana):
    ask_by_voice(mirana, "   ")
    pump(mirana, lambda: idle(mirana) and mirana.overlay.of("state")[-1]["state"] == "idle")
    assert mirana.brain.asked == [] and len(mirana.memory) == 0


def test_mute_ignores_ptt_and_typed(mirana):
    mirana._on_panic()
    mirana._on_ptt_press()
    assert mirana.state is main.State.IDLE
    mirana._handle_typed("počuješ?")
    assert mirana.brain.asked == []
    assert "stlmená" in mirana.overlay.of("notice")[-1]["text"]
    mirana._on_panic()
    mirana._handle_typed("a teraz?")
    pump(mirana, lambda: len(mirana.memory) == 1 and idle(mirana))


def test_budget_reached_says_fallback(mirana, config):
    mirana.budget.cap = 0.0
    mirana._handle_typed("ahoj")
    pump(mirana, lambda: mirana.voice.played and idle(mirana))
    assert mirana.brain.asked == [] and len(mirana.memory) == 0  # fallback sa nepamata


def test_llm_failure_says_fallback(mirana):
    mirana.brain.fail = True
    mirana._handle_typed("ahoj")
    pump(mirana, lambda: mirana.voice.played and idle(mirana))
    assert len(mirana.memory) == 0


def test_urgent_game_event_waits_for_answer(mirana):
    mirana.brain.reply = [f"Toto je dlhá veta číslo {i} v odpovedi." for i in range(3)]
    mirana._handle_typed("otázka")
    pump(mirana, lambda: mirana.state is main.State.SPEAKING)
    mirana._handle_game_event("hp_critical", Snapshot({"in_game": True, "hp": 5}), "zdravie kleslo na 5 %")
    assert mirana._pending_urgent is not None
    pump(mirana, lambda: any("[GAME_EVENT]" in q for q in mirana.brain.asked) and idle(mirana))
    assert mirana._pending_urgent is None


def test_normal_game_event_respects_quiet_after_erik(mirana):
    mirana._last_erik = time.time()
    mirana._handle_game_event("level_up", Snapshot({"in_game": True, "level": 7}), "Erik postúpil na úroveň 7")
    assert mirana.state is main.State.IDLE and mirana.brain.asked == []


def test_game_event_records_highlight_and_fx(mirana):
    text = mirana._record_game_event("death", Snapshot({"in_game": True, "hp": 0, "district": "Watson"}), "Erik práve zomrel")
    assert text == "Erik práve zomrel (dnes už 1. smrť)"
    assert mirana.overlay.of("game_fx")[-1] == {"type": "game_fx", "kind": "death", "text": "FLATLINE #1"}
    assert mirana.highlights.path.read_text(encoding="utf-8").count("SMRŤ") == 1


def test_idle_nudge_rules(mirana):
    mirana._maybe_nudge()
    assert mirana.brain.asked == []                       # este neubehlo 10 minut
    mirana._idle_since = time.time() - 11 * 60
    mirana.game.current = Snapshot({"in_game": True, "combat": True})
    mirana._maybe_nudge()
    assert mirana.brain.asked == []                       # v boji nie
    mirana.game.current = None
    for _ in range(3):
        mirana._last_nudge = 0
        mirana._maybe_nudge()
        pump(mirana, lambda: idle(mirana))
    assert sum("[IDLE]" in q for q in mirana.brain.asked) == 2  # max_in_row, potom caka na Erika
    mirana._handle_typed("som tu")
    pump(mirana, lambda: idle(mirana) and len(mirana.memory) == 3)
    assert mirana._nudges_in_row == 0


def test_volume_and_memory_commands(mirana):
    mirana._on_command("volume", "80")
    assert mirana.voice.volume == pytest.approx(0.8)
    mirana._on_command("volume", "nie číslo")
    assert mirana.voice.volume == pytest.approx(0.8)
    mirana._on_command("quit")
    assert isinstance(mirana._events.get_nowait(), Quit)
