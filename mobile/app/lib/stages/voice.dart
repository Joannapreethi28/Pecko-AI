import 'dart:async';
import 'dart:collection';
import 'dart:typed_data';

import 'package:flutter_pcm_sound/flutter_pcm_sound.dart';

import '../core/bus.dart';
import '../core/clock.dart';
import '../core/event_log.dart';
import '../core/stage.dart';
import 'workers.dart';

/// Audio output. Abstract so the hold/commit logic is testable without a device.
abstract class PcmSink {
  Future<void> setup(int sampleRate, void Function() onDrained);
  Future<void> feed(Int16List pcm);
  Future<void> flush();
}

/// flutter_pcm_sound: a streaming PCM player, so clause 1 plays while clause 2 synthesizes.
class PluginPcmSink implements PcmSink {
  int _sr = 16000;
  void Function()? _onDrained;

  @override
  Future<void> setup(int sampleRate, void Function() onDrained) async {
    _sr = sampleRate;
    _onDrained = onDrained;
    await FlutterPcmSound.setup(sampleRate: sampleRate, channelCount: 1);
    await FlutterPcmSound.setFeedThreshold(sampleRate ~/ 10);
    FlutterPcmSound.setFeedCallback((remaining) {
      if (remaining == 0) _onDrained?.call();
    });
  }

  @override
  Future<void> feed(Int16List pcm) => FlutterPcmSound.feed(PcmArrayInt16(bytes: pcm.buffer.asByteData(pcm.offsetInBytes, pcm.lengthInBytes)));

  @override
  Future<void> flush() async {
    await FlutterPcmSound.release();
    await setup(_sr, _onDrained ?? () {});
  }
}

Int16List toPcm16(Float32List f) {
  final out = Int16List(f.length);
  for (var i = 0; i < f.length; i++) {
    final v = (f[i] * 32767).round();
    out[i] = v > 32767 ? 32767 : (v < -32768 ? -32768 : v);
  }
  return out;
}

/// Voice on the phone: Piper lessac-low in a TTS isolate + hold-until-commit + cached clips.
class Voice implements Stage {
  Voice({required this.send, required this.log, required this.ttsDir, PcmSink? sink, this.cacheTexts = const {}})
      : sink = sink ?? PluginPcmSink();

  final Send send;
  final EventLog log;
  final String ttsDir;
  final PcmSink sink;
  final Map<String, String> cacheTexts; // clip -> text, pre-synthesized in the background after start
  final Map<String, Float32List> _clipPcm = {};

  /// Fired once per turn when the first PCM is handed to the player (first_audio_out).
  void Function(int turn, double t)? onFirstAudio;

  final HoldGate<Msg> gate = HoldGate<Msg>();
  Worker? _tts;
  int _sr = 16000;
  final Queue<Msg> _queue = Queue();
  bool _busy = false;
  int _reqId = 0;
  final Map<int, Completer<Map<String, dynamic>>> _pending = {};
  int _audibleTurn = -1, _audibleGen = -1;
  bool _firstOut = false;
  bool _lastQueued = false;
  bool playing = false;

  void _ev(String e, int? turn, [Map<String, dynamic> x = const {}]) => log.emit('voice', e, turn, extra: x);

  @override
  Future<void> start() async {
    _tts = await Worker.spawn(ttsEntry, {'ttsDir': ttsDir, 'threads': 1});
    _sr = (_tts!.ready['sr'] as int?) ?? 16000;
    _tts!.events.listen((e) {
      final c = _pending.remove(e['id']);
      if (c != null) c.complete(e);
    });
    await sink.setup(_sr, _onDrained);
    _ev('ready', null);
    unawaited(_warmCache());
  }

  Future<void> _warmCache() async {
    for (final e in cacheTexts.entries) {
      if (_clipPcm.containsKey(e.key)) continue;
      final r = await _synth(e.value);
      if (r['samples'] is Float32List) _clipPcm[e.key] = r['samples'] as Float32List;
    }
    _ev('cache_warm', null, {'clips': _clipPcm.length});
  }

  Future<Map<String, dynamic>> _synth(String text) {
    final id = ++_reqId;
    final c = Completer<Map<String, dynamic>>();
    _pending[id] = c;
    _tts!.send({'cmd': 'synth', 'id': id, 'text': text});
    return c.future;
  }

  @override
  void feed(Msg msg) {
    final turn = (msg['turn'] as int?) ?? -1;
    final gen = (msg['gen'] as int?) ?? 0;
    switch (msg['type']) {
      case 'chunk' || 'cached':
        _ev('chunk_recv', turn, {'gen': gen, 'seq': msg['seq'], 'held': msg['held'] == true});
        _enqueue(gate.offer(turn, gen, msg, held: msg['held'] == true));
      case 'commit':
        _enqueue(gate.commit(turn, gen));
      case 'cancel':
        if (gate.cancel(turn, gen)) _stopNow(turn, 'cancel');
      case 'barge_in':
        _stopNow(turn, 'barge_in');
      case 'intent_hint':
        break;
    }
  }

  void _enqueue(List<Msg> items) {
    if (items.isEmpty) return;
    final m = items.first;
    if (m['turn'] != _audibleTurn || m['gen'] != _audibleGen) {
      _audibleTurn = m['turn'] as int;
      _audibleGen = m['gen'] as int;
      _firstOut = false;
      _lastQueued = false;
    }
    _queue.addAll(items);
    unawaited(_pump());
  }

  Future<void> _pump() async {
    if (_busy) return;
    _busy = true;
    try {
      while (_queue.isNotEmpty) {
        final m = _queue.removeFirst();
        final turn = m['turn'] as int, gen = m['gen'] as int;
        if (m['last'] == true) _lastQueued = true;
        Float32List? pcm;
        if (m['type'] == 'cached' && _clipPcm.containsKey(m['clip'])) {
          pcm = _clipPcm[m['clip']];
          log.emit('voice', 'cache_play', turn, extra: {'clip': m['clip']});
        } else {
          final text = ((m['text'] as String?) ?? '').trim();
          if (text.isEmpty) continue;
          _ev('synth_start', turn, {'gen': gen, 'seq': m['seq']});
          final r = await _synth(text);
          if (r['samples'] is! Float32List) {
            _ev('synth_error', turn, {'error': r['error']});
            continue;
          }
          pcm = r['samples'] as Float32List;
          _ev('synth_end', turn, {'gen': gen, 'seq': m['seq'], 'synth_s': r['synth_s'], 'audio_s': pcm.length / _sr});
          if (m['type'] == 'cached') _clipPcm[m['clip'] as String] = pcm;
        }
        // stale after a cancel / newer gen while we synthesized? drop it
        if (turn != _audibleTurn || gen != _audibleGen || gate.gen != gen) continue;
        _ev('pcm_ready', turn, {'gen': gen, 'seq': m['seq']});
        if (!_firstOut) {
          _firstOut = true;
          final t = now();
          _ev('first_audio_out', turn, {'gen': gen});
          onFirstAudio?.call(turn, t);
        }
        if (!playing) {
          playing = true;
          send({'type': 'playback_state', 'turn': turn, 'playing': true, 't': now()});
        }
        await sink.feed(toPcm16(pcm!));
      }
    } finally {
      _busy = false;
    }
  }

  void _onDrained() {
    if (!playing) return;
    if (_queue.isEmpty && !_busy && _lastQueued) {
      playing = false;
      send({'type': 'playback_state', 'turn': _audibleTurn, 'playing': false, 't': now()});
    } else if (_queue.isEmpty && !_busy) {
      _ev('underrun', _audibleTurn);
    }
  }

  void _stopNow(int turn, String why) {
    _queue.clear();
    _audibleGen = -1;
    if (playing) {
      playing = false;
      unawaited(sink.flush());
      _ev('barge_in_stop', turn, {'why': why});
      send({'type': 'playback_state', 'turn': turn, 'playing': false, 't': now()});
    }
  }

  @override
  Future<void> stop() async {
    _queue.clear();
    _tts?.kill();
  }

  @override
  void setTier(int n) {} // phone profile: Piper low + cache at every tier
}
