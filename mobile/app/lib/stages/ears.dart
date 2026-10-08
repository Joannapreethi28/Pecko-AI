import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:record/record.dart';

import '../core/clock.dart';
import '../core/event_log.dart';
import '../core/prompt.dart';
import '../core/stage.dart';
import 'workers.dart';

Float32List pcm16ToFloat(Uint8List bytes) {
  final bd = ByteData.sublistView(bytes);
  final n = bytes.length ~/ 2;
  final out = Float32List(n);
  for (var i = 0; i < n; i++) {
    out[i] = bd.getInt16(i * 2, Endian.little) / 32768.0;
  }
  return out;
}

/// Minimal WAV reader: 16-bit PCM, mono, 16 kHz (the format of data/clips). Throws otherwise.
Float32List readWav16k(File f) {
  final b = f.readAsBytesSync();
  final bd = ByteData.sublistView(b);
  var p = 12;
  int? sr, ch, bits;
  while (p + 8 <= b.length) {
    final id = String.fromCharCodes(b.sublist(p, p + 4));
    final size = bd.getUint32(p + 4, Endian.little);
    if (id == 'fmt ') {
      ch = bd.getUint16(p + 10, Endian.little);
      sr = bd.getUint32(p + 12, Endian.little);
      bits = bd.getUint16(p + 22, Endian.little);
    } else if (id == 'data') {
      if (sr != 16000 || ch != 1 || bits != 16) throw FormatException('need 16 kHz mono 16-bit, got $sr Hz $ch ch $bits bit');
      return pcm16ToFloat(Uint8List.sublistView(b, p + 8, p + 8 + size));
    }
    p += 8 + size + (size & 1);
  }
  throw const FormatException('no data chunk');
}

/// Words agreed by two consecutive partials (contract `stable`).
String stablePrefix(String a, String b) {
  final wa = a.split(' '), wb = b.split(' ');
  final out = <String>[];
  for (var i = 0; i < wa.length && i < wb.length; i++) {
    if (wa[i] != wb[i]) break;
    out.add(wa[i]);
  }
  return out.join(' ');
}

/// Ears on the phone (phone profile row): mic or WAV-in -> Zipformer 20M int8 streaming ASR (+ Silero VAD)
/// in an isolate. End of speech: push-to-talk release (t_eos = release time), or in hands-free mode the
/// VAD's speech->silence flip (t_eos = flip time - 0.5 s min-silence, an approximation, labelled).
class Ears implements Stage {
  Ears({required this.send, required this.log, required this.asrDir, this.vadPath});

  final Send send;
  final EventLog log;
  final String asrDir;
  final String? vadPath;
  Worker? _asr;
  final AudioRecorder _rec = AudioRecorder();
  StreamSubscription<Uint8List>? _micSub;

  int turn = 0;
  bool listening = false;
  bool handsFree = false;
  bool voicePlaying = false;
  bool speech = false;
  String partial = '';
  String _prevPartial = '';
  double? _tEos;
  String source = 'mic';

  void Function()? onChange;

  void _ev(String e, [Map<String, dynamic> x = const {}]) => log.emit('ears', e, turn, extra: x);

  @override
  Future<void> start() async {
    _asr = await Worker.spawn(asrEntry, {'asrDir': asrDir, 'vad': vadPath, 'threads': 1});
    _asr!.events.listen(_onAsr);
    log.emit('ears', 'ready', null, extra: {'vad': vadPath != null});
  }

  void _onAsr(Map<String, dynamic> e) {
    switch (e['ev']) {
      case 'partial':
        if (!listening && _tEos == null) return;
        final text = (e['text'] as String).toLowerCase();
        final stable = stablePrefix(_prevPartial, text);
        _prevPartial = text;
        partial = text;
        send({'type': 'partial', 'turn': turn, 'text': text, 'stable': stable, 't': now()});
      case 'vad':
        speech = e['speech'] as bool;
        _ev('vad', {'speech': speech});
        if (handsFree && !voicePlaying) {
          if (speech && !listening) {
            _beginTurn();
          } else if (!speech && listening) {
            _endTurn(now() - 0.5, approx: true);
          }
        }
      case 'final':
        final tEndpoint = now();
        final text = (e['text'] as String).trim();
        final pretty = text.isEmpty ? '' : text[0].toUpperCase() + text.substring(1).toLowerCase();
        _ev('endpoint', {'t_eos': _tEos});
        _ev('asr_final', {'text': pretty, 'audio_s': e['audio_s'], 'decode_s': e['decode_s']});
        send({'type': 'final', 'turn': turn, 'text': pretty, 'norm': normalize(text), 't_eos': _tEos, 't_endpoint': tEndpoint});
        partial = pretty;
        _tEos = null;
      case 'error':
        _ev('error', {'error': e['error']});
    }
    onChange?.call();
  }

  void _beginTurn() {
    turn += 1;
    if (voicePlaying) send({'type': 'barge_in', 'turn': turn, 't': now()});
    _asr!.send({'cmd': 'reset'});
    partial = '';
    _prevPartial = '';
    listening = true;
    _ev('listen_start', {'source': source});
    onChange?.call();
  }

  void _endTurn(double tEos, {bool approx = false}) {
    listening = false;
    _tEos = tEos;
    _ev('t_eos', {'t_eos': tEos, 'source': source, 'approx': approx});
    _asr!.send({'cmd': 'finish'});
    onChange?.call();
  }

  Future<void> _startMic() async {
    if (_micSub != null) return;
    if (!await _rec.hasPermission()) throw StateError('microphone permission denied');
    final s = await _rec.startStream(const RecordConfig(encoder: AudioEncoder.pcm16bits, sampleRate: 16000, numChannels: 1));
    _micSub = s.listen((bytes) {
      if (listening || handsFree) _asr!.send({'cmd': 'audio', 'samples': pcm16ToFloat(bytes)});
    });
  }

  Future<void> _stopMic() async {
    await _micSub?.cancel();
    _micSub = null;
    await _rec.stop();
  }

  /// Push-to-talk: press.
  Future<void> pttDown() async {
    source = 'mic';
    _beginTurn();
    await _startMic();
  }

  /// Push-to-talk: release = end of speech.
  Future<void> pttUp() async {
    if (!listening) return;
    final t = now();
    if (!handsFree) await _stopMic();
    _endTurn(t);
  }

  Future<void> setHandsFree(bool on) async {
    handsFree = on;
    if (on) {
      source = 'mic-vad';
      await _startMic();
    } else {
      await _stopMic();
    }
    onChange?.call();
  }

  /// WAV-in: stream a pushed 16 kHz WAV at real-time speed (100 ms blocks); t_eos = end of the audio.
  Future<void> playWav(File f) async {
    final pcm = readWav16k(f);
    source = 'wav:${f.uri.pathSegments.last}';
    _beginTurn();
    const block = 1600;
    final t0 = now();
    for (var i = 0; i < pcm.length; i += block) {
      final end = i + block < pcm.length ? i + block : pcm.length;
      _asr!.send({'cmd': 'audio', 'samples': Float32List.sublistView(pcm, i, end)});
      final due = t0 + end / 16000.0;
      final wait = due - now();
      if (wait > 0) await Future<void>.delayed(Duration(microseconds: (wait * 1e6).round()));
    }
    _endTurn(t0 + pcm.length / 16000.0);
  }

  @override
  void feed(Msg msg) {
    if (msg['type'] == 'playback_state') {
      voicePlaying = msg['playing'] == true;
    }
  }

  @override
  Future<void> stop() async {
    await _stopMic();
    _asr?.kill();
  }

  @override
  void setTier(int n) {}
}
