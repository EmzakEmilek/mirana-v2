"""Orchestracia Mirany s nahradnymi komponentmi: otazka, barge-in, mute, urgentna hlaska, pripomienka, rozpocet.

Udalosti z fronty spracuva rovnaka funkcia ako hlavna slucka (_handle_event), len v teste.
"""

import json
import queue
import time

import pytest

import mirana.app as main
from mirana.features import notes as notes_mod
from mirana.features import vision as vision_mod
from mirana.features.idle import IdleNudge
from mirana.events import Quit
from mirana.inputs.game_state import Snapshot
from tests import fakes


@pytest.fixture
def mirana(config, data_dir, monkeypatch):
    for name, fake in (("Brain", fakes.FakeBrain), ("Voice", fakes.FakeVoice), ("Fillers", fakes.FakeFillers),
                       ("Overlay", fakes.RecordingOverlay), ("PushToTalk", fakes.FakePtt),
                       ("GameState", fakes.FakeGame), ("TwitchChat", fakes.FakeChat)):
        monkeypatch.setattr(main, name, fake)
    monkeypatch.setattr(notes_mod, "NOTES_PATH", data_dir / "logs" / "poznamky.md")
    monkeypatch.setattr(vision_mod, "capture", lambda *a, **kw: "SNIMKA")  # nikdy skutocna obrazovka
    config["idle_nudge"] = {"enabled": True, "after_min": 10, "max_in_row": 2}
    config["wiki"]["enabled"] = False  # bez siete
    return main.Mirana(config, "20261002-200000")


def feature(m, cls):
    return next(f for f in m.features if isinstance(f, cls))


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
    mirana._on_game_event("death", Snapshot({"in_game": True, "hp": 0, "district": "Watson"}), "Erik práve zomrel")
    assert mirana._events.get_nowait().text == "Erik práve zomrel (dnes už 1. smrť)"
    assert mirana.overlay.of("game_fx")[-1] == {"type": "game_fx", "kind": "death", "text": "FLATLINE #1", "detail": "Watson"}
    assert mirana.highlights.path.read_text(encoding="utf-8").count("SMRŤ") == 1


def test_idle_nudge_rules(mirana):
    nudge = feature(mirana, IdleNudge)
    nudge.tick()
    assert mirana.brain.asked == []                       # este neubehlo 10 minut
    nudge.since = time.time() - 11 * 60
    mirana.game.current = Snapshot({"in_game": True, "combat": True})
    nudge.tick()
    assert mirana.brain.asked == []                       # v boji nie
    mirana.game.current = None
    for _ in range(3):
        nudge.last = 0
        nudge.tick()
        pump(mirana, lambda: idle(mirana))
    assert sum("[IDLE]" in q for q in mirana.brain.asked) == 2  # max_in_row, potom caka na Erika
    mirana._handle_typed("som tu")
    pump(mirana, lambda: idle(mirana) and len(mirana.memory) == 3)
    assert nudge.in_row == 0


def test_volume_and_memory_commands(mirana):
    mirana._on_command("volume", "80")
    assert mirana.voice.volume == pytest.approx(0.8)
    mirana._on_command("volume", "nie číslo")
    assert mirana.voice.volume == pytest.approx(0.8)
    mirana._on_command("quit")
    assert isinstance(mirana._events.get_nowait(), Quit)


def test_context_lines_in_fixed_order_and_structured_log(mirana):
    mirana.game.line = lambda: "[HRA] zdravie 80 %"
    mirana.chat.line = lambda: "[CHAT] Kubo: ahoj"
    mirana._handle_typed("Mirana, čo je toto za auto? A koľko krát som dnes zomrel?")
    pump(mirana, lambda: len(mirana.memory) == 1 and idle(mirana))
    lines = mirana.brain.asked[-1].split("\n")
    assert [x.split("]")[0] + "]" for x in lines] == ["[HRA]", "[STREAM]", "[OBRAZOVKA]", "[CHAT]", "[ERIK]"]
    assert mirana.overlay.of("scan")
    record = json.loads(mirana.conversation.path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["zdroj"] == "typed" and record["otazka"].startswith("Mirana, čo je toto")
    assert set(record["kontext"]) == {"HRA", "STREAM", "OBRAZOVKA", "CHAT"} and record["obrazovka"] is True
    assert mirana.memory.as_messages()[0]["content"] == "[ERIK] Mirana, čo je toto za auto? A koľko krát som dnes zomrel?"


def test_note_saved(mirana, data_dir):
    mirana._handle_typed("Mirana, zapíš si do logu, že HUD je moc veľký")
    pump(mirana, lambda: len(mirana.memory) == 1 and idle(mirana))
    assert "HUD je moc veľký" in (data_dir / "logs" / "poznamky.md").read_text(encoding="utf-8")


def test_feature_failure_does_not_stop_answer(mirana):
    def broken(turn):
        raise RuntimeError("chyba vo funkcii")
    feature(mirana, IdleNudge).context = broken
    mirana._handle_typed("ahoj")
    pump(mirana, lambda: len(mirana.memory) == 1 and idle(mirana))


def test_hud_test_command(mirana):
    mirana._on_command("hud_test", "level")
    pump(mirana, lambda: mirana.overlay.of("game_fx"), timeout=2)
    assert mirana.overlay.of("game_fx")[-1]["kind"] == "level_up"


def test_memory_edit_command(mirana):
    from mirana.features.longterm import LongTermFeature
    memory = feature(mirana, LongTermFeature).memory
    memory.data["erik"]["facts"] = ["hrá za Corpo", "má psa"]
    mirana._on_command("memory_edit", json.dumps({"facts": ["hrá za Nomáda"], "notes": {}}))
    assert memory.data["erik"]["facts"] == ["hrá za Nomáda"]
    assert "hrá za Nomáda" in memory.block



def test_hud_v2_stages_marks_and_viewer_card(mirana):
    mirana.longterm.data["viewers"] = {"kubo_sk": {"nick": "Kubo_SK", "visits": 3, "badges": ["subscriber"],
                                                   "first_seen": "2026-09-30", "notes": []}}
    mirana.brain.reply = ["Kubo_SK, vitaj späť v Night City, kurva."]
    ask_by_voice(mirana, "pozdrav Kuba")
    pump(mirana, lambda: len(mirana.memory) == 1 and idle(mirana))
    stages = [(e["name"], e["status"]) for e in mirana.overlay.of("stage")]
    assert stages == [("prepis", "active"), ("prepis", "done"), ("model", "active"), ("model", "done")]
    append = mirana.overlay.of("answer_append")[0]
    text = append["text"]
    assert [(text[a:b], kind) for a, b, kind in append["marks"]] == [
        ("Kubo_SK", "nick"), ("Night City", "name"), ("kurva", "swear")]
    assert append["viewers"] == [{"nick": "Kubo_SK", "badge": "SUB", "visits": 3, "since": "2026-09-30"}]
