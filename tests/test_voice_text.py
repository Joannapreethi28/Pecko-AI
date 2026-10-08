from voice.text import PhraseChunker, normalize


def test_numbers_money_percent_time():
    assert normalize("It costs ₹4,500, about 15% more.") == \
        "It costs four thousand five hundred rupees, about fifteen percent more."
    assert normalize("1,50,000") == "one lakh fifty thousand"
    assert normalize("at 3:45 and 10:05") == "at three forty-five and ten oh five"


def test_strip_markdown_emoji_links():
    assert normalize("**Paris** 😀 see https://x.com") == "Paris see I'll skip the link "


def test_first_phrase_cut_at_punctuation_or_six_words():
    c = PhraseChunker(lambda: 500)
    assert c.feed("Paris is the capital, and its largest city. Bye") == \
        ["Paris is the capital,", "and its largest city."]
    c = PhraseChunker(lambda: 500)
    assert c.feed("one two three four five six ") == ["one two three four five six"]


def test_streamed_digits_not_cut():
    c = PhraseChunker(lambda: 500)
    assert c.feed("It costs about 4,") == []          # "4," may continue as "4,500"
    assert c.feed("500 rupees today.") == ["It costs about 4,500 rupees today."]


def test_later_phrases_use_comma_only_when_buffer_low():
    c = PhraseChunker(lambda: 1000)
    c.feed("Sure thing, ")
    assert c.feed("first part, second part. ") == ["first part, second part."]
    c = PhraseChunker(lambda: 100)
    c.feed("Sure thing, ")
    assert c.feed("first part, second part. ") == ["first part,", "second part."]


def test_ablation_policies():
    w = PhraseChunker(policy="word")
    assert w.feed("one two three") == ["one", "two"]          # last word may still be growing
    s = PhraseChunker(policy="sentence")
    assert s.feed("Sure thing, it opens at ten. Then") == ["Sure thing, it opens at ten."]
    c = PhraseChunker(policy="comma")
    assert c.feed("Sure thing, it opens at ten. ") == ["Sure thing,", "it opens at ten."]
