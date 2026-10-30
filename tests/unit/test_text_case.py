"""Proper case for exported names and QTHs (owner, 2026-10-29)."""

import pytest

from beam_navigator.core.text_case import proper_name, proper_qth


@pytest.mark.parametrize(
    ("typed", "shown"),
    [
        ("FRED L LLOYD", "Fred L Lloyd"),
        ('FRED "THE BOSS" LLOYD', 'Fred "The Boss" Lloyd'),
        ("O'BRIEN", "O'Brien"),
        ("MARY-ANN", "Mary-Ann"),
        ("bob smith", "Bob Smith"),
        ("JOHN SMITH III", "John Smith III"),
        ("McDonald", "McDonald"),  # mixed case: left as typed
        ("Al deLong", "Al deLong"),
        ("", ""),
    ],
)
def test_proper_name(typed: str, shown: str) -> None:
    assert proper_name(typed) == shown


@pytest.mark.parametrize(
    ("typed", "shown"),
    [
        ("TABERNACLE, NJ", "Tabernacle, NJ"),
        ("SCOTTSDALE, AZ", "Scottsdale, AZ"),
        ("CHERRY HILL", "Cherry Hill"),
        ("cherry hill, nj", "Cherry Hill, NJ"),
        ("TROY, ME", "Troy, ME"),
        ("Wernersville", "Wernersville"),
    ],
)
def test_proper_qth(typed: str, shown: str) -> None:
    assert proper_qth(typed) == shown


def test_none_stays_none() -> None:
    assert proper_name(None) is None and proper_qth(None) is None
