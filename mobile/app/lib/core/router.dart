/// Intent router, ported (simplified) from brain/router.py: answers common phrases without the LLM.
/// Exact template match, then lead-word strip + time/date/day composed answers, then a conservative fuzzy
/// match (entity agreement + >= 75% template coverage). Simplification vs laptop: no token_set_ratio
/// score; coverage + entity agreement alone decide (stricter templates, so false hits stay rare).
library;

import 'intents.g.dart';

class Intent {
  const Intent({required this.name, required this.clip, required this.say, required this.fuzzy, required this.templates});
  final String name, clip, say;
  final bool fuzzy;
  final List<String> templates;
}

class Route {
  const Route(this.kind, {this.intent, this.clip, this.text});
  final String kind; // cached | composed | llm
  final String? intent, clip, text;
}

const _lead = {'hey', 'hi', 'hello', 'ok', 'okay', 'so', 'um', 'uh', 'please', 'pecko'};
const _filler = {
  'please', 'pecko', 'hey', 'hi', 'hello', 'um', 'uh', 'so', 'okay', 'ok', 'oh', 'well', //
  'just', 'the', 'a', 'there', 'again', 'now', 'yeah', 'very', 'much'
};
const _minCoverage = 0.75;

const _ones = [
  'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', //
  'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'
];
const _tens = {2: 'twenty', 3: 'thirty', 4: 'forty', 5: 'fifty'};
const _months = [
  'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', //
  'November', 'December'
];
const _days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const _ord = [
  '', 'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', //
  'eleventh', 'twelfth', 'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth', 'eighteenth',
  'nineteenth', 'twentieth', 'twenty-first', 'twenty-second', 'twenty-third', 'twenty-fourth', 'twenty-fifth',
  'twenty-sixth', 'twenty-seventh', 'twenty-eighth', 'twenty-ninth', 'thirtieth', 'thirty-first'
];

String _minuteWords(int m) {
  if (m < 20) return _ones[m];
  final t = m ~/ 10, o = m % 10;
  return _tens[t]! + (o > 0 ? '-${_ones[o]}' : '');
}

String timeWords(DateTime dt) {
  final h12 = dt.hour % 12 == 0 ? 12 : dt.hour % 12;
  final String clock;
  if (dt.minute == 0) {
    clock = "${_ones[h12]} o'clock";
  } else if (dt.minute < 10) {
    clock = '${_ones[h12]} oh ${_ones[dt.minute]}';
  } else {
    clock = '${_ones[h12]} ${_minuteWords(dt.minute)}';
  }
  final h = dt.hour;
  final part = h < 5
      ? 'at night'
      : h < 12
          ? 'in the morning'
          : h < 17
              ? 'in the afternoon'
              : h < 21
                  ? 'in the evening'
                  : 'at night';
  return "It's $clock $part.";
}

String dateWords(DateTime dt) => 'Today is ${_days[dt.weekday - 1]}, ${_months[dt.month - 1]} ${_ord[dt.day]}.';
String dayWords(DateTime dt) => "It's ${_days[dt.weekday - 1]}.";

const _tail = r"(?: please| pecko)*";
final _timeRe = RegExp(r"^(?:what time is it(?: right now| now| currently)?|what(?:'s| is) the (?:current )?time"
    r"(?: right now| now)?|tell me the (?:current )?time|current time|time now|what time do you have)"
    '$_tail\$');
final _dateRe = RegExp(r"^(?:what(?:'s| is) (?:the |today's )?date(?: today| is it)?|what date is it(?: today)?"
    r"|today's date|tell me (?:the |today's )?date)"
    '$_tail\$');
final _dayRe = RegExp(r"^(?:what day is (?:it|today)(?: today)?|which day is (?:it|today)|what(?:'s| is) the day"
    r"(?: today)?|what day of the week is it|tell me the day)"
    '$_tail\$');

class Router {
  Router({List<Intent> intents = kIntents, DateTime Function()? clock}) : _clock = clock ?? DateTime.now {
    for (final i in intents) {
      _byName[i.name] = i;
      for (final t in i.templates) {
        _exact[t] = i.name;
      }
      _words[i.name] = {for (final t in i.templates) ...t.split(' ')};
    }
    _fuzzy = intents.where((i) => i.fuzzy).toList();
  }

  final DateTime Function() _clock;
  final Map<String, Intent> _byName = {};
  final Map<String, String> _exact = {};
  final Map<String, Set<String>> _words = {};
  late final List<Intent> _fuzzy;

  Intent? intent(String name) => _byName[name];
  Iterable<Intent> get intents => _byName.values;

  Route _cached(String name) => Route('cached', intent: name, clip: _byName[name]!.clip, text: _byName[name]!.say);

  Route route(String norm) {
    norm = norm.trim();
    if (norm.isEmpty) return _cached('didnt_catch');
    if (_exact.containsKey(norm)) return _cached(_exact[norm]!);

    var words = norm.split(' ');
    while (words.isNotEmpty && _lead.contains(words.first)) {
      words = words.sublist(1);
    }
    final stripped = words.join(' ');
    if (stripped.isNotEmpty) {
      final n = _clock();
      if (_timeRe.hasMatch(stripped)) return Route('composed', intent: 'time', text: timeWords(n));
      if (_dateRe.hasMatch(stripped)) return Route('composed', intent: 'date', text: dateWords(n));
      if (_dayRe.hasMatch(stripped)) return Route('composed', intent: 'day', text: dayWords(n));
      if (_exact.containsKey(stripped)) return _cached(_exact[stripped]!);
    }

    final qwords = norm.split(' ');
    String? best;
    var bestCov = 0.0;
    for (final i in _fuzzy) {
      final allowed = {..._words[i.name]!, ..._filler};
      if (qwords.any((w) => !allowed.contains(w))) continue; // entity agreement
      for (final t in i.templates) {
        final twords = t.split(' ');
        final tfill = _filler.difference(twords.toSet());
        final tcontent = twords.where((w) => !tfill.contains(w)).toSet();
        final qcontent = qwords.where((w) => !tfill.contains(w)).toSet();
        if (tcontent.isEmpty) continue;
        final cov = qcontent.intersection(tcontent).length / tcontent.length;
        // also require the query not to carry many extra content words (stand-in for token_set_ratio)
        final extra = qcontent.difference(tcontent).length;
        if (cov >= _minCoverage && extra <= 1 && cov > bestCov) {
          bestCov = cov;
          best = i.name;
        }
      }
    }
    if (best != null) return _cached(best);
    return const Route('llm');
  }
}
