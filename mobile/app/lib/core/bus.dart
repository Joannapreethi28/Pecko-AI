import 'clock.dart';
import 'event_log.dart';
import 'stage.dart';

/// Who receives each message type. Same tables as spine/app.py (docs/CONTRACT.md).
const Map<String, List<String>> kFromEars = {
  'partial': ['brain'],
  'tentative_final': ['brain'],
  'final': ['brain'],
  'cancel': ['brain'],
  'barge_in': ['voice', 'brain'],
  'intent_hint': ['voice'],
};
const Map<String, List<String>> kFromBrain = {
  'chunk': ['voice'],
  'cached': ['voice'],
  'cancel': ['voice'],
};

/// Spine on the phone: routes contract messages between stages and owns the commit gate C
/// (v2.1 hold-and-release). When Brain logs `held_valid{match:true, gen}`, the final transcript matched
/// what Brain prepared, so Spine sends `commit` to Voice. Nothing held is audible before that.
class Bus {
  Bus(this.log, {this.clock = now});

  final EventLog log;
  final Clock clock;
  final Map<String, Stage> stages = {};

  /// Called with every routed message (dashboard hook). Optional.
  void Function(String src, Msg msg)? onRouted;

  void register(String name, Stage s) => stages[name] = s;

  void _deliver(String src, List<String> dsts, Msg msg) {
    log.bus(src, dsts, msg);
    onRouted?.call(src, msg);
    for (final d in dsts) {
      stages[d]?.feed(msg);
    }
  }

  void fromEars(Msg msg) => _deliver('ears', kFromEars[msg['type']] ?? const [], msg);

  void fromBrain(Msg msg) => _deliver('brain', kFromBrain[msg['type']] ?? const [], msg);

  /// Voice -> Ears/Spine: playback_state. Ears uses it for half-duplex / barge-in decisions.
  void fromVoice(Msg msg) {
    if (msg['type'] == 'playback_state') {
      _deliver('voice', const ['ears'], msg);
    } else {
      _deliver('voice', const [], msg);
    }
  }

  /// Commit gate C. Hook this to Brain's log lines.
  void onBrainLog(Map<String, dynamic> rec) {
    if (rec['event'] != 'held_valid') return;
    final extra = (rec['extra'] as Map?) ?? const {};
    if (extra['match'] != true) return;
    final t = clock();
    final msg = <String, dynamic>{'type': 'commit', 'turn': rec['turn'], 'gen': extra['gen'], 't': t};
    log.emit('spine', 'commit', rec['turn'] as int?, t: t, extra: {'gen': extra['gen']});
    _deliver('spine', const ['voice'], msg);
  }

  /// Between turns only (contract).
  void setTier(int n) {
    log.emit('spine', 'tier_switch', null, extra: {'to': n});
    for (final s in stages.values) {
      s.setTier(n);
    }
  }
}

/// Voice-side hold-and-release rules (v2.1), kept pure so it is unit-testable:
/// - items for (turn, gen) are held until `commit` for the same turn and gen;
/// - a newer gen for the same turn (or a newer turn) invalidates older gens;
/// - `cancel` for (turn, gen) drops that gen.
/// Items that are not `held` play immediately (still subject to staleness).
class HoldGate<T> {
  int _turn = -1;
  int _gen = -1;
  bool _committed = false;
  final List<T> _held = [];

  int get turn => _turn;
  int get gen => _gen;
  bool get committed => _committed;
  int get heldCount => _held.length;

  /// Offer an item. Returns the items that may play now (possibly empty).
  List<T> offer(int turn, int gen, T item, {required bool held}) {
    if (_isStale(turn, gen)) return const [];
    _adopt(turn, gen);
    if (held && !_committed) {
      _held.add(item);
      return const [];
    }
    return [item];
  }

  /// Commit for (turn, gen). Returns the released items in order.
  List<T> commit(int turn, int gen) {
    if (_isStale(turn, gen)) return const [];
    _adopt(turn, gen);
    _committed = true;
    final out = List<T>.of(_held);
    _held.clear();
    return out;
  }

  /// Cancel for (turn, gen). Returns true if the active gen was dropped.
  bool cancel(int turn, int gen) {
    if (turn == _turn && gen == _gen) {
      _held.clear();
      _committed = false;
      _gen = -1; // nothing active; a later item for the same gen is stale
      _cancelledGen = gen;
      return true;
    }
    return false;
  }

  int _cancelledGen = -1;

  bool _isStale(int turn, int gen) {
    if (turn < _turn) return true;
    if (turn == _turn && gen < _gen) return true;
    if (turn == _turn && gen <= _cancelledGen) return true;
    return false;
  }

  void _adopt(int turn, int gen) {
    if (turn != _turn) {
      _turn = turn;
      _gen = gen;
      _committed = false;
      _held.clear();
      _cancelledGen = -1;
    } else if (gen != _gen) {
      _gen = gen;
      _committed = false;
      _held.clear();
    }
  }
}
