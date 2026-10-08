/// Stage interface from CLAUDE.md / docs/CONTRACT.md: start (load + warm up + ready), feed(msg), stop, setTier.
/// Messages are plain maps with the exact contract fields.
typedef Msg = Map<String, dynamic>;
typedef Send = void Function(Msg msg);

abstract class Stage {
  Future<void> start();
  void feed(Msg msg);
  Future<void> stop();
  void setTier(int n);
}
