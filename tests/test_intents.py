"""Klucove slova: skutocne otazky zo streamov (aj s chybami prepisu)."""

import json

import pytest

from mirana import intents
from mirana.features.longterm import record_chat, record_question
from mirana.turn import Turn

VISION_YES = [
    "Čo je toto za typka?",
    "To čo je toto?",
    "Čuje toto za týpka?",                          # prepis "čo je toto"
    "Ok, čistím tu niečo, neviem čo to je, neviem, kde som.",
    "Mirana, kto je toto, na koho teraz sa pozera?",
    "Mirana, čo je toto? Na čo sa teraz pozorám?",
    "Toto kdo je?",
    "Toto suše vyzerá dobre.",
    "Čo je toto za jeep, ty vole, to vyzerá ako ďavný tereniák.",
    "Pozri je tu mŕtvý Doom Doom a že vraje za neho odmena 670 eddies. Ako ho vydám policajtom?",
    "Mirana, vidíš to? Čo mám robiť?",
    "Mirana, čo je toto za auto?",
    "Čo vidíš na obrazovke?",
]
VISION_NO = [
    "OK, toto bol len test, takže koniec testu. Poďme si pozrieť logi.",
    "To je toto.",
    "Mirana, toto je náš úvodný stream. Ideme na to.",
    "A čo je to chladná hlava?",                     # nazov questu -> wiki, nie obrazovka
    "Mirana, zapínam hru. Pozri sa do chatu a pozdrav všetkých divákov.",
    "Mirana, toto bolo trošku odveci, napíš si do logu.",
    "Musíme sa napojeť na Wikipedia, tak toto nepôjde ďalej.",
    "Kto je Padre?",
    "Koľko mám peňazí?",
]


@pytest.mark.parametrize("question", VISION_YES)
def test_vision_yes(question):
    assert intents.wants_vision(question)


@pytest.mark.parametrize("question", VISION_NO)
def test_vision_no(question):
    assert not intents.wants_vision(question)


def test_note():
    assert intents.wants_note("Mirana, zapíš si do logu, že HUD je veľký")
    assert intents.wants_note("toto bolo trošku odveci, napíš si do logu")
    assert intents.wants_note("poznač si do poznámok, že chcem rýchlejší hlas")
    assert not intents.wants_note("zapíš si, že idem spať")       # bez miesta (log/poznamky)
    assert not intents.wants_note("pozri logy")


def test_forget_stream_lore():
    assert intents.wants_forget("Mirana, zabudni Kuba")
    assert not intents.wants_forget("nezabudni na Jackieho")
    assert intents.asks_about_stream("koľko krát som dnes zomrel?")
    assert intents.asks_about_stream("zhrň mi dnešný stream")
    assert not intents.asks_about_stream("kto je Padre?")
    assert intents.is_lore_question("povedz mi o Arasake")
    assert not intents.is_lore_question("ideme ďalej")


def test_turn_prompt_order_and_tag():
    turn = Turn(gen=0, source="typed", question="kto je Padre?")
    turn.add("SYSTÉM", "[SYSTÉM] x")
    turn.add("HRA", "[HRA] zdravie 80 %")
    turn.add("WIKI", "[WIKI Padre] fixer")
    turn.add("CHAT", None)                                       # prazdny riadok sa nepridava
    assert turn.build_prompt() == "[HRA] zdravie 80 %\n[WIKI Padre] fixer\n[SYSTÉM] x\n[ERIK] kto je Padre?"
    assert Turn(gen=0, source="game", question="Erik zomrel").tagged == "[GAME_EVENT] Erik zomrel"
    with pytest.raises(ValueError):
        turn.add("NEZNAME", "x")


def test_conversation_records_old_and_new_format():
    old = {"erik": "[HRA] x\n[CHAT] Kubo: ahoj\n[ERIK] kto je Padre", "mirana": "Fixer."}
    new = {"zdroj": "voice", "otazka": "kto je Padre", "kontext": {"CHAT": "[CHAT] Kubo: ahoj"}, "mirana": "Fixer."}
    game = {"zdroj": "game", "otazka": "Erik zomrel", "kontext": {}}
    assert record_question(old) == record_question(new) == "kto je Padre"
    assert record_question(game) is None
    assert record_chat(old) == record_chat(new) == "[CHAT] Kubo: ahoj"
    assert json.dumps(new, ensure_ascii=False)  # zaznam je cisty JSON
