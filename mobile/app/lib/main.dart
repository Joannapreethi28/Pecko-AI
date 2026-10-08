import 'package:flutter/material.dart';

import 'pecko.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const PeckoApp());
}

const _bg = Color(0xFF0E1116);
const _card = Color(0xFF171B22);
const _line = Color(0xFF262C36);
const _muted = Color(0xFF8B95A5);
const _text = Color(0xFFE6EAF0);

const _stateColor = {
  PipeState.loading: Color(0xFF8B95A5),
  PipeState.idle: Color(0xFF8B95A5),
  PipeState.listening: Color(0xFF3FB950),
  PipeState.thinking: Color(0xFFD29922),
  PipeState.speaking: Color(0xFF58A6FF),
  PipeState.error: Color(0xFFF85149),
};

class PeckoApp extends StatefulWidget {
  const PeckoApp({super.key});
  @override
  State<PeckoApp> createState() => _PeckoAppState();
}

class _PeckoAppState extends State<PeckoApp> {
  final Pecko p = Pecko();
  int _wavIdx = 0;

  @override
  void initState() {
    super.initState();
    p.init();
  }

  @override
  void dispose() {
    p.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Pecko',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(brightness: Brightness.dark, scaffoldBackgroundColor: _bg, useMaterial3: true),
      home: Scaffold(
        body: SafeArea(
          child: ListenableBuilder(listenable: p, builder: (context, _) => _body()),
        ),
      ),
    );
  }

  String _ms(double? s) => s == null || s.isNaN ? '–' : '${(s * 1000).round()}';
  String _mb(int kb) => kb == 0 ? '–' : (kb / 1024).toStringAsFixed(0);

  Widget _body() {
    final ready = p.state != PipeState.loading && p.state != PipeState.error;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          const Text('Pecko', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: _text)),
          const SizedBox(width: 10),
          const Text('offline · CPU only', style: TextStyle(color: _muted)),
          const Spacer(),
          _pill(p.state.name.toUpperCase(), _stateColor[p.state]!),
        ]),
        const SizedBox(height: 4),
        Text(p.deviceLine, style: const TextStyle(color: _muted, fontSize: 12)),
        Text('T${p.tier} · ${p.modelLine}', style: const TextStyle(color: _muted, fontSize: 12)),
        if (p.status != 'ready') Text(p.status, style: const TextStyle(color: Color(0xFFD29922), fontSize: 12)),
        const SizedBox(height: 12),
        // first-audio latency: end of speech -> first answer PCM handed to the player
        _box(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('FIRST AUDIO (end of speech → first answer audio)', style: TextStyle(color: _muted, fontSize: 11, letterSpacing: 0.6)),
          const SizedBox(height: 6),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(_ms(p.lastLatency), style: const TextStyle(fontSize: 52, fontWeight: FontWeight.w700, color: _text, height: 1)),
            const Padding(padding: EdgeInsets.only(left: 4, bottom: 6), child: Text('ms', style: TextStyle(color: _muted, fontSize: 18))),
            const Spacer(),
            _stat('p50', _ms(p.stats.p50)),
            _stat('p90', _ms(p.stats.p90)),
            _stat('n', '${p.stats.n}'),
          ]),
        ])),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(child: _metric('APP RAM', _mb(p.tele.app.rssKb), 'MB', 'peak ${_mb(p.tele.app.hwmKb)}')),
          const SizedBox(width: 10),
          Expanded(child: _metric('LLAMA RAM', _mb(p.tele.llama.rssKb), 'MB', 'peak ${_mb(p.tele.llama.hwmKb)}')),
          const SizedBox(width: 10),
          Expanded(child: _metric('DECODE', p.tokPerSec?.toStringAsFixed(1) ?? '–', 'tok/s', 'CPU ${(p.tele.appCpu + p.tele.llamaCpu).round()}%')),
        ]),
        if (p.tele.tempC != null)
          Padding(padding: const EdgeInsets.only(top: 6), child: Text('battery ${p.tele.tempC!.toStringAsFixed(1)} °C', style: const TextStyle(color: _muted, fontSize: 12))),
        const SizedBox(height: 10),
        Expanded(
          child: _box(SingleChildScrollView(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('YOU', style: TextStyle(color: _muted, fontSize: 11, letterSpacing: 0.6)),
              const SizedBox(height: 4),
              Text(p.transcript.isEmpty ? '…' : p.transcript, style: const TextStyle(fontSize: 20, color: _text)),
              const SizedBox(height: 14),
              const Text('PECKO', style: TextStyle(color: _muted, fontSize: 11, letterSpacing: 0.6)),
              const SizedBox(height: 4),
              Text(p.reply.isEmpty ? '…' : p.reply, style: const TextStyle(fontSize: 20, color: Color(0xFF58A6FF))),
            ]),
          )),
        ),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(
            child: OutlinedButton(
              onPressed: ready && p.wavs.isNotEmpty
                  ? () {
                      final f = p.wavs[_wavIdx % p.wavs.length];
                      _wavIdx++;
                      p.ears!.playWav(f);
                    }
                  : null,
              child: Text(p.wavs.isEmpty ? 'WAV-in: none pushed' : 'WAV-in ${(_wavIdx % p.wavs.length) + 1}/${p.wavs.length}'),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: OutlinedButton(
              onPressed: ready ? () => p.ears!.setHandsFree(!(p.ears!.handsFree)) : null,
              child: Text(p.ears?.handsFree == true ? 'Hands-free (VAD): ON' : 'Hands-free (VAD): off'),
            ),
          ),
        ]),
        const SizedBox(height: 10),
        GestureDetector(
          onTapDown: ready ? (_) => p.ears!.pttDown() : null,
          onTapUp: ready ? (_) => p.ears!.pttUp() : null,
          onTapCancel: ready ? () => p.ears!.pttUp() : null,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 120),
            height: 84,
            decoration: BoxDecoration(
              color: p.ears?.listening == true ? const Color(0xFF238636) : (ready ? const Color(0xFF1F6FEB) : _line),
              borderRadius: BorderRadius.circular(18),
            ),
            alignment: Alignment.center,
            child: Text(p.ears?.listening == true ? 'Listening… release to send' : 'Hold to talk',
                style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600, color: Colors.white)),
          ),
        ),
      ]),
    );
  }

  Widget _box(Widget child) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: _card, borderRadius: BorderRadius.circular(14), border: Border.all(color: _line)),
        child: child,
      );

  Widget _pill(String s, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(color: c.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(20), border: Border.all(color: c)),
        child: Text(s, style: TextStyle(color: c, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
      );

  Widget _stat(String k, String v) => Padding(
        padding: const EdgeInsets.only(left: 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(k, style: const TextStyle(color: _muted, fontSize: 11)),
          Text(v, style: const TextStyle(color: _text, fontSize: 20, fontWeight: FontWeight.w600)),
        ]),
      );

  Widget _metric(String k, String v, String unit, String sub) => _box(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(k, style: const TextStyle(color: _muted, fontSize: 11, letterSpacing: 0.6)),
        const SizedBox(height: 4),
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Flexible(child: Text(v, style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: _text))),
          Padding(padding: const EdgeInsets.only(left: 3, bottom: 3), child: Text(unit, style: const TextStyle(color: _muted, fontSize: 12))),
        ]),
        Text(sub, style: const TextStyle(color: _muted, fontSize: 11)),
      ]));
}
