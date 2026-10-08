/// Cut a streamed reply into speakable chunks for Voice. Port of brain/chunker.py (same rules):
/// First chunk: first , . ? ! ; : after >= 2 words, or after 6 pieces at a word boundary.
/// Later chunks: at . ? ! ; or at , : once the chunk has >= 4 words; never more than 25 words.
/// Punctuation glued to the next character (3.5, 1,000, 3:45) is never a cut; a '.' ',' or ':' right
/// after a digit at the end of the buffer waits one piece (it may become 3.5).
library;

const String _cuts = ',.?!;:';
const String _sentenceEnd = '.?!;';
const int kMaxWords = 25;

int _words(String s) => s.trim().isEmpty ? 0 : s.trim().split(RegExp(r'\s+')).length;
bool _isSpace(String c) => c.trim().isEmpty;
bool _isDigit(String c) => c.codeUnitAt(0) >= 48 && c.codeUnitAt(0) <= 57;

int _lastSpaceCut(String buf) {
  final i = buf.lastIndexOf(' ');
  return i <= 0 ? buf.length : i + 1;
}

class Chunker {
  Chunker({this.firstMinWords = 2, this.firstMaxPieces = 6, this.laterCommaWords = 4, bool firstDone = false})
      : chunksOut = firstDone ? 1 : 0;

  final int firstMinWords, firstMaxPieces, laterCommaWords;
  int chunksOut;
  String _buf = '';
  int _pieces = 0;

  List<String> push(String piece) {
    if (piece.isEmpty) return const [];
    _buf += piece;
    _pieces += 1;
    final out = <String>[];
    int? cut;
    while ((cut = _findCut()) != null) {
      out.add(_buf.substring(0, cut));
      _buf = _buf.substring(cut!);
      chunksOut += 1;
    }
    return out;
  }

  String? flush() {
    final rest = _buf;
    _buf = '';
    if (rest.trim().isNotEmpty) {
      chunksOut += 1;
      return rest;
    }
    return null;
  }

  int? _findCut() {
    final buf = _buf;
    final first = chunksOut == 0;
    for (var i = 0; i < buf.length; i++) {
      final ch = buf[i];
      if (!_cuts.contains(ch)) continue;
      final atEnd = i == buf.length - 1;
      if (!atEnd && !_isSpace(buf[i + 1])) continue;
      if (atEnd && '.,:'.contains(ch) && i > 0 && _isDigit(buf[i - 1])) return null;
      final words = _words(buf.substring(0, i + 1));
      if (first) {
        if (words >= firstMinWords) return i + 1;
      } else if (_sentenceEnd.contains(ch) || words >= laterCommaWords) {
        return i + 1;
      }
    }
    final nWords = _words(buf);
    if (first && _pieces >= firstMaxPieces && nWords >= firstMinWords) {
      final cut = _lastSpaceCut(buf);
      return _words(buf.substring(0, cut)) >= firstMinWords ? cut : null;
    }
    if (!first && nWords > kMaxWords) return _lastSpaceCut(buf);
    return null;
  }
}
