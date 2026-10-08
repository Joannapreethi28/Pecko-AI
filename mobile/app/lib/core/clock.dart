/// One monotonic clock for the whole app (laptop rule: `time.monotonic()` seconds everywhere).
/// On the phone everything runs in one process, so a single Stopwatch started at launch is enough.
/// Isolates get their own Stopwatch, so worker isolates never stamp contract times; they report
/// durations and the main isolate stamps `t`.
library;

final Stopwatch _sw = Stopwatch()..start();

/// Seconds since app launch, as a double (monotonic).
double now() => _sw.elapsedMicroseconds / 1e6;

/// Test hook: a fake clock can be injected where a stage takes `double Function()`.
typedef Clock = double Function();
