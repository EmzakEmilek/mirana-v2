"""Protokol HUD/okno: kazdy typ spravy ma prijemcu, okno posiela len zname prikazy, prikazy len z localhostu."""

import json
import re
import shutil
from types import SimpleNamespace

import pytest

from mirana import protocol, settings
from mirana.config import BASE_DIR, CONFIG_PATH, PERSONA_PATH
from mirana.outputs.overlay import Overlay

HUD_SRC = (BASE_DIR / "overlay" / "index.html").read_text(encoding="utf-8")
HUD2_SRC = (BASE_DIR / "overlay" / "v2.html").read_text(encoding="utf-8")
GUI_SRC = (BASE_DIR / "ui" / "control.py").read_text(encoding="utf-8")
MIRANA_SRC = "".join(p.read_text(encoding="utf-8") for p in (BASE_DIR / "mirana").rglob("*.py"))


def test_every_event_has_a_receiver():
    hud = set(re.findall(r"case '(\w+)':", HUD_SRC))
    hud2 = set(re.findall(r"case '(\w+)':", HUD2_SRC))
    assert protocol.HUD <= hud2, protocol.HUD - hud2      # aj HUD v2 spracuje vsetko
    assert hud2 <= set(protocol.EVENTS)
    gui = set(re.findall(r'kind == "(\w+)"', GUI_SRC)) - {"connected", "disconnected", "diagnostics"}  # vnutorne udalosti okna
    assert protocol.HUD <= hud, protocol.HUD - hud
    assert protocol.GUI <= gui, protocol.GUI - gui
    assert set(protocol.EVENTS) == protocol.HUD | protocol.GUI
    assert hud <= set(protocol.EVENTS) and gui <= set(protocol.EVENTS)  # ziadne mrtve vetvy


def test_gui_sends_only_known_commands():
    sources = GUI_SRC + (BASE_DIR / "ui" / "settings_window.py").read_text(encoding="utf-8")
    sent = set(re.findall(r'_send\("(\w+)"', sources))
    assert sent and sent <= protocol.COMMANDS
    handled = set(re.findall(r'cmd == "(\w+)"', MIRANA_SRC))
    assert protocol.COMMANDS <= handled


def test_event_validates_fields():
    assert protocol.event("state", state="idle") == {"type": "state", "state": "idle"}
    assert protocol.event("game_fx", kind="death", text="x", detail="")["kind"] == "death"
    with pytest.raises(ValueError):
        protocol.event("state")
    with pytest.raises(ValueError):
        protocol.event("neexistuje")


@pytest.fixture
def overlay(config):
    ov = Overlay(config)
    ov.commands = []
    ov.on_command = lambda cmd, text: ov.commands.append((cmd, text))
    return ov


def ws(host, origin=None):
    headers = {"Origin": origin} if origin else {}
    return SimpleNamespace(remote_address=(host, 5000), request=SimpleNamespace(headers=headers))


def test_overlay_methods_build_valid_events(overlay):
    overlay.telemetry(location="Watson", quest="Jízda", combat=True, wanted=2, critical=False, deaths=1)
    overlay.state("idle")
    overlay.search(None, ["hľadám"])
    overlay.answer_append("Veta.", duration_sec=1.0)
    overlay.info(model="m", effort="low")
    assert overlay._last["telemetry"]["wanted"] == 2
    assert set(overlay._last) == {"telemetry", "state", "info", "hud"}  # jednorazove spravy sa nepamataju
    with pytest.raises(TypeError):
        overlay.telemetry("Watson", "Jízda")  # len s menami poli


def test_commands_only_from_local_window(overlay):
    cmd = json.dumps({"type": "command", "cmd": "ask", "text": "ahoj"})
    overlay._on_message(ws("127.0.0.1"), cmd)
    overlay._on_message(ws("192.168.1.20"), cmd)                        # notebook s OBS
    overlay._on_message(ws("127.0.0.1", "https://zla-stranka.com"), cmd)  # prehliadac na tomto PC
    overlay._on_message(ws("127.0.0.1"), json.dumps({"type": "command", "cmd": "format_c"}))
    overlay._on_message(ws("127.0.0.1"), "nie json")
    assert overlay.commands == [("ask", "ahoj")]


def test_settings_roundtrip_keeps_comments(tmp_path, monkeypatch):
    cfg, persona = tmp_path / "config.yaml", tmp_path / "persona.md"
    shutil.copy(CONFIG_PATH, cfg)
    shutil.copy(PERSONA_PATH, persona)
    monkeypatch.setattr(settings, "CONFIG_PATH", cfg)
    monkeypatch.setattr(settings, "PERSONA_PATH", persona)
    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backup")
    original = cfg.read_text(encoding="utf-8")
    data = settings.load_editable()
    settings.save(data)
    assert cfg.read_text(encoding="utf-8") == original
    data["audio"]["volume"] = 123
    settings.save(data)
    assert "volume: 123" in cfg.read_text(encoding="utf-8")
    assert (tmp_path / "backup" / "config.yaml.bak").read_text(encoding="utf-8") == original
    settings.save_persona("# Persona\n\ntext\n\n\n")
    assert persona.read_text(encoding="utf-8") == "# Persona\n\ntext\n"
