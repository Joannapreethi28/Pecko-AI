#!/usr/bin/env bash
# One-shot, idempotent model + dependency setup. Run from repo root WITH network.
# After this, nothing downloads at runtime (use HF_HUB_OFFLINE=1).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || python3 -m venv .venv

# 1. Python deps. torch = CPU-only wheel (no CUDA), rest from the pinned files.
if ! $PY -c "import torch,sys;sys.exit('+cpu' not in torch.__version__)" 2>/dev/null; then
  $PY -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.10.0
fi
TMPREQ="$(mktemp)"; grep -v '^torch==' requirements.txt > "$TMPREQ"
$PY -m pip install -r "$TMPREQ" -r frontend/requirements.txt -r voice/requirements.txt

# 2. Voice (Piper lessac low/medium, fp32/fp16/int8)
$PY voice/get_models.py

# 3. Ears models
B=https://github.com/k2-fsa/sherpa-onnx/releases/download
mkdir -p models/zipformer_asr models/sherpa_kws models/smart_turn models/vosk
Z=models/zipformer_asr/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17
[ -d "$Z" ] || curl -fL "$B/asr-models/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17.tar.bz2" | tar xj -C models/zipformer_asr

K=models/sherpa_kws/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01
[ -d "$K" ] || curl -fL "$B/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2" | tar xj -C models/sherpa_kws
# Wake phrase "HEY PECKO" as BPE pieces from the model's own bpe.model
printf '▁HE Y ▁P E CK O\n' > "$K/pecko_keywords.txt"

V=models/vosk/vosk-model-small-en-in-0.4
if [ ! -d "$V" ]; then
  curl -fL https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip -o models/vosk/_v.zip
  $PY -c "import zipfile;zipfile.ZipFile('models/vosk/_v.zip').extractall('models/vosk')"
  rm -f models/vosk/_v.zip
fi

# Smart-turn: HF repo has no *-int8 file; v3.2-cpu.onnx (8.7 MB) is the int8 CPU build.
[ -f models/smart_turn/smart-turn-v3.2-int8.onnx ] || $PY - <<'PY'
from huggingface_hub import hf_hub_download
import shutil
p = hf_hub_download("pipecat-ai/smart-turn-v3", "smart-turn-v3.2-cpu.onnx")
shutil.copy(p, "models/smart_turn/smart-turn-v3.2-int8.onnx")
PY

# Moonshine Small + Tiny streaming -> ~/.cache/moonshine_voice (lazy-downloaded otherwise)
$PY - <<'PY'
from moonshine_voice import get_model_for_language, ModelArch
for a in (ModelArch.SMALL_STREAMING, ModelArch.TINY_STREAMING):
    print(get_model_for_language("en", a, include_word_timestamps=True))
PY

# silero-vad ships inside the pip package; verify it loads
$PY -c "from silero_vad import load_silero_vad; load_silero_vad(onnx=True); print('silero ok')"
echo "setup_models: done"
