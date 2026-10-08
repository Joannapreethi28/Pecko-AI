from brain.prompt import SYSTEM_PROMPT, PromptBuilder, normalize


def test_normalize_basic():
    assert normalize("What is the Capital of France?") == "what is the capital of france"


def test_normalize_keeps_apostrophe():
    assert normalize("What's up?") == "what's up"


def test_normalize_keeps_hindi_words_intact():
    assert normalize("नमस्ते, पेको!") == "नमस्ते पेको"


def test_final_extends_partial():
    b = PromptBuilder()
    assert b.final("what is the capital of france").startswith(b.partial("what is the capital"))


def test_base_is_byte_identical():
    b = PromptBuilder()
    assert b.base() == b.base()
    assert b.base() == PromptBuilder().base()


def test_qwen3_final_ends_with_empty_think_block():
    assert PromptBuilder().final("hi").endswith("<think>\n\n</think>\n\n")


def test_cache_invariant_next_turn_extends_previous():
    b = PromptBuilder()
    u, r = "hi there", "Hello, how can I help?"
    p1 = b.final(u)
    b.add_turn(u, r)
    assert b.base().startswith(p1 + r)


def test_history_trims_in_block():
    b = PromptBuilder()
    for i in range(3):
        assert b.add_turn(f"q{i}", f"a{i}") is False
    assert all(f"q{i}" in b.base() for i in range(3))
    assert b.add_turn("q3", "a3") is True
    base = b.base()
    assert "q3" in base and not any(f"q{i}" in base for i in range(3))
    assert b.add_turn("q4", "a4") is False
    assert b.add_turn("q5", "a5") is False
    base = b.base()
    assert all(f"q{i}" in base for i in (3, 4, 5)) and "q2" not in base


def test_append_only_between_trims():
    b = PromptBuilder()
    for i in range(10):
        prev = b.base()
        if not b.add_turn(f"q{i}", f"a{i}"):
            assert b.base().startswith(prev)


def test_keep_after_trim_two():
    b = PromptBuilder(max_turns=3, keep_after_trim=2)
    for i in range(3):
        assert b.add_turn(f"q{i}", f"a{i}") is False
    assert b.add_turn("q3", "a3") is True
    base = b.base()
    assert "q2" in base and "q3" in base and "q0" not in base and "q1" not in base


def test_max_turns_zero_keeps_none():
    b = PromptBuilder(max_turns=0)
    b.add_turn("q", "a")
    assert b.base() == PromptBuilder(max_turns=0).base()


def test_system_prompt_short():
    assert len(SYSTEM_PROMPT.split()) <= 90


def test_rebuild_keeps_turns_changes_template():
    b = PromptBuilder()
    b.add_turn("q", "a")
    nb = b.rebuild("lfm2")
    assert nb.family == "lfm2"
    assert "q" in nb.base()
    assert "<think>" in b.base() and "<think>" not in nb.base()


def test_rebuild_keeps_trim_settings():
    b = PromptBuilder(max_turns=4, keep_after_trim=2)
    nb = b.rebuild("lfm2")
    assert nb.max_turns == 4 and nb.keep_after_trim == 2


def test_clear():
    b = PromptBuilder()
    b.add_turn("q", "a")
    b.clear()
    assert b.base() == PromptBuilder().base()
