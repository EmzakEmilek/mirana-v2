"""Schema nastaveni, nacitanie configu, uprava pamate z okna, aktualizacia modu, diagnostika, okno Nastavenia."""

import gc
import io
import json

import pytest

from mirana import config as config_mod
from mirana import diagnostics, schema
from mirana.budget import PRICES
from mirana.config import CONFIG_PATH
from mirana.features.longterm import apply_edit


def test_real_config_is_valid_and_complete():
    import yaml
    config_mod.load_config()
    assert config_mod.problems == []
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert set(schema._leaves(raw)) == set(schema.BY_KEY)  # kazde nastavenie je v config.yaml aj v scheme


def test_missing_values_get_defaults():
    cfg, problems = schema.resolve({"audio": {"ptt_key": "f4"}})
    assert problems == []
    assert cfg["llm"]["model"] == "claude-sonnet-5-5" and cfg["audio"]["ptt_key"] == "f4"
    assert cfg["tts"]["effects"]["params"] == {}


def test_bad_values_fall_back_with_problem():
    raw = {"overlay": {"port": "osemdesiat"}, "tts": {"rate": "rychlo"}, "llm": {"effort": "max"},
           "audio": {"ptt_key": "neexistuje"}, "memory": {"max_exchanges": 0}, "nieco": {"preklep": 1}}
    cfg, problems = schema.resolve(raw)
    assert cfg["overlay"]["port"] == 8080 and cfg["tts"]["rate"] == "0%" and cfg["llm"]["effort"] == "low"
    text = "\n".join(problems)
    for key in ("overlay.port", "tts.rate", "llm.effort", "audio.ptt_key", "memory.max_exchanges", "nieco.preklep"):
        assert key in text


def test_cross_rules():
    cfg, problems = schema.resolve({"game_state": {"hp_low_threshold": 10, "hp_critical_threshold": 20},
                                    "audio": {"ptt_key": "f4", "panic_mute_key": "f4"}})
    assert any("Kritické HP" in p for p in problems) and any("rôzne" in p for p in problems)


def test_broken_yaml_does_not_crash(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("audio: [nedokoncene\n", encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert cfg["overlay"]["port"] == 8080 and "nedá prečítať" in config_mod.problems[0]
    config_mod.load_config()


def test_schema_lists_match_code():
    from mirana.outputs.voice_fx import PRESET_LABELS
    assert set(schema.EFFECTS) == set(PRESET_LABELS)
    assert set(schema.MODELS) <= set(PRICES)
    for item in schema.SETTINGS:
        assert item.tab in ("",) + schema.TABS
        if isinstance(item, schema.S):
            assert item.error(item.default) is None, item.key  # predvolena hodnota je platna


# --- pamat z okna ----------------------------------------------------------------------------------

def test_apply_edit():
    data = {"erik": {"facts": ["a", "b"]}, "viewers": {"kubo": {"visits": 3, "notes": ["x"]}}, "processed": {"s": [1, 2]}}
    out = apply_edit(json.loads(json.dumps(data)), {"facts": ["a", " "], "notes": {"kubo": ["nová"]}})
    assert out["erik"]["facts"] == ["a"] and out["viewers"]["kubo"] == {"visits": 3, "notes": ["nová"]}
    wiped = apply_edit(data, {"forget_all": True})
    assert wiped["viewers"] == {} and wiped["processed"] == {"s": [1, 2]}


# --- mod v hre ---------------------------------------------------------------------------------------

@pytest.fixture
def game(tmp_path, monkeypatch):
    import mirana.inputs.game_state as gs
    source = tmp_path / "repo"
    source.mkdir()
    (source / "init.lua").write_text("local VERSION = 6\n", encoding="utf-8")
    game_dir = tmp_path / "game"
    (game_dir / "bin" / "x64" / "plugins" / "cyber_engine_tweaks").mkdir(parents=True)
    monkeypatch.setattr(gs, "MOD_SOURCE", source)
    return gs, game_dir


def test_mod_updates_only_when_game_is_off(game, monkeypatch):
    gs, game_dir = game
    installed = game_dir / gs.MOD_SUBDIR / "init.lua"
    monkeypatch.setattr(gs, "game_running", lambda: True)
    assert "po vypnutí hry" in gs.update_mod(game_dir) and not installed.exists()
    monkeypatch.setattr(gs, "game_running", lambda: False)
    assert "→ v6" in gs.update_mod(game_dir) and gs.mod_version(installed) == 6
    assert gs.update_mod(game_dir) is None  # uz aktualny


def test_diagnostics_keys_never_show_values(monkeypatch, config):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-tajne-123")
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    check = diagnostics._keys(config)[0]
    assert not check.ok and "AZURE_SPEECH_KEY" in check.detail and "tajne" not in check.detail


# --- okno Nastavenia (skutocne Tk okno, skryte) ---------------------------------------------------------

@pytest.fixture(scope="module")
def tk_app():
    """Jeden Tk koren na cely modul — druhy Tk v tom istom procese na Windows nevie najst tk.tcl."""
    ctk = pytest.importorskip("customtkinter")

    class FakeApp(ctk.CTk):
        connected = False

        def _send(self, *a, **k):
            return False

        def on_settings_saved(self, restart):
            pass
    try:
        app = FakeApp()
    except Exception as e:  # bez obrazovky
        pytest.skip(f"Tk nejde: {e}")
    app.withdraw()
    yield app
    app.destroy()
    gc.collect()


@pytest.fixture
def window(tk_app):
    from ui.settings_window import SettingsWindow
    w = SettingsWindow(tk_app)
    w.withdraw()
    tk_app.update()
    yield w
    w.destroy()
    # Tk objekty (pisma) upratat hned v hlavnom vlakne — inak ich GC zmaze neskor z vlakna Mirany
    # v inom teste a tkinter tam zamrzne (caka na hlavne vlakno)
    gc.collect()


def test_settings_window_roundtrip_without_changes(window):
    from mirana import settings
    from ui.settings_window import _put_path
    values = window.collect()
    current = config_mod.load_config()
    assert {k: v for k, v in values.items() if v != schema.get(current, k)} == {}
    tree = settings.load_editable()
    for key, value in values.items():
        _put_path(tree, key, value)
    buf = io.StringIO()
    settings._yaml().dump(tree, buf)
    assert buf.getvalue() == CONFIG_PATH.read_text(encoding="utf-8")  # ulozenie bez zmien nic nezmeni


def test_settings_window_rejects_bad_input(window):
    port = window.fields["overlay.port"][1].__defaults__[0]
    port.set("abc")
    with pytest.raises(ValueError, match="nie je číslo"):
        window.collect()
    port.set("80")
    with pytest.raises(ValueError, match="najmenej 1024"):
        window.collect()


# --- archiv logov ------------------------------------------------------------------------------------

def test_archive_old_logs(tmp_path):
    import zipfile
    from datetime import date

    from mirana.features.archive import archive_logs
    logs = tmp_path / "logs"
    logs.mkdir()
    names = [f"mirana-2026090{d}-200000.log" for d in range(1, 8)] + ["rozhovor-20260901-200000.jsonl",
                                                                      "strih-20260901.md", "poznamky.md",
                                                                      "mirana-20261001-200000.log"]
    for name in names:
        (logs / name).write_text(f"obsah {name}", encoding="utf-8")
    done = archive_logs(logs, 14, today=date(2026, 10, 2))
    # starsie ako 14 dni ide do archivu, okrem 4 najnovsich sessions (5.-7.9. a 1.10.)
    assert "mirana-20260901-200000.log" in done and "strih-20260901.md" in done
    assert "mirana-20260907-200000.log" not in done            # medzi 4 poslednymi sessions
    assert (logs / "poznamky.md").exists() and (logs / "mirana-20261001-200000.log").exists()
    with zipfile.ZipFile(logs / "archive" / "2026-09.zip") as z:
        assert z.read("mirana-20260901-200000.log").decode() == "obsah mirana-20260901-200000.log"
    assert not (logs / "mirana-20260901-200000.log").exists()
    assert archive_logs(logs, 14, today=date(2026, 10, 2)) == []  # druhy beh nic nerobi
