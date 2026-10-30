"""Proper case for names and QTHs in exports (owner, 2026-10-29).

Only words typed all in capitals or all in lower case change: a mixed-case spelling such
as McDonald or deLong is the operator's and is left alone. A short code after the last
comma of a QTH (NJ, ME, ONT) stays in capitals.
"""

import re

_WORD = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
_PART = re.compile(r"[A-Za-z]+")
_ROMAN = {"II", "III", "IV"}
_REGION = re.compile(r"\s*[A-Za-z]{2,3}\s*")


def _word(word: str) -> str:
    if not (word.isupper() or word.islower()):
        return word
    if word.upper() in _ROMAN:
        return word.upper()
    return _PART.sub(lambda part: part.group().capitalize(), word)


def proper_name(text: str | None) -> str | None:
    if text is None:
        return None
    return _WORD.sub(lambda match: _word(match.group()), text)


def proper_qth(text: str | None) -> str | None:
    if text is None:
        return None
    head, comma, tail = text.rpartition(",")
    if comma and _REGION.fullmatch(tail):
        return f"{proper_name(head)},{tail.upper()}"
    return proper_name(text)
