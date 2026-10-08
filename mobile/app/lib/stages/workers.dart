import 'dart:async';
import 'dart:isolate';
import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as so;

/// sherpa-onnx calls are synchronous FFI. Running them on the UI isolate would freeze the dashboard during
/// decode/synthesis, so ASR(+VAD) and TTS each live in their own isolate. Workers never stamp contract
/// times (different Stopwatch); they report durations, and the main isolate stamps `t`.
class Worker {
  Worker._(this._iso, this._send, this.events, this.ready);

  final Isolate _iso;
  final SendPort _send;
  final Stream<Map<String, dynamic>> events;
  final Map<String, dynamic> ready; // the worker's ready event (e.g. TTS sample rate)

  static Future<Worker> spawn(void Function(SendPort) entry, Map<String, dynamic> init) async {
    final rx = ReceivePort();
    final iso = await Isolate.spawn(entry, rx.sendPort);
    final events = rx.map((e) => e).asBroadcastStream();
    final send = await events.firstWhere((e) => e is SendPort) as SendPort;
    final evs = events.where((e) => e is Map).map((e) => (e as Map).cast<String, dynamic>()).asBroadcastStream();
    send.send({'cmd': 'init', ...init});
    final ready = await evs.firstWhere((e) => e['ev'] == 'ready' || e['ev'] == 'error');
    if (ready['ev'] == 'error') throw StateError('worker init failed: ${ready['error']}');
    return Worker._(iso, send, evs, ready);
  }

  void send(Map<String, dynamic> msg) => _send.send(msg);

  void kill() => _iso.kill(priority: Isolate.immediate);
}

// ---------------------------------------------------------------- ASR + VAD isolate
/// Zipformer 20M int8 streaming transducer + Silero VAD. Commands: init, reset, audio, finish.
void asrEntry(SendPort out) {
  final rx = ReceivePort();
  out.send(rx.sendPort);
  so.OnlineRecognizer? rec;
  so.OnlineStream? stream;
  so.VoiceActivityDetector? vad;
  var lastText = '';
  var speech = false;
  var audioS = 0.0, decodeS = 0.0;
  final sw = Stopwatch()..start();

  void decode() {
    final t0 = sw.elapsedMicroseconds;
    while (rec!.isReady(stream!)) {
      rec!.decode(stream!);
    }
    decodeS += (sw.elapsedMicroseconds - t0) / 1e6;
  }

  rx.listen((m) {
    final msg = (m as Map).cast<String, dynamic>();
    try {
      switch (msg['cmd']) {
        case 'init':
          so.initBindings();
          final d = msg['asrDir'] as String;
          rec = so.OnlineRecognizer(so.OnlineRecognizerConfig(
            model: so.OnlineModelConfig(
              transducer: so.OnlineTransducerModelConfig(
                encoder: '$d/encoder-epoch-99-avg-1.int8.onnx',
                decoder: '$d/decoder-epoch-99-avg-1.int8.onnx',
                joiner: '$d/joiner-epoch-99-avg-1.int8.onnx',
              ),
              tokens: '$d/tokens.txt',
              numThreads: (msg['threads'] as int?) ?? 1,
              debug: false,
            ),
            enableEndpoint: false, // push-to-talk release (or VAD) is the endpoint
          ));
          stream = rec!.createStream();
          final vadPath = msg['vad'] as String?;
          if (vadPath != null) {
            vad = so.VoiceActivityDetector(
              config: so.VadModelConfig(
                sileroVad: so.SileroVadModelConfig(model: vadPath, minSilenceDuration: 0.5, minSpeechDuration: 0.25, maxSpeechDuration: 20.0),
                numThreads: 1,
                debug: false,
              ),
              bufferSizeInSeconds: 30,
            );
          }
          out.send({'ev': 'ready'});
        case 'reset':
          stream?.free();
          stream = rec!.createStream();
          vad?.clear();
          lastText = '';
          speech = false;
          audioS = 0;
          decodeS = 0;
        case 'audio':
          final s = msg['samples'] as Float32List;
          audioS += s.length / 16000.0;
          stream!.acceptWaveform(samples: s, sampleRate: 16000);
          decode();
          final text = rec!.getResult(stream!).text.trim();
          if (text != lastText) {
            lastText = text;
            out.send({'ev': 'partial', 'text': text});
          }
          if (vad != null) {
            vad!.acceptWaveform(s);
            final det = vad!.isDetected();
            while (!vad!.isEmpty()) {
              vad!.pop();
            }
            if (det != speech) {
              speech = det;
              out.send({'ev': 'vad', 'speech': det});
            }
          }
        case 'finish':
          // tail padding before inputFinished, as sherpa's examples do (flushes the last frames)
          stream!.acceptWaveform(samples: Float32List((0.66 * 16000).round()), sampleRate: 16000);
          stream!.inputFinished();
          decode();
          final text = rec!.getResult(stream!).text.trim();
          out.send({'ev': 'final', 'text': text, 'audio_s': audioS, 'decode_s': decodeS});
      }
    } catch (e) {
      out.send({'ev': 'error', 'error': e.toString()});
    }
  });
}

// ---------------------------------------------------------------- TTS isolate
/// Piper lessac-low (VITS) via sherpa-onnx, 1 thread. Commands: init, synth.
void ttsEntry(SendPort out) {
  final rx = ReceivePort();
  out.send(rx.sendPort);
  so.OfflineTts? tts;
  final sw = Stopwatch()..start();
  rx.listen((m) {
    final msg = (m as Map).cast<String, dynamic>();
    try {
      switch (msg['cmd']) {
        case 'init':
          so.initBindings();
          final d = msg['ttsDir'] as String;
          tts = so.OfflineTts(so.OfflineTtsConfig(
            model: so.OfflineTtsModelConfig(
              vits: so.OfflineTtsVitsModelConfig(
                model: '$d/en_US-lessac-low.onnx',
                tokens: '$d/tokens.txt',
                dataDir: '$d/espeak-ng-data',
              ),
              numThreads: (msg['threads'] as int?) ?? 1,
              debug: false,
            ),
          ));
          // warm-up so the first real sentence does not pay session init
          tts!.generate(text: 'Hi.');
          out.send({'ev': 'ready', 'sr': tts!.sampleRate});
        case 'synth':
          final t0 = sw.elapsedMicroseconds;
          final a = tts!.generate(text: msg['text'] as String, speed: 1.0);
          final synthS = (sw.elapsedMicroseconds - t0) / 1e6;
          out.send({'ev': 'audio', 'id': msg['id'], 'samples': a.samples, 'sr': a.sampleRate, 'synth_s': synthS});
      }
    } catch (e) {
      out.send({'ev': 'error', 'id': msg['id'], 'error': e.toString()});
    }
  });
}
