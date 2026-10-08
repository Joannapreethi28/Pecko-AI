from brain.chunker import Chunker


def feed(ch, pieces):
    out = []
    for p in pieces:
        out += ch.push(p)
    return out


def test_first_chunk_at_comma_after_two_words():
    assert feed(Chunker(), ["Paris", " is", " the", " capital", ","]) == ["Paris is the capital,"]


def test_comma_before_two_words_waits():
    c = Chunker()
    assert feed(c, ["Yes", ","]) == []
    assert feed(c, [" it", " is", "."]) == ["Yes, it is."]


def test_first_chunk_after_six_pieces_at_word_boundary():
    out = feed(Chunker(), ["The", " sun", " is", " a", " star", " that", " shi"])
    assert out == ["The sun is a star "]


def test_decimal_not_split():
    c = Chunker(first_max_pieces=20)
    assert feed(c, ["It", " is", " 3", "."]) == []
    assert feed(c, ["5", " degrees", "."]) == ["It is 3.5 degrees."]


def test_thousands_not_split():
    c = Chunker(first_max_pieces=20)
    assert feed(c, ["About", " 1", ",", "000", " people", "."]) == ["About 1,000 people."]


def test_time_not_split():
    c = Chunker(first_max_pieces=20)
    assert feed(c, ["At", " 3", ":", "45", " pm", "."]) == ["At 3:45 pm."]


def test_period_after_digit_then_space_cuts():
    c = Chunker(first_max_pieces=20)
    assert feed(c, ["It", " was", " 2024", ".", " Then"]) == ["It was 2024."]


def test_later_chunk_needs_four_words_at_comma():
    c = Chunker()
    feed(c, ["Paris", " is", " big", ","])
    assert feed(c, [" and", " old", ","]) == []
    assert feed(c, [" and", " very", " pretty", "."]) == [" and old, and very pretty."]


def test_later_chunk_cuts_at_comma_with_four_words():
    c = Chunker()
    feed(c, ["Yes", " sure", ","])
    assert feed(c, [" it", " opens", " at", " nine", ","]) == [" it opens at nine,"]


def test_runaway_capped_at_25_words():
    c = Chunker()
    feed(c, ["Okay", " then", "."])
    out = feed(c, [f" w{i}" for i in range(27)])
    assert len(out) == 1
    assert len(out[0].split()) == 25


def test_flush_returns_rest_once():
    c = Chunker()
    feed(c, ["Hello", " there"])
    assert c.flush() == "Hello there"
    assert c.flush() is None
