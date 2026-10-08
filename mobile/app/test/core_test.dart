// Unit tests for the device-free logic: bus routing, commit gate, prompt builder, chunker, router.
// Expected strings for chunker/prompt/normalize were produced by the laptop's Python modules
// (brain/chunker.py, brain/prompt.py) so the phone port is byte-compatible.
import 'package:flutter_test/flutter_test.dart';
import 'package:pecko_app/core/bus.dart';
import 'package:pecko_app/core/chunker.dart';
import 'package:pecko_app/core/event_log.dart';
import 'package:pecko_app/core/prompt.dart';
import 'package:pecko_app/core/router.dart';
import 'package:pecko_app/core/stage.dart';
import 'package:pecko_app/core/stats.dart';

class FakeStage implements Stage {
  final List<Msg> got = [];
  @override
  void feed(Msg msg) => got.add(msg);
  @override
  Future<void> start() async {}
  @override
  Future<void> stop() async {}
  int tier = 0;
  @override
  void setTier(int n) => tier = n;
}

List<String> chunkAll(List<String> pieces) {
  final c = Chunker();
  final out = <String>[];
  for (final p in pieces) {
    out.addAll(c.push(p));
  }
  final f = c.flush();
  if (f != null) out.add(f);
  return out;
}

void main() {
  group('bus routing (spine/app.py tables)', () {
    late Bus bus;
    late FakeStage ears, brain, voice;
    setUp(() {
      bus = Bus(EventLog(clock: () => 1.0), clock: () => 1.0);
      ears = FakeStage();
      brain = FakeStage();
      voice = FakeStage();
      bus..register('ears', ears)..register('brain', brain)..register('voice', voice);
    });

    test('ears messages', () {
      for (final t in ['partial', 'tentative_final', 'final', 'cancel']) {
        bus.fromEars({'type': t, 'turn': 1});
      }
      bus.fromEars({'type': 'barge_in', 'turn': 1});
      bus.fromEars({'type': 'intent_hint', 'turn': 1});
      expect(brain.got.map((m) => m['type']), ['partial', 'tentative_final', 'final', 'cancel', 'barge_in']);
      expect(voice.got.map((m) => m['type']), ['barge_in', 'intent_hint']);
      expect(ears.got, isEmpty);
    });

    test('brain messages go to voice only', () {
      bus.fromBrain({'type': 'chunk', 'turn': 1, 'gen': 1});
      bus.fromBrain({'type': 'cached', 'turn': 1, 'gen': 1});
      bus.fromBrain({'type': 'cancel', 'turn': 1, 'gen': 1});
      bus.fromBrain({'type': 'bogus', 'turn': 1});
      expect(voice.got.map((m) => m['type']), ['chunk', 'cached', 'cancel']);
      expect(brain.got, isEmpty);
    });

    test('playback_state goes to ears', () {
      bus.fromVoice({'type': 'playback_state', 'turn': 1, 'playing': true});
      expect(ears.got.single['playing'], true);
    });

    test('commit gate: held_valid match -> commit to voice', () {
      bus.onBrainLog({'stage': 'brain', 'event': 'held_valid', 'turn': 3, 'extra': {'gen': 2, 'match': true}});
      bus.onBrainLog({'stage': 'brain', 'event': 'held_valid', 'turn': 3, 'extra': {'gen': 3, 'match': false}});
      bus.onBrainLog({'stage': 'brain', 'event': 'first_token', 'turn': 3, 'extra': {'gen': 2}});
      expect(voice.got.length, 1);
      expect(voice.got.single, {'type': 'commit', 'turn': 3, 'gen': 2, 't': 1.0});
    });

    test('tier fan-out', () {
      bus.setTier(2);
      expect([ears.tier, brain.tier, voice.tier], [2, 2, 2]);
    });
  });

  group('HoldGate (v2.1 hold-and-release)', () {
    test('held items wait for commit, then release in order', () {
      final g = HoldGate<String>();
      expect(g.offer(7, 1, 'a', held: true), isEmpty);
      expect(g.offer(7, 1, 'b', held: true), isEmpty);
      expect(g.commit(7, 1), ['a', 'b']);
      expect(g.offer(7, 1, 'c', held: true), ['c']); // after commit, same gen plays at once
    });
    test('commit for another gen releases nothing', () {
      final g = HoldGate<String>();
      g.offer(7, 2, 'a', held: true);
      expect(g.commit(7, 1), isEmpty);
      expect(g.heldCount, 1);
    });
    test('newer gen invalidates older', () {
      final g = HoldGate<String>();
      g.offer(7, 1, 'old', held: true);
      g.offer(7, 2, 'new', held: true);
      expect(g.offer(7, 1, 'late-old', held: true), isEmpty);
      expect(g.commit(7, 1), isEmpty);
      expect(g.commit(7, 2), ['new']);
    });
    test('cancel drops held and blocks the same gen', () {
      final g = HoldGate<String>();
      g.offer(7, 1, 'a', held: true);
      expect(g.cancel(7, 1), isTrue);
      expect(g.commit(7, 1), isEmpty);
      expect(g.offer(7, 1, 'b', held: false), isEmpty);
      expect(g.offer(7, 2, 'c', held: false), ['c']);
    });
    test('new turn resets; older turn is stale', () {
      final g = HoldGate<String>();
      g.offer(7, 1, 'a', held: true);
      g.offer(8, 1, 'b', held: true);
      expect(g.commit(7, 1), isEmpty);
      expect(g.commit(8, 1), ['b']);
    });
  });

  group('prompt (byte-identical to brain/prompt.py)', () {
    test('qwen3 final prompt with one history turn', () {
      final pb = PromptBuilder()..addTurn('Hi there.', 'Hello!');
      expect(
          pb.finalPrompt('What is the capital of France?'),
          "<|im_start|>system\nYou are Pecko, an offline voice assistant running on this device. Answer in one or two short "
          "spoken sentences. Give the answer first, then at most one short reason. No lists, no markdown, no symbols, no "
          "emoji. Spell out numbers in words. If you don't know, say so in one sentence. You are offline and cannot browse, "
          "check live data or open apps.<|im_end|>\n<|im_start|>user\nHi there.<|im_end|>\n<|im_start|>assistant\n"
          "<think>\n\n</think>\n\nHello!<|im_end|>\n<|im_start|>user\nWhat is the capital of France?<|im_end|>\n"
          "<|im_start|>assistant\n<think>\n\n</think>\n\n");
    });
    test('partial is a byte prefix of final', () {
      final pb = PromptBuilder();
      expect(pb.finalPrompt('abc').startsWith(pb.partial('abc')), isTrue);
    });
    test('trim keeps last turn in one block', () {
      final pb = PromptBuilder();
      expect([for (var i = 0; i < 4; i++) pb.addTurn('u$i', 'r$i')], [false, false, false, true]);
      expect(pb.nTurns, 1);
      expect(pb.base().contains('u3'), isTrue);
    });
    test('normalize', () {
      expect(normalize("What's the Capital of France?!"), "what's the capital of france");
      expect(normalize('Hello, Pecko... 3.5 kg'), 'hello pecko 3 5 kg');
    });
  });

  group('chunker (same outputs as brain/chunker.py)', () {
    test('first clause at comma', () {
      expect(chunkAll(['Paris', ' is', ' the', ' capital', ',', ' and', ' its', ' largest', ' city', '.']),
          ['Paris is the capital,', ' and its largest city.']);
    });
    test('digit then dot waits one piece', () {
      expect(chunkAll(['It', ' is', ' 3', '.', ' 5', ' degrees', ' today', '.', ' Nice', '.']),
          ['It is 3.', ' 5 degrees today.', ' Nice.']);
    });
    test('first chunk forced after 6 pieces', () {
      expect(chunkAll(['one', ' two', ' three', ' four', ' five', ' six', ' seven', ' eight']),
          ['one two three four five ', 'six seven eight']);
    });
    test('later chunks need 4 words for a comma cut', () {
      expect(chunkAll(['Yes', ',', ' sure', '.', ' The', ' answer', ' is', ' here', ',', ' okay', ' then', ',', ' bye', '!']),
          ['Yes, sure.', ' The answer is here,', ' okay then, bye!']);
    });
  });

  group('router', () {
    final r = Router(clock: () => DateTime(2026, 10, 9, 2, 5));
    test('exact and lead-stripped', () {
      expect(r.route('hello').clip, 'greeting');
      expect(r.route('hey pecko what is your name').clip, 'your_name');
    });
    test('composed time/date', () {
      expect(r.route('what time is it').text, "It's two oh five at night.");
      expect(r.route('what is the date today').text, 'Today is Friday, October ninth.');
    });
    test('real questions go to the LLM', () {
      expect(r.route('what is the capital of france').kind, 'llm');
      expect(r.route('thank you for explaining photosynthesis').kind, 'llm');
    });
    test('empty -> didnt_catch', () => expect(r.route('').clip, 'didnt_catch'));
  });

  test('percentiles match numpy linear', () {
    final s = LatencyStats();
    for (final x in [1.0, 2.0, 3.0, 4.0, 10.0]) {
      s.add(x);
    }
    expect(s.p50, 3.0);
    expect(s.p90, closeTo(7.6, 1e-9));
  });
}
