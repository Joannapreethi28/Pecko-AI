import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

/// Starts the bundled llama-server (b11501 android-arm64) and talks to it over HTTP, like
/// brain/llama_server.py + brain/llama_client.py on the laptop.
/// Android 10+ forbids exec from app data, so the binary ships as jniLibs/arm64-v8a/libllama_server.so
/// and is executed from nativeLibraryDir (extracted because of useLegacyPackaging = true).
class LlamaProcess {
  LlamaProcess({required this.nativeLibDir, required this.modelPath, this.port = 8080, this.ctx = 1024, this.threads = 4, this.logPath});

  final String nativeLibDir;
  final String modelPath;
  final int port, ctx, threads;
  final String? logPath;
  Process? _proc;
  IOSink? _log;

  int? get pid => _proc?.pid;
  Uri _u(String path) => Uri.parse('http://127.0.0.1:$port$path');

  Future<void> start({Duration timeout = const Duration(seconds: 90)}) async {
    final exe = '$nativeLibDir/libllama_server.so';
    final args = [
      '-m', modelPath, '--host', '127.0.0.1', '--port', '$port', //
      '-c', '$ctx', '-t', '$threads', '-tb', '$threads', '-np', '1', '-ctk', 'q8_0', '-ctv', 'q8_0',
    ];
    _proc = await Process.start(exe, args, environment: {'LD_LIBRARY_PATH': nativeLibDir}, workingDirectory: nativeLibDir);
    if (logPath != null) {
      _log = File(logPath!).openWrite(mode: FileMode.append);
      _proc!.stdout.listen(_log!.add);
      _proc!.stderr.listen(_log!.add);
    } else {
      _proc!.stdout.drain<void>();
      _proc!.stderr.drain<void>();
    }
    int? exitCode;
    unawaited(_proc!.exitCode.then((c) => exitCode = c));
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      if (exitCode != null) throw StateError('llama-server exited with code $exitCode (see llama-server.log)');
      if (await health()) return;
      await Future<void>.delayed(const Duration(milliseconds: 250));
    }
    throw TimeoutException('llama-server not healthy after $timeout');
  }

  Future<bool> health() async {
    try {
      final r = await http.get(_u('/health')).timeout(const Duration(seconds: 2));
      return r.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Warm the system prompt into the KV cache (n_predict 1: probe showed 0 returns no timings).
  Future<Map<String, dynamic>> prefill(String prompt) async {
    final r = await http.post(_u('/completion'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'prompt': prompt, 'n_predict': 1, 'stream': false, 'cache_prompt': true, 'id_slot': 0}));
    if (r.statusCode != 200) throw StateError('prefill HTTP ${r.statusCode}');
    return (jsonDecode(r.body)['timings'] as Map?)?.cast<String, dynamic>() ?? {};
  }

  /// Stream a completion (SSE). Yields text pieces; the final event's timings go to [onTimings].
  /// Cancel = close the client; llama-server stops generating on disconnect.
  Stream<String> stream(String prompt,
      {required int nPredict, double temperature = 0.4, void Function(Map<String, dynamic>)? onTimings, http.Client? client}) async* {
    final c = client ?? http.Client();
    try {
      final req = http.Request('POST', _u('/completion'))
        ..headers['Content-Type'] = 'application/json'
        ..body = jsonEncode({
          'prompt': prompt, 'n_predict': nPredict, 'stream': true, 'cache_prompt': true, //
          'temperature': temperature, 'stop': ['<|im_end|>'], 'id_slot': 0,
        });
      final resp = await c.send(req);
      if (resp.statusCode != 200) throw StateError('completion HTTP ${resp.statusCode}');
      await for (final ev in parseSse(resp.stream.transform(utf8.decoder).transform(const LineSplitter()))) {
        final text = (ev['content'] as String?) ?? '';
        if (ev['stop'] == true) {
          if (text.isNotEmpty) yield text;
          onTimings?.call((ev['timings'] as Map?)?.cast<String, dynamic>() ?? {});
          return;
        }
        if (text.isNotEmpty) yield text;
      }
    } finally {
      if (client == null) c.close();
    }
  }

  Future<void> stop() async {
    _proc?.kill(ProcessSignal.sigterm);
    await _proc?.exitCode.timeout(const Duration(seconds: 3), onTimeout: () {
      _proc?.kill(ProcessSignal.sigkill);
      return -9;
    });
    await _log?.flush();
    await _log?.close();
    _proc = null;
  }
}

/// SSE lines -> JSON events (same rule as brain/llama_client.iter_sse).
Stream<Map<String, dynamic>> parseSse(Stream<String> lines) async* {
  await for (final raw in lines) {
    final line = raw.trim();
    if (!line.startsWith('data:')) continue;
    final payload = line.substring(5).trim();
    if (payload == '[DONE]') return;
    yield (jsonDecode(payload) as Map).cast<String, dynamic>();
  }
}
