"""Co Erik chce — vsetky klucove slova na jednom mieste (testy v tests/test_intents.py).

Otazky prichadzaju z prepisu reci (Whisper), preto vzory pocitaju s chybajucou diakritikou a
drobnymi preklepmi ("čuje toto" = "čo je toto"). Vsetko su len lacne regexy pred volanim modelu.
"""

import re

_I = re.I

# --- pozri sa na obrazovku (snimka okna hry ide modelu) -------------------------------------------
# Jasne vizualne: na co sa pozeram, vidis, obrazovka, "co je toto", "co to je?" (bez nazvu za tym).
_VISION_STRONG = re.compile(
    r"\b(vidíš|vidis|obrazovk\w*|na (čo|co|koho) sa (teraz )?(pozerám|pozeram|pozerá|pozera|dívam|divam)|"
    r"(čo|co) (vidím|vidim)|na (čo|co|koho) mierim|"
    r"(čo|co|kto|kdo|čuje|cuje) (je |sú |su )?(toto|tento|táto|tato|tieto|tamto)|"
    r"(toto|tento|táto|tato|tieto|tamto) (je )?(kto|kdo|čo|co)\b|"
    r"(čo|co) (je )?to( je)?(?=\s*(\?|,|\.|$|za\b)))", _I)
# Ukazovacie zameno (toto, tento...) — len spolu s otazkou alebo "vyzera", inak je to bezna rec.
_DEMONSTRATIVE = re.compile(r"\b(toto|tento|táto|tato|tieto|tohto|tomto|tamto|pozri)\b", _I)
_QUESTION = re.compile(r"\?|\b(čo|co|kto|kdo|aký|aky|aká|aka|aké|ake|akú|aku|kde|koľko|kolko|ako|prečo|preco|"
                       r"vyzerá|vyzera|vyzerajú|vyzeraju)\b", _I)
# Rec o Mirane, streame a logoch nie je o obrazovke ("toto bol len test", "pozri sa do chatu").
_META = re.compile(r"\b(test\w*|log\w*|stream\w*|chat\w*|wiki\w*|lore|persón\w*|person\w*|kamer\w*)\b", _I)


def wants_vision(question: str) -> bool:
    if _VISION_STRONG.search(question):
        return not _META.search(question) or bool(re.search(r"vidíš|vidis|obrazovk|pozer", question, _I))
    pointing = [m for m in _DEMONSTRATIVE.finditer(question) if not _NAME_AFTER.match(question, m.end())]
    return bool(pointing and _QUESTION.search(question) and not _META.search(question))


# "Tato Evelyn Parker", "tento Jackie" — ukazovacie slovo pred menom je otazka na postavu (wiki), nie na obrazovku
_NAME_AFTER = re.compile(r"\s+[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ]")


# --- zabudni (dlhodoba pamat) ----------------------------------------------------------------------
_FORGET = re.compile(r"\bzabudni\b", _I)  # "Mirana, zabudni Kuba" / "zabudni, ze nemam rad stealth"


def wants_forget(question: str) -> bool:
    return bool(_FORGET.search(question))


# --- poznamka do logu ("zapis si do logu, ze ...") -----------------------------------------------
_NOTE_VERB = re.compile(r"\bzap[ií]š|\bzap[ií]s|poznač|poznac|zaznač|zaznac|zapamät|zapamat", _I)
_NOTE_PLACE = re.compile(r"do logu|\blog\w*|poznám|poznam", _I)
_WRITE = re.compile(r"\bnap[ií]š|\bnapis", _I)


def wants_note(question: str) -> bool:
    """Kazde "zapis / zapamataj si / poznac" (aj skomolene prepisom: zapisci, zapísi) ide do poznamok;
    "napis" len s "do logu", lebo "napis do chatu" je nieco ine (3.10.: 8 zo 14 ziadosti sa stratilo)."""
    return bool(_NOTE_VERB.search(question) or (_WRITE.search(question) and _NOTE_PLACE.search(question)))


# --- otazka na stream (riadok [STREAM] so statistikami) --------------------------------------------
_STREAM = re.compile(r"stream|zhr[nň]|\bdne[sš]|smrt[ií]|zomrel|umrel|koľko krát|kolko krat", _I)


def asks_about_stream(question: str) -> bool:
    return bool(_STREAM.search(question))


# --- otazka na lore (predhladanie vo wiki) ---------------------------------------------------------
_LORE = re.compile(r"\b(kto|čo|co|aký|aká|aké|akú|aky|aka|ake|aku|odkiaľ|odkial|povedz mi o|čo vieš o|co vies o|"
                   r"kde (je|nájdem|najdem))\b", _I)


def is_lore_question(question: str) -> bool:
    return bool(_LORE.search(question))


# --- nadavky (HUD v2 ich na okamih zaglitchuje) ---------------------------------------------------------
SWEAR = re.compile(r"\b(kurv\w*|kurev\w*|do (?:riti|piče|prdele|hajzlu)|piči\w*|pič\w*|kokot\w*|čurák\w*|curak\w*|"
                   r"hovn\w*|sračk\w*|srac\w*|doprdele|prdel\w*|jeb\w*|pojeb\w*|vyjeb\w*|zjeb\w*|zasran\w*|"
                   r"posran\w*|chuj\w*|debil\w*|sakra)\b", _I)
