"""Cisto logicke casti: bez siete, zvuku a modelu."""

import json
from datetime import date
from types import SimpleNamespace

import pytest

from mirana import store
from mirana.llm.brain import SentenceSplitter
from mirana.features.highlights import fmt_offset, parse_uptime
from mirana.safety import Safety
from mirana.inputs.game_state import Snapshot, completed_quests, detect_events, event_text, telemetry_line
from mirana.inputs.twitch_chat import channel_name, clean_text, parse_privmsg


# --- store -------------------------------------------------------------------------------------

def test_write_json_atomic_and_read_back(tmp_path):
    path = tmp_path / "sub" / "x.json"
    assert store.write_json(path, {"a": "ľščť"})
    assert store.read_json(path) == {"a": "ľščť"}
    assert not list(path.parent.glob("*.tmp"))


def test_read_json_corrupted_returns_default(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{nedokoncene", encoding="utf-8")
    assert store.read_json(path, {"ok": 1}) == {"ok": 1}


def test_append_jsonl(tmp_path):
    path = tmp_path / "log.jsonl"
    store.append_jsonl(path, {"n": 1})
    store.append_jsonl(path, {"n": 2})
    assert [json.loads(x)["n"] for x in path.read_text(encoding="utf-8").splitlines()] == [1, 2]


def test_daily_json_rolls_over(tmp_path):
    path = tmp_path / "d.json"
    path.write_text(json.dumps({"day": "2000-01-01", "usd": 5.0}), encoding="utf-8")
    d = store.DailyJson(path, {"usd": 0.0})
    assert d.data == {"day": date.today().isoformat(), "usd": 0.0}
    d.data["usd"] = 1.5
    d.save()
    assert store.DailyJson(path, {"usd": 0.0}).data["usd"] == 1.5
    d.data["day"] = "2000-01-01"  # "polnoc"
    d.roll()
    assert d.data["usd"] == 0.0


def test_budget_counts_and_caps(config, data_dir):
    from mirana.budget import Budget
    config["limits"]["daily_usd_cap"] = 0.003
    b = Budget(config)
    usage = SimpleNamespace(input_tokens=100, output_tokens=100, cache_read_input_tokens=0,
                            cache_creation_input_tokens=0)
    cost = b.add("claude-sonnet-5-5", usage)
    assert cost == pytest.approx((100 * 2.0 + 100 * 10.0) / 1e6)
    assert not b.exceeded()
    for _ in range(2):
        b.add("claude-sonnet-5-5", usage)
    assert b.exceeded()
    assert Budget(config).spent == pytest.approx(b.spent)  # prezije restart


# --- vety -------------------------------------------------------------------------------------

def feed_all(chunks):
    s = SentenceSplitter()
    out = []
    for c in chunks:
        out += s.feed(c)
    rest = s.flush()
    return out + ([rest] if rest else [])


def test_splitter_streams_sentences():
    out = feed_all(["Padre je fixer z Heyw", "oodu. Kedysi bol medzi Valentinos. A", "ko kňaz."])
    assert out == ["Padre je fixer z Heywoodu.", "Kedysi bol medzi Valentinos.", "Ako kňaz."]


def test_splitter_short_first_sentence_joined():
    assert feed_all(["Nie. To fakt nie je dobrý nápad. Ide sa."])[0] == "Nie. To fakt nie je dobrý nápad."


def test_splitter_keeps_abbreviations():
    out = feed_all(["Zbraň je napr. Mk. 2 verzia od Arasaka. Dobrá vec."])
    assert out[0].startswith("Zbraň je napr. Mk. 2 verzia")


# --- hra ----------------------------------------------------------------------------------------

def snap(**data):
    return Snapshot({"in_game": True, **data})


def test_detect_death_and_critical():
    assert detect_events(snap(hp=40), snap(hp=0), 30, 10) == ["death"]
    assert detect_events(snap(hp=40), snap(hp=8), 30, 10) == ["hp_critical"]
    assert detect_events(snap(hp=40), snap(hp=25), 30, 10) == ["hp_low"]
    assert detect_events(None, snap(hp=0), 30, 10) == []
    assert detect_events(snap(hp=40), Snapshot({"in_game": False, "hp": 0}), 30, 10) == []


def test_detect_level_wanted_combat():
    events = detect_events(snap(level=5, wanted=0), snap(level=6, wanted=2, combat=True), 30, 10)
    assert events == ["wanted_up", "level_up", "combat_start"]
    assert detect_events(snap(level=0), snap(level=6), 30, 10) == []  # prvy snimok po nacitani nie je level up


def test_pseudo_quest_is_not_new_quest():
    prev = snap(quest="Jízda")
    assert detect_events(prev, snap(quest="Neobjevené"), 30, 10) == []
    assert detect_events(snap(quest="Neobjevené"), snap(quest="Jízda"), 30, 10, last_quest="Jízda") == []
    assert detect_events(prev, snap(quest="Nový quest"), 30, 10) == ["quest_changed"]


def test_completed_quests_and_text():
    prev = snap(story={"main_done": [{"id": "q001", "title": "Prvý"}]})
    cur = snap(story={"main_done": [{"id": "q001", "title": "Prvý"}, {"id": "q003", "title": "Pochôdzka"}]})
    assert completed_quests(prev, cur) == ["Pochôdzka"]
    assert event_text("quest_completed", cur, prev) == "Erik dokončil hlavný quest Pochôdzka"
    assert event_text("wanted_up", snap(wanted=3)) == "polícia ho hľadá, už 3 hviezdy"


def test_telemetry_line_skips_empty():
    line = telemetry_line(snap(hp=80, district="Watson", subdistrict="Kabuki", money=1200))
    assert line.startswith("[HRA] zdravie 80 %")
    assert "Watson, Kabuki" in line and "1200 eddies" in line
    assert "None" not in line


# --- ostatne ------------------------------------------------------------------------------------

def test_uptime_parsing():
    assert parse_uptime("1 hour, 2 minutes, 3 seconds") == 3723
    assert parse_uptime("emzakemil is offline") is None
    assert parse_uptime("") is None
    assert fmt_offset(3723) == "1:02:03"


def test_safety(config):
    s = Safety(config)
    assert s.check("Padre je fixer.") is None
    assert s.check("napíš mi na jano@example.com") == "email"
    assert s.check("pozri www.example.com") == "odkaz"


def test_twitch_privmsg():
    m = parse_privmsg("@badges=moderator/1,subscriber/12;display-name=Kubo :kubo!kubo@kubo.tmi.twitch.tv "
                      "PRIVMSG #emzakemil :ahoj Mirana")
    assert (m.login, m.nick, m.text, m.badges) == ("kubo", "Kubo", "ahoj Mirana", ("moderator", "subscriber"))
    assert parse_privmsg(":tmi.twitch.tv PING") is None
    assert channel_name("https://www.twitch.tv/Emzakemil/") == "emzakemil"
    assert clean_text("pozri https://x.y a | b", 100) == "pozri [odkaz] a / b"


def test_ptt_keys():
    from pynput import keyboard, mouse

    from mirana.inputs.ptt import key_label, parse_key
    assert parse_key("mouse_x1") == mouse.Button.x1
    assert parse_key("F11") == keyboard.Key.f11
    assert parse_key("") is None
    assert key_label("mouse_x2") == "predné bočné tlačidlo myši"
    with pytest.raises(ValueError):
        parse_key("neexistuje")


def test_loaded_save_is_not_progress():
    story = lambda *ids: {"main_done": [{"id": i, "title": i} for i in ids]}
    assert detect_events(snap(level=1), snap(level=7), 30, 10) == []                  # skok o 6 levelov = save
    assert detect_events(snap(level=6), snap(level=7), 30, 10) == ["level_up"]
    many = detect_events(snap(story=story()), snap(story=story("q001", "q002", "q003")), 30, 10)
    assert "quest_completed" not in many                                              # 3 naraz = save
    one = detect_events(snap(story=story("q001")), snap(story=story("q001", "q003")), 30, 10)
    assert "quest_completed" in one


def test_events_ignored_right_after_load(tmp_path, config, monkeypatch):
    import json as _json
    import mirana.inputs.game_state as gs
    path = tmp_path / "state.json"
    config["game_state"].update(enabled=True, json_path=str(path))
    seen = []
    game = gs.GameState(config, on_event=lambda name, s, text: seen.append(name))
    clock = [1000.0]
    monkeypatch.setattr(gs.time, "time", lambda: clock[0])
    def write(**data):
        path.write_text(_json.dumps({"in_game": True, "hp": 100, **data}), encoding="utf-8")
        game._mtime = 0                                    # novy zapis (mtime sa v teste nemusi zmenit)
        game._tick()
    write(in_game=False)                                   # menu
    write(hp=100, level=6)                                 # nacitany save
    clock[0] += 5
    write(hp=0, level=6)                                   # 5 s po nacitani: ignorovane
    assert seen == []
    clock[0] += 40
    write(hp=100, level=6)
    write(hp=0, level=6)                                   # neskor: skutocna smrt
    assert seen == ["death"]


def test_cache_breakpoint_on_stored_history(config, monkeypatch):
    """Cache bod je na poslednej sprave pamate (rovnaka pri dalsej otazke), nie na novej otazke s [HRA]."""
    import mirana.llm.brain as brain_mod
    monkeypatch.setattr(brain_mod, "create_stt", lambda cfg: None)
    b = brain_mod.Brain(config, None, wiki=SimpleNamespace(enabled=False))
    memory = [{"role": "user", "content": "[ERIK] kto je Padre?"}, {"role": "assistant", "content": "Fixer."}]
    msgs = b._messages(memory, "[HRA] zdravie 80 %\n[ERIK] a kde je?")
    assert msgs[1]["content"] == [{"type": "text", "text": "Fixer.", "cache_control": {"type": "ephemeral"}}]
    assert "cache_control" not in msgs[2]["content"][0]
    assert memory[1]["content"] == "Fixer."                     # pamat sa nemeni
    first = b._messages([], "[ERIK] ahoj", image_b64="QUJD")
    assert [c["type"] for c in first[0]["content"]] == ["image", "text"] and len(first) == 1


class _FakeStream:
    """Napodobenina streamu Anthropic SDK: udalosti a finalna sprava."""
    def __init__(self, events, message):
        self.events, self.message = events, message
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def __iter__(self):
        return iter(self.events)
    def get_final_message(self):
        return self.message


def test_screen_tool_round(config, monkeypatch):
    """Model zavola nastroj obrazovka -> Brain posle snimku ako vysledok a model potom odpovie."""
    import mirana.llm.brain as brain_mod
    monkeypatch.setattr(brain_mod, "create_stt", lambda cfg: None)
    usage = SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    tool_block = SimpleNamespace(type="tool_use", name="obrazovka", id="t1", input={})
    first = _FakeStream([SimpleNamespace(type="content_block_start", content_block=tool_block)],
                        SimpleNamespace(content=[tool_block], stop_reason="tool_use", usage=usage, model="m"))
    second = _FakeStream([SimpleNamespace(type="text", text="Vidím Maelstrom gangera pri aute.")],
                         SimpleNamespace(content=[], stop_reason="end_turn", usage=usage, model="m"))
    calls = []
    def stream(**kwargs):
        calls.append(kwargs)
        return first if len(calls) == 1 else second
    b = brain_mod.Brain(config, SimpleNamespace(add=lambda m, u: 0.0), wiki=SimpleNamespace(enabled=False))
    b.anthropic_client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    b.screen = lambda: "SNIMKA"
    looked = []
    answer = b.ask_stream("[ERIK] čo tu vidíš?", None, [], on_sentence=lambda s: None, on_look=lambda: looked.append(1))
    assert [t["name"] for t in calls[0]["tools"]] == ["obrazovka"]
    result = calls[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["content"][0]["source"]["data"] == "SNIMKA"
    assert looked == [1] and answer.text == "Vidím Maelstrom gangera pri aute."
    calls.clear()
    b.ask_stream("[ERIK] čo je toto?", None, [], on_sentence=lambda s: None, image_b64="UZ")   # snimka uz je pri otazke
    assert "tools" not in calls[0]


def test_hra_line_quest_and_no_grenades():
    s = snap(hp=80, grenade_charges=2, grenade_max=2, heal_charges=1, heal_max=2, quest="Neobjevené",
             quest_id="generic_sts_quest")
    line = telemetry_line(s)
    assert "granát" not in line and "liečenie 1 z 2" in line
    assert "neobjavené miesto" in line
