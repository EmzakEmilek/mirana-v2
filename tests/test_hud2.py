"""HUD v2: zvyraznene slova, pasma hlasu, prepinanie verzie, radio, stvrt, karta cielu."""

from types import SimpleNamespace

import numpy as np
import pytest

from mirana.features.hud import Hud, mark_sentence
from mirana.inputs.game_state import Snapshot, target_info
from mirana.outputs.overlay import INDEX_PATH, V2_PATH, Overlay
from mirana.spectrum import N_BANDS, bands
from tests.fakes import RecordingOverlay

NAMES = {"padre", "heywood", "night city", "jackie", "arasaka", "valentinos"}


def is_name(phrase: str) -> bool:
    from mirana.features.wiki import _norm
    return _norm(phrase) in NAMES


def spans(sentence, marks):
    return [(sentence[a:b], kind) for a, b, kind in marks]


def test_marks_names_declined_and_swears():
    s = "Padre je fixer z Heywoodu, choď za Jackiem, Arasaka má hovno."
    marks, cards = mark_sentence(s, is_name, {})
    assert spans(s, marks) == [("Padre", "name"), ("Heywoodu", "name"), ("Jackiem", "name"),
                               ("Arasaka", "name"), ("hovno", "swear")]
    assert cards == []


def test_marks_lowercase_words_are_not_names():
    s = "padre a heywood píšem malým, nesvietia."
    assert mark_sentence(s, is_name, {})[0] == []


def test_marks_viewers_declined_and_cards():
    viewers = {"kubo_sk": {"nick": "Kubo_SK", "visits": 3, "badges": ["moderator", "subscriber"], "first_seen": "2026-09-30"},
               "lara": {"nick": "Lara", "visits": 1, "badges": []}}
    s = "Kubovi a Lare pošli pozdrav, kubo_sk to aj tak vidí."
    marks, cards = mark_sentence(s, is_name, viewers)
    assert spans(s, marks) == [("Kubovi", "nick"), ("Lare", "nick"), ("kubo_sk", "nick")]
    assert cards == [{"nick": "Kubo_SK", "badge": "MOD", "visits": 3, "since": "2026-09-30"},
                     {"nick": "Lara", "badge": "", "visits": 1, "since": ""}]


def test_marks_do_not_overlap():
    viewers = {"jackie": {"nick": "Jackie", "visits": 2, "badges": []}}  # divak s menom postavy
    s = "Jackie, kurva, Night City čaká."
    marks, _ = mark_sentence(s, is_name, viewers)
    assert spans(s, marks) == [("Jackie", "nick"), ("kurva", "swear"), ("Night City", "name")]
    covered = [i for a, b, _ in marks for i in range(a, b)]
    assert len(covered) == len(set(covered))


def test_bands_silence_and_tone():
    rate = 48000
    assert bands(np.zeros(2400, np.int16), rate) == [0.0] * N_BANDS
    t = np.arange(2400) / rate
    low = bands((np.sin(2 * np.pi * 200 * t) * 12000).astype(np.int16), rate)
    high = bands((np.sin(2 * np.pi * 5000 * t) * 12000).astype(np.int16), rate)
    assert len(low) == N_BANDS and all(0 <= v <= 1 for v in low + high)
    assert int(np.argmax(low)) < 4 and int(np.argmax(high)) > 8
    assert bands(np.zeros(10, np.int16), rate) == [0.0] * N_BANDS   # prilis kratky kus


def test_page_by_settings_and_override(config):
    config["overlay"]["hud"] = "v2"
    ov = Overlay(config)
    assert ov.page_path("/") == V2_PATH and ov.page_path("/?hud=1") == INDEX_PATH
    assert ov.page_path("/index.html?demo") == V2_PATH and ov.page_path("/nieco") is None
    config["overlay"]["hud"] = "v1"
    ov = Overlay(config)
    assert ov.page_path("/") == INDEX_PATH and ov.page_path("/?hud=2") == V2_PATH and ov.page_path("/v2.html") == V2_PATH
    assert ov._last["hud"] == {"type": "hud", "version": "v1"}


def test_target_info():
    hostile = Snapshot({"target": {"name": "Maelstrom Ganger", "hostile": True, "level": 8, "hp": 64}})
    assert target_info(hostile) == {"name": "Maelstrom Ganger", "status": "nepriateľ", "level": 8, "hp": 64, "recent": False}
    dead = Snapshot({"target": {"name": "Royce", "dead": True, "boss": True, "level": 20, "hp": 0, "recent": True}})
    assert target_info(dead) == {"name": "Royce", "status": "mŕtvy", "level": None, "hp": None, "recent": True}
    car = Snapshot({"target": {"name": "Quadra Type-66", "kind": "vehicle"}})
    assert target_info(car)["status"] == "vozidlo"
    assert target_info(None) is None and target_info(Snapshot({})) is None


@pytest.fixture
def hud(config):
    app = SimpleNamespace(config=config, overlay=RecordingOverlay(config), highlights=SimpleNamespace(deaths=2),
                          game=SimpleNamespace(line=lambda: None, current=None), wiki=SimpleNamespace(has_name=lambda p: False),
                          longterm=None)
    return Hud(app)


def snap(**data):
    return Snapshot({"in_game": True, "district": "Watson", "subdistrict": "Kabuki", **data})


def test_radio_card_only_on_change(hud):
    hud.on_snapshot(snap(radio="89.7 Growl FM", song="Never Fade Away"))   # skladba hrala uz pri starte
    assert hud.app.overlay.of("game_fx") == []
    hud.on_snapshot(snap(radio="89.7 Growl FM", song="Never Fade Away"))
    hud.on_snapshot(snap(radio="89.7 Growl FM", song="Chippin' In"))
    assert hud.app.overlay.of("game_fx") == [{"type": "game_fx", "kind": "radio", "text": "Chippin' In", "detail": "89.7 Growl FM"}]
    hud.on_snapshot(snap())                                                # vystupil z auta
    hud.on_snapshot(snap(radio="89.7 Growl FM", song="Chippin' In"))       # nastupil znova -> karta znova
    assert len(hud.app.overlay.of("game_fx")) == 2


def test_telemetry_has_time_weather_money(hud):
    hud.on_snapshot(snap(money=12400, time="23:40", weather="RainHeavy", hp=80))
    t = hud.app.overlay.of("telemetry")[-1]
    assert (t["money"], t["time"], t["location"], t["deaths"]) == (12400, "23:40", "Watson, Kabuki", 2)
    assert t["weather"] and t["weather"] != "RainHeavy"                    # slovensky nazov pocasia


def test_district_and_quest_cards(hud):
    hud.on_game_event("district_change", snap(time="23:40"), "Erik prišiel do štvrte Watson, Kabuki")
    hud.on_game_event("quest_completed", snap(), "Erik dokončil hlavný quest Pochôdzka")
    fx = hud.app.overlay.of("game_fx")
    assert fx[0] == {"type": "game_fx", "kind": "district", "text": "Watson", "detail": "Kabuki · 23:40"}
    assert fx[1]["detail"] == "Pochôdzka"
