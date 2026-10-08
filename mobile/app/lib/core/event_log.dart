import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'clock.dart';

/// Contract log line, same shape as the laptop:
/// {"stage":"brain","event":"first_token","turn":7,"t":13.41,"extra":{}}
/// Every line goes to events.jsonl (if a directory is set) and to a broadcast stream the dashboard reads.
class EventLog {
  EventLog({this.clock = now});

  final Clock clock;
  IOSink? _events;
  IOSink? _bus;
  final _ctrl = StreamController<Map<String, dynamic>>.broadcast();

  Stream<Map<String, dynamic>> get stream => _ctrl.stream;

  /// Open events.jsonl + bus.jsonl in [dir] (append). Safe to skip in tests.
  void openDir(Directory dir) {
    dir.createSync(recursive: true);
    _events = File('${dir.path}/events.jsonl').openWrite(mode: FileMode.append);
    _bus = File('${dir.path}/bus.jsonl').openWrite(mode: FileMode.append);
  }

  Map<String, dynamic> emit(String stage, String event, int? turn,
      {double? t, Map<String, dynamic> extra = const {}}) {
    final rec = <String, dynamic>{
      'stage': stage,
      'event': event,
      'turn': turn,
      't': t ?? clock(),
      'extra': extra,
    };
    _events?.writeln(jsonEncode(rec));
    _ctrl.add(rec);
    return rec;
  }

  /// Every routed contract message (laptop bus.jsonl format).
  void bus(String src, List<String> dst, Map<String, dynamic> msg) {
    _bus?.writeln(jsonEncode({'t': clock(), 'src': src, 'dst': dst, 'msg': msg}));
  }

  Future<void> close() async {
    await _events?.flush();
    await _bus?.flush();
    await _events?.close();
    await _bus?.close();
    await _ctrl.close();
  }
}
