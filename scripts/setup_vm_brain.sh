#!/usr/bin/env bash
# One-shot, re-runnable setup of the Brain stage on the Ubuntu VM.
# Run from a git clone (NOT a shared folder):  bash scripts/setup_vm_brain.sh
# Every step is skipped if already done.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"
LLAMA_TAG="b11501"
LLAMA_TGZ="llama-${LLAMA_TAG}-bin-ubuntu-x64.tar.gz"
LLAMA_DIR="models/llama.cpp/${LLAMA_TAG}-ubuntu"
step() { printf '\n== %s\n' "$*"; }

step "1/8 apt dependencies"
need=()
for p in python3-venv python3-pip git curl unzip gh; do
  dpkg -s "$p" >/dev/null 2>&1 || need+=("$p")
done
if [ "${#need[@]}" -gt 0 ]; then
  sudo apt-get update
  sudo apt-get install -y "${need[@]}"
else
  echo "all present"
fi

step "2/8 AVX2 check (gotcha G9)"
if grep -q -m1 avx2 /proc/cpuinfo; then
  echo "AVX2 present"
else
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "!! NO AVX2 in this VM: llama.cpp will be very slow, numbers meaningless !!"
  echo "!! Likely cause: Hyper-V / WSL2 / Memory Integrity is on in Windows, so  !!"
  echo "!! VirtualBox runs in a slow mode and hides AVX2. Fix on the Windows     !!"
  echo "!! host: 'bcdedit /set hypervisorlaunchtype off', disable Windows        !!"
  echo "!! features Hyper-V / Virtual Machine Platform, reboot, retry. Also give !!"
  echo "!! the VM >= 4 vCPUs and >= 6 GB RAM.                                    !!"
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
fi

step "3/8 RAPL (energy counters)"
if ls /sys/class/powercap 2>/dev/null | grep -q .; then
  ls /sys/class/powercap
else
  echo "no /sys/class/powercap: no RAPL in this VM; Spine must label energy 'not joules'"
fi

step "4/8 Python venv + requirements"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q -r brain/requirements.txt
echo "python: $(python --version)"

step "5/8 llama.cpp ${LLAMA_TAG} (ubuntu-x64)"
if [ -n "$(find "$LLAMA_DIR" -name llama-server -type f 2>/dev/null | head -1)" ]; then
  echo "already installed in $LLAMA_DIR"
else
  mkdir -p models/llama.cpp "$LLAMA_DIR"
  if [ ! -f "models/llama.cpp/$LLAMA_TGZ" ]; then
    # gh needs no login for public release downloads; curl is the fallback
    (cd models/llama.cpp && { gh release download "$LLAMA_TAG" -R ggml-org/llama.cpp -p "$LLAMA_TGZ" \
      || curl -fL -O "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_TAG}/${LLAMA_TGZ}"; })
  fi
  tar xzf "models/llama.cpp/$LLAMA_TGZ" -C "$LLAMA_DIR"
fi
find "$LLAMA_DIR" -name llama-server -type f | head -1 | xargs -r -I{} sh -c 'chmod +x "{}"; echo "llama-server: {}"'

step "6/8 Qwen3-0.6B GGUF (Q4_K_M + Q8_0)"
if ! command -v hf >/dev/null 2>&1; then
  pip install -q "huggingface_hub[cli]"
fi
mkdir -p models
for f in Qwen3-0.6B-Q4_K_M.gguf Qwen3-0.6B-Q8_0.gguf; do
  if [ -s "models/$f" ]; then
    echo "have $f"
  else
    hf download unsloth/Qwen3-0.6B-GGUF "$f" --local-dir models
  fi
done

step "7/8 sha256 (paste into brain/RESULTS.md header)"
sha256sum models/*.gguf

step "8/8 tests"
python -m pytest -q tests/common tests/brain -k "not live"

echo
echo "Setup done in $ROOT"
