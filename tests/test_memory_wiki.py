"""Wiki (bez siete: index z docasneho suboru) a dlhodoba pamat (subory v docasnom priecinku)."""

import json
from datetime import date
from types import SimpleNamespace

import pytest

import core.wiki as wiki_mod
from core.longterm import LongTermMemory
from core.wiki import Wiki, clean_wikitext, infobox_facts

TITLES = ["Padre", "Sebastian Ibarra", "The Mox", "Mox (shard)", "Mox", "Makigai Tanishi T400", "Night City",
          "Jackie Welles", "Arasaka Corporation", "List of weapons", "Padre/Gallery"]


@pytest.fixture
def wiki(tmp_path, monkeypatch, config):
    path = tmp_path / "wiki_titles.json"
    path.write_text(json.dumps(TITLES), encoding="utf-8")
    monkeypatch.setattr(wiki_mod, "TITLES_PATH", path)
    w = Wiki({**config, "wiki": {"enabled": True, "prefetch": True}})
    w._load_index()
    return w


def test_wiki_match(wiki):
    assert wiki.match("Mirana, kto je Padre?") == "Padre"
    assert wiki.match("čo vieš o Sebastian Ibarra") == "Sebastian Ibarra"
    assert wiki.match("kto sú The Mox?") == "The Mox"
    assert wiki.match("čo je Mox") == "The Mox"           # gang ma prednost pred zbranou
    assert wiki.match("aký je Tanishi T400") == "Makigai Tanishi T400"
    assert wiki.match("kto je Padrej?") == "Padre"          # preklep z prepisu reci


def test_wiki_no_match(wiki):
    assert wiki.match("kto je Jackie?") is None             # hlavne postavy model pozna sam
    assert wiki.match("Padre") is None                      # nie je to otazka na lore
    assert wiki.match("čo je Night City") is None
    assert wiki.match("kto je Gallery") is None             # podstranky sa neindexuju


def test_clean_wikitext_and_infobox():
    raw = ("{{Infobox character\n|name = Padre\n|affiliation = [[Valentinos]]\n|status = Alive\n}}"
           "'''Sebastian \"Padre\" Ibarra''' is a [[fixer|Fixer]] in [[Heywood]].<ref>x</ref>\n\n== History ==\nOld.")
    box, body = wiki_mod._find_infobox(raw)
    assert "affiliation: Valentinos" in infobox_facts(box)
    assert "status" not in infobox_facts(box)               # spoiler (zije/zomrel) sa nehovori
    assert clean_wikitext(body) == 'Sebastian "Padre" Ibarra is a Fixer in Heywood.\nHistory:\nOld.'


# --- dlhodoba pamat ---------------------------------------------------------------------------------

def msg(login, text, badges=()):
    return SimpleNamespace(login=login, nick=login.capitalize(), text=text, badges=badges)


@pytest.fixture
def memory(config, data_dir):
    return LongTermMemory(config, "20261002-200000")


def test_add_chat_counts_and_logs(memory, data_dir):
    memory.add_chat(msg("kubo", "ahoj", ("subscriber",)))
    memory.add_chat(msg("kubo", "druha"))
    v = memory.data["viewers"]["kubo"]
    assert (v["messages"], v["visits"], v["badges"]) == (2, 1, ["subscriber"])
    lines = (data_dir / "logs" / "chat-20261002-200000.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["text"] for x in lines] == ["ahoj", "druha"]


def test_viewers_line_only_for_present_or_named(memory):
    memory.data["viewers"] = {
        "kubo_sk": {"nick": "Kubo_SK", "visits": 3, "first_seen": "2026-09-20", "notes": ["hrá za Nomáda"]},
        "anna": {"nick": "Anna", "visits": 1, "first_seen": "2026-10-01", "notes": []},
    }
    assert memory.viewers_line([], "čo robíš") is None
    line = memory.viewers_line([], "čo vieš o Kubovi?")
    assert line.startswith("[DIVÁCI] Kubo_SK: 3. deň na streame") and "hrá za Nomáda" in line
    assert "Anna" in memory.viewers_line(["anna"], "ahoj")


def test_forget_viewer_keeps_stats(memory, data_dir):
    memory.data["viewers"] = {"kubo": {"nick": "Kubo", "visits": 3, "notes": ["fanúšik Panam"]}}
    assert memory.forget_viewer("Mirana, zabudni Kuba") == "Kubo"
    saved = json.loads((data_dir / "data" / "memory.json").read_text(encoding="utf-8"))
    assert saved["viewers"]["kubo"] == {"nick": "Kubo", "visits": 3, "notes": []}
    assert memory.forget_viewer("zabudni Fera") is None


def test_forget_fact_with_fake_model(memory):
    memory.data["erik"]["facts"] = ["nemá rád stealth", "hrá za Corpo", "má psa"]
    reply = SimpleNamespace(content=[SimpleNamespace(type="text", text='{"remove": [0, 7]}')])
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: reply))
    assert memory.forget_fact(client, "zabudni, že nemám rád stealth") == 1
    assert memory.data["erik"]["facts"] == ["hrá za Corpo", "má psa"]


def test_block_and_reload(memory, data_dir):
    memory.data["erik"]["facts"] = ["hrá za Corpo"]
    memory.save(force=True)
    memory.reload()
    assert "hrá za Corpo" in memory.block


def test_chat_from_old_conversation_log(memory, data_dir):
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    record = {"erik": "[HRA] x\n[CHAT] Kubo (sub): ahoj | Anna: čau | dnes v chate písali: Kubo, Anna\n[ERIK] kto je Padre",
              "mirana": "Fixer."}
    (logs / "rozhovor-20260930-200000.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    items = memory._unprocessed()
    sid, talk, chat = items[0][:3]
    assert sid == "20260930-200000"
    assert talk == ["Erik: kto je Padre\nMirana: Fixer."]
    assert chat == ["kubo (Kubo): ahoj", "anna (Anna): čau"]
    assert memory.data["viewers"]["kubo"]["badges"] == ["subscriber"]


def test_update_stream_today(memory):
    memory.update_stream({"death": 2, "marker": 1}, 95)
    entry = memory.data["streams"][-1]
    assert entry["date"] == date.today().isoformat() and entry["minutes"] == 95
