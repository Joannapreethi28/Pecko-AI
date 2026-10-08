from brain.sim import speak


class StubStage:
    def __init__(self):
        self.msgs = []

    def feed(self, msg):
        self.msgs.append(msg)


def test_speak_message_sequence():
    s = StubStage()
    t_final = speak(s, 4, "What is the capital of France?", wps=1000, pause_ms=1)
    types = [m["type"] for m in s.msgs]
    assert types == ["partial"] * 6 + ["tentative_final", "final"]
    assert all(m["turn"] == 4 for m in s.msgs)
    assert t_final >= s.msgs[-2]["t_eos"]


def test_stable_is_all_but_newest_word():
    s = StubStage()
    speak(s, 1, "what is the capital", wps=1000, pause_ms=1)
    partials = [m for m in s.msgs if m["type"] == "partial"]
    assert partials[0]["stable"] == ""
    assert partials[3]["text"] == "what is the capital"
    assert partials[3]["stable"] == "what is the"


def test_final_and_tentative_are_normalized_consistently():
    s = StubStage()
    speak(s, 1, "What is the capital of France?", wps=1000, pause_ms=1)
    tent, fin = s.msgs[-2], s.msgs[-1]
    assert fin["text"] == "What is the capital of France?"
    assert fin["norm"] == tent["text"] == "what is the capital of france"
