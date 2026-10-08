import 'dart:io';

/// 1 s telemetry from /proc (no root needed for our own processes): VmRSS / VmHWM of the app and of the
/// llama-server child, and CPU% from utime+stime deltas. Sum of the two peaks is an upper bound on peak RAM.
class ProcSample {
  ProcSample({this.rssKb = 0, this.hwmKb = 0, this.cpuTicks = 0});
  final int rssKb, hwmKb, cpuTicks;
}

ProcSample readProc(String pid) {
  var rss = 0, hwm = 0, ticks = 0;
  try {
    for (final l in File('/proc/$pid/status').readAsLinesSync()) {
      if (l.startsWith('VmRSS:')) rss = int.parse(l.split(RegExp(r'\s+'))[1]);
      if (l.startsWith('VmHWM:')) hwm = int.parse(l.split(RegExp(r'\s+'))[1]);
    }
    final stat = File('/proc/$pid/stat').readAsStringSync();
    final f = stat.substring(stat.lastIndexOf(')') + 2).split(' ');
    ticks = int.parse(f[11]) + int.parse(f[12]); // utime + stime (fields 14, 15)
  } catch (_) {}
  return ProcSample(rssKb: rss, hwmKb: hwm, cpuTicks: ticks);
}

class Telemetry {
  static const double _hz = 100; // USER_HZ on Android/Linux
  int? llamaPid;
  ProcSample app = ProcSample(), llama = ProcSample();
  double appCpu = 0, llamaCpu = 0; // % of one core
  double? tempC;
  DateTime? _last;
  int _lastAppTicks = 0, _lastLlamaTicks = 0;

  void sample() {
    final t = DateTime.now();
    app = readProc('self');
    llama = llamaPid == null ? ProcSample() : readProc('$llamaPid');
    if (_last != null) {
      final dt = t.difference(_last!).inMicroseconds / 1e6;
      if (dt > 0) {
        appCpu = (app.cpuTicks - _lastAppTicks) / _hz / dt * 100;
        llamaCpu = (llama.cpuTicks - _lastLlamaTicks) / _hz / dt * 100;
      }
    }
    _last = t;
    _lastAppTicks = app.cpuTicks;
    _lastLlamaTicks = llama.cpuTicks;
    tempC = _readTemp();
  }

  double? _readTemp() {
    // battery thermal zone is often readable without root; may be null on some phones
    try {
      final v = int.parse(File('/sys/class/power_supply/battery/temp').readAsStringSync().trim());
      return v / 10.0;
    } catch (_) {
      return null;
    }
  }

  Map<String, dynamic> toJson() => {
        'app_rss_kb': app.rssKb, 'app_hwm_kb': app.hwmKb, 'llama_rss_kb': llama.rssKb, //
        'llama_hwm_kb': llama.hwmKb, 'app_cpu_pct': appCpu, 'llama_cpu_pct': llamaCpu, 'batt_temp_c': tempC,
      };
}
