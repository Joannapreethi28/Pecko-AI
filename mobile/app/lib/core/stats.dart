/// Session latency stats. Percentiles use linear interpolation (numpy's default), so p50/p90 match
/// the laptop report scripts for the same samples.
library;

double percentile(List<double> xs, double p) {
  if (xs.isEmpty) return double.nan;
  final s = List<double>.of(xs)..sort();
  final pos = (s.length - 1) * p / 100.0;
  final lo = pos.floor(), hi = pos.ceil();
  if (lo == hi) return s[lo];
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

class LatencyStats {
  final List<double> samples = [];
  int failures = 0; // turns that produced no audio: kept and reported, never dropped

  void add(double seconds) => samples.add(seconds);
  int get n => samples.length;
  double get p50 => percentile(samples, 50);
  double get p90 => percentile(samples, 90);
  double? get last => samples.isEmpty ? null : samples.last;
}
