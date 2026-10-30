import pytest

from beam_navigator.core.callsign import base_callsign, is_callsign, normalize_callsign


@pytest.mark.parametrize(
    "text", ["W2KV", "n2lqh", "K1ABC/P", "EA/K1ABC", "VE2XX", "KA3WXV", "2E0ABC", " W2KV "]
)
def test_is_callsign(text: str) -> None:
    assert is_callsign(text)


@pytest.mark.parametrize(
    "text", ["FN20ok", "FN20", "AB12", "50.150", "NE", "247", "NBA", "76'ER", "", "K1ABC/", "/P",
             "123A"]
)
def test_not_callsign(text: str) -> None:
    assert not is_callsign(text)


def test_normalize_callsign() -> None:
    assert normalize_callsign(" k1abc/p ") == "K1ABC/P"


@pytest.mark.parametrize(
    ("text", "base"), [("K1ABC/P", "K1ABC"), ("EA/K1ABC", "K1ABC"), ("w2kv", "W2KV")]
)
def test_base_callsign(text: str, base: str) -> None:
    assert base_callsign(text) == base
