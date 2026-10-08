import pytest

from brain.speakable import ThinkFilter, clean


@pytest.mark.parametrize("raw,expected", [
    ("**Paris** is the `capital`.", "Paris is the capital."),
    ("- first item", "first item"),
    ("1. Step one", "Step one"),
    ("See https://example.com for more", "See for more"),
    ("Great job 🎉!", "Great job!"),
    ("Salt & pepper", "Salt and pepper"),
    ("  lots   of\nspace ", "lots of space"),
    ("# Heading", "Heading"),
])
def test_clean(raw, expected):
    assert clean(raw) == expected


def test_think_filter_drops_split_tags():
    f = ThinkFilter()
    out = "".join(f.feed(p) for p in ["<thi", "nk>secret", " plan</th", "ink>Hi", " there"])
    out += f.flush()
    assert out == "Hi there"


def test_think_filter_plain_text_passes_through():
    f = ThinkFilter()
    out = f.feed("Hello, ") + f.feed("world.") + f.flush()
    assert out == "Hello, world."
