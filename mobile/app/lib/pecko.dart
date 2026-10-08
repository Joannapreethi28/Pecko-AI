import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import 'core/bus.dart';
import 'core/event_log.dart';
import 'core/router.dart';
import 'core/stats.dart';
import 'stages/brain.dart';
import 'stages/ears.dart';
import 'stages/llama_process.dart';
import 'stages/telemetry.dart';
import 'stages/voice.dart';

enum PipeState { loading, idle, listening, thinking, speaking, error }

/// App-level wiring: builds the stages, the bus (Spine) and the dashboard state.
class Pecko extends ChangeNotifier {
  static const _ch = MethodChannel('pecko/native');

  final EventLog log = EventLog();
  late final Bus bus = Bus(log);
  final LatencyStats stats = LatencyStats();
  final Telemetry tele = Telemetry();
  final Router router = Router();

  Ears? ears;
  Brain? brain;
  Voice? voice;
  LlamaProcess? llama;

  PipeState state = PipeState.loading;
  String status = 'starting…';
  String modelLine = '';
  String deviceLine = '';
  String transcript = '';
  String reply = '';
  double? lastLatency;
  int tier = 0;
  String? modelsDir;
  List<File> wavs = [];
  final Map<int, double> _tEos = {};
  int _replyTurn = -1;
  Timer? _timer;

  Future<void> init() async {
    try {
      final ext = await getExternalStorageDirectory();
      if (ext == null) throw StateError('no external files dir');
      modelsDir = '${ext.path}/models';
      final run = Directory('${ext.path}/runs/run-${DateTime.now().toIso8601String().replaceAll(':', '').split('.').first}');
      log.openDir(run);
      final dev = (await _ch.invokeMapMethod<String, dynamic>('deviceInfo')) ?? {};
      deviceLine = '${dev['model']} · ${dev['soc']} · Android ${dev['android']} · '
          '${((dev['totalMem'] as int? ?? 0) / (1 << 30)).toStringAsFixed(1)} GB · ${dev['cpus']} CPU';
      log.emit('spine', 'device', null, extra: dev);
      final nativeDir = await _ch.invokeMethod<String>('nativeLibDir');

      final m = modelsDir!;
      String? gguf;
      var family = 'qwen3';
      if (File('$m/Qwen3-0.6B-Q4_0.gguf').existsSync()) {
        gguf = '$m/Qwen3-0.6B-Q4_0.gguf';
      } else if (File('$m/LFM2.5-350M-Q4_0.gguf').existsSync()) {
        gguf = '$m/LFM2.5-350M-Q4_0.gguf';
        family = 'lfm2';
      }
      wavs = Directory('$m/clips').existsSync()
          ? (Directory('$m/clips').listSync().whereType<File>().where((f) => f.path.endsWith('.wav')).toList()
            ..sort((a, b) => a.path.compareTo(b.path)))
          : [];

      const threads = 4; // [MEASURE] sweep -t 2 vs -t 4 on the device
      if (gguf != null && nativeDir != null) {
        status = 'starting llama-server…';
        notifyListeners();
        llama = LlamaProcess(nativeLibDir: nativeDir, modelPath: gguf, threads: threads, ctx: kBrainTiers[tier]!.ctx, logPath: '${run.path}/llama-server.log');
        try {
          await llama!.start();
          tele.llamaPid = llama!.pid;
        } catch (e) {
          log.emit('spine', 'llm_failed', null, extra: {'error': '$e'});
          status = 'LLM failed ($e) → cache-only mode';
          llama = null;
        }
      }
      modelLine = llama != null
          ? '${gguf!.split('/').last} · llama.cpp b11501 · ctx ${kBrainTiers[tier]!.ctx} · n_predict ${kBrainTiers[tier]!.nPredict} · -t $threads'
          : 'no LLM (cache + composed answers only)';

      voice = Voice(send: bus.fromVoice, log: log, ttsDir: '$m/vits-piper-en_US-lessac-low',
          cacheTexts: {for (final i in router.intents) i.clip: i.say});
      brain = Brain(send: bus.fromBrain, log: log, llm: llama, router: router, family: family, tier: tier);
      final vad = File('$m/silero_vad.onnx');
      ears = Ears(send: bus.fromEars, log: log, asrDir: '$m/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17', vadPath: vad.existsSync() ? vad.path : null);
      bus
        ..register('ears', ears!)
        ..register('brain', brain!)
        ..register('voice', voice!);
      log.stream.listen((rec) {
        if (rec['stage'] == 'brain') bus.onBrainLog(rec);
      });
      bus.onRouted = _onRouted;
      voice!.onFirstAudio = _onFirstAudio;
      ears!.onChange = () {
        if (ears!.listening) state = PipeState.listening;
        transcript = ears!.partial;
        notifyListeners();
      };

      status = 'loading speech models…';
      notifyListeners();
      await ears!.start();
      await voice!.start();
      await brain!.start();
      log.emit('spine', 'ready', null, extra: {'tier': tier, 'llm': llama != null});
      state = PipeState.idle;
      if (llama != null) status = 'ready';
      _timer = Timer.periodic(const Duration(seconds: 1), (_) {
        tele.sample();
        log.emit('spine', 'telemetry', null, extra: tele.toJson());
        notifyListeners();
      });
    } catch (e, st) {
      state = PipeState.error;
      status = 'error: $e';
      debugPrint('$st');
    }
    notifyListeners();
  }

  void _onRouted(String src, Map<String, dynamic> msg) {
    final turn = msg['turn'] as int?;
    switch (msg['type']) {
      case 'final':
        _tEos[turn!] = (msg['t_eos'] as num).toDouble();
        transcript = msg['text'] as String;
        reply = '';
        _replyTurn = turn;
        state = PipeState.thinking;
      case 'chunk':
        if (turn != _replyTurn) break;
        reply += (msg['text'] as String?) ?? '';
      case 'cached':
        if (turn != _replyTurn) break;
        reply = '${msg['text'] ?? msg['clip']}  [cached]';
      case 'playback_state':
        state = msg['playing'] == true ? PipeState.speaking : PipeState.idle;
    }
    notifyListeners();
  }

  void _onFirstAudio(int turn, double t) {
    final te = _tEos[turn];
    if (te == null) return;
    lastLatency = t - te;
    stats.add(lastLatency!);
    log.emit('spine', 'first_audio', turn, extra: {'latency_s': lastLatency, 'source': ears?.source});
    notifyListeners();
  }

  double? get tokPerSec => brain?.lastDecodeTps;

  @override
  void dispose() {
    _timer?.cancel();
    ears?.stop();
    voice?.stop();
    brain?.stop();
    llama?.stop();
    log.close();
    super.dispose();
  }
}
