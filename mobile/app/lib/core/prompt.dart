/// Byte-stable prompts, ported from brain/prompt.py. The KV cache is reused only for an identical
/// byte prefix, so the system prompt never changes and history is append-only between block trims.
library;

const String kSystemPrompt =
    "You are Pecko, an offline voice assistant running on this device. "
    "Answer in one or two short spoken sentences. Give the answer first, then at most one short reason. "
    "No lists, no markdown, no symbols, no emoji. Spell out numbers in words. "
    "If you don't know, say so in one sentence. "
    "You are offline and cannot browse, check live data or open apps.";

// keep letters/digits/apostrophes/underscore (Python \w) + Devanagari and Tamil blocks
final RegExp _punct = RegExp(r"[^\p{L}\p{N}_\s'ऀ-ॿ஀-௿]", unicode: true);

String normalize(String text) =>
    text.toLowerCase().replaceAll(_punct, ' ').split(RegExp(r'\s+')).where((w) => w.isNotEmpty).join(' ');

class Template {
  const Template(this.system, this.userOpen, this.userClose, this.assistantOpen, this.assistantClose);
  final String system; // contains {sys}
  final String userOpen, userClose, assistantOpen, assistantClose;
}

const Map<String, Template> kTemplates = {
  // Qwen3 non-thinking: pre-fill an empty think block so there are no silent "thinking" seconds
  'qwen3': Template('<|im_start|>system\n{sys}<|im_end|>\n', '<|im_start|>user\n', '<|im_end|>\n',
      '<|im_start|>assistant\n<think>\n\n</think>\n\n', '<|im_end|>\n'),
  // LFM2: BOS is added by llama-server's tokenizer
  'lfm2': Template('<|im_start|>system\n{sys}<|im_end|>\n', '<|im_start|>user\n', '<|im_end|>\n',
      '<|im_start|>assistant\n', '<|im_end|>\n'),
};

class PromptBuilder {
  PromptBuilder({this.family = 'qwen3', String system = kSystemPrompt, this.maxTurns = 3, this.keepAfterTrim = 1})
      : _systemText = system,
        t = kTemplates[family]!,
        _system = kTemplates[family]!.system.replaceAll('{sys}', system);

  final String family;
  final int maxTurns;
  final int keepAfterTrim;
  final Template t;
  final String _systemText;
  final String _system;
  final List<(String, String)> _turns = [];

  String get systemText => _systemText;
  int get nTurns => _turns.length;

  String base() {
    final b = StringBuffer(_system);
    for (final (user, reply) in _turns) {
      b
        ..write(t.userOpen)
        ..write(user)
        ..write(t.userClose)
        ..write(t.assistantOpen)
        ..write(reply)
        ..write(t.assistantClose);
    }
    return b.toString();
  }

  /// Early-prefill prompt: user turn still open, so this is a byte prefix of final().
  String partial(String user) => base() + t.userOpen + user;

  String finalPrompt(String user) => partial(user) + t.userClose + t.assistantOpen;

  /// Append a turn. On overflow cut history to the last [keepAfterTrim] turns in one block; returns true.
  bool addTurn(String user, String reply) {
    _turns.add((user, reply));
    if (_turns.length <= maxTurns) return false;
    final keep = keepAfterTrim < maxTurns ? keepAfterTrim : maxTurns;
    _turns.removeRange(0, _turns.length - keep);
    return true;
  }

  void clear() => _turns.clear();
}
