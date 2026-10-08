import 'dart:async';

import 'package:http/http.dart' as http;

import '../core/chunker.dart';
import '../core/clock.dart';
import '../core/event_log.dart';
import '../core/prompt.dart';
import '../core/router.dart';
import '../core/stage.dart';
import 'llama_process.dart';

/// Phone tier mapping (docs/CONTRACT.md "Phone profile" row): ctx 1024 / n_predict 40, T2: 512 / 25.
class BrainTier {
  const BrainTier(this.ctx, this.nPredict);
  final int ctx, nPredict;
}

const Map<int, BrainTier> kBrainTiers = {0: BrainTier(1024, 40), 1: BrainTier(1024, 40), 2: BrainTier(512, 25), 3: BrainTier(512, 25)};

/// Brain on the phone. Speculation is OFF (phone profile, "off until measured"), so generation starts at
/// `final`. Chunks are still sent `held:true` and Brain logs `held_valid{match:true}` at `final`, so the
/// same commit gate as the laptop decides when Voice may play (match is trivially true without speculation).
class Brain implements Stage {
  Brain({required this.send, required this.log, required this.llm, Router? router, this.family = 'qwen3', this.tier = 0})
      : router = router ?? Router(),
        prompts = PromptBuilder(family: family);

  final Send send;
  final EventLog log;
  final LlamaProcess? llm; // null = cache/composed only (T3, or LLM failed to start)
  final Router router;
  final String family;
  int tier;
  PromptBuilder prompts;

  int _gen = 0;
  http.Client? _active;
  double? lastDecodeTps;
  double? lastPromptTps;

  void _ev(String event, int? turn, [Map<String, dynamic> extra = const {}]) => log.emit('brain', event, turn, extra: extra);

  @override
  Future<void> start() async {
    if (llm != null) {
      final t0 = now();
      final tm = await llm!.prefill(prompts.base());
      _ev('warm', null, {'s': now() - t0, 'prompt_n': tm['prompt_n']});
    }
    _ev('ready', null, {'llm': llm != null, 'tier': tier});
  }

  @override
  void feed(Msg msg) {
    switch (msg['type']) {
      case 'final':
        unawaited(_answer(msg['turn'] as int, (msg['text'] as String?) ?? '', (msg['norm'] as String?) ?? ''));
      case 'cancel' || 'barge_in':
        _cancel(msg['turn'] as int?);
      default:
        break; // partial / tentative_final: speculation off on the phone profile
    }
  }

  void _cancel(int? turn) {
    if (_active != null) {
      _active!.close(); // closing the connection is the cancel
      _active = null;
      send({'type': 'cancel', 'turn': turn, 'gen': _gen});
    }
  }

  Future<void> _answer(int turn, String text, String norm) async {
    _cancel(turn); // a new final supersedes anything still streaming
    final gen = ++_gen;
    final norm2 = norm.isEmpty ? normalize(text) : norm;
    final route = router.route(norm2);
    if (route.kind == 'cached' || (llm == null)) {
      final r = route.kind == 'llm' ? router.route('low power mode') : route;
      _ev('cache_hit', turn, {'intent': r.intent, 'clip': r.clip});
      _ev('held_valid', turn, {'gen': gen, 'match': true});
      send({'type': 'cached', 'turn': turn, 'gen': gen, 'clip': r.clip, 'text': r.text, 'held': true, 'last': true});
      return;
    }
    if (route.kind == 'composed') {
      _ev('cache_hit', turn, {'intent': route.intent, 'composed': true});
      _ev('held_valid', turn, {'gen': gen, 'match': true});
      send({'type': 'chunk', 'turn': turn, 'gen': gen, 'seq': 0, 'text': route.text, 'held': true, 'last': true});
      return;
    }

    final prompt = prompts.finalPrompt(text.trim());
    _ev('prompt_ready', turn, {'gen': gen, 'chars': prompt.length});
    _ev('held_valid', turn, {'gen': gen, 'match': true});
    final chunker = Chunker();
    final client = http.Client();
    _active = client;
    final reply = StringBuffer();
    var seq = 0;
    var first = true;
    Map<String, dynamic> timings = {};
    void out(String s, {bool last = false}) {
      if (seq == 0) _ev('first_chunk', turn, {'gen': gen, 'text': s});
      send({'type': 'chunk', 'turn': turn, 'gen': gen, 'seq': seq++, 'text': s, 'held': true, if (last) 'last': true});
    }

    try {
      await for (final piece in llm!.stream(prompt,
          nPredict: kBrainTiers[tier]!.nPredict, client: client, onTimings: (t) => timings = t)) {
        if (!identical(_active, client)) return; // cancelled
        if (first) {
          _ev('first_token', turn, {'gen': gen});
          first = false;
        }
        reply.write(piece);
        for (final c in chunker.push(piece)) {
          out(c);
        }
      }
    } catch (e) {
      if (!identical(_active, client)) return; // cancel closed the socket
      _ev('error', turn, {'gen': gen, 'error': e.toString()});
    }
    if (!identical(_active, client)) return;
    _active = null;
    client.close();
    final rest = chunker.flush();
    if (rest != null) {
      out(rest, last: true);
    } else if (seq > 0) {
      send({'type': 'chunk', 'turn': turn, 'gen': gen, 'seq': seq++, 'text': '', 'held': true, 'last': true});
    } else {
      // nothing generated: answer honestly instead of silence
      out("Sorry, I couldn't come up with an answer.", last: true);
    }
    final pn = (timings['predicted_n'] as num?)?.toDouble() ?? 0, pms = (timings['predicted_ms'] as num?)?.toDouble() ?? 0;
    final qn = (timings['prompt_n'] as num?)?.toDouble() ?? 0, qms = (timings['prompt_ms'] as num?)?.toDouble() ?? 0;
    lastDecodeTps = pms > 0 ? pn / (pms / 1000) : null;
    lastPromptTps = qms > 0 ? qn / (qms / 1000) : null;
    _ev('done', turn, {'gen': gen, 'timings': timings, 'decode_tps': lastDecodeTps, 'prompt_tps': lastPromptTps});
    prompts.addTurn(text.trim(), reply.toString());
  }

  @override
  Future<void> stop() async {
    _active?.close();
    _active = null;
  }

  @override
  void setTier(int n) => tier = n.clamp(0, 3);
}
