#!/usr/bin/env bash
# One-shot setup for a Mac with Apple Silicon (tested target: Mac mini M5 Pro, 64 GB).
# Installs the tools, the Python environment and the local AI runtimes. Models are
# fetched by scripts/download_models.sh. Nothing here costs money.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Homebrew packages"
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
brew install ffmpeg python@3.12 git uv espeak-ng || true
brew install --cask lm-studio || true

echo "== LM Studio CLI (lms)"
if ! command -v lms >/dev/null; then
  if [ -x "$HOME/.lmstudio/bin/lms" ]; then
    echo 'export PATH="$HOME/.lmstudio/bin:$PATH"' >> "$HOME/.zshrc"
    export PATH="$HOME/.lmstudio/bin:$PATH"
  else
    echo "Open LM Studio once, then run:  ~/.lmstudio/bin/lms bootstrap"
  fi
fi

echo "== Python environment"
uv venv .venv --python 3.12 || python3.12 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
uv pip install -e ".[dev]" || pip install -e ".[dev]"

echo "== Apple-Silicon inference packages"
uv pip install mlx mlx-lm mlx-whisper parakeet-mlx chatterbox-tts kokoro soundfile torch torchaudio || true
# LTX-2.5 on MLX: community package, see docs/MODELS.md for the current repo
uv pip install ltx-mlx || echo "ltx-mlx not on PyPI yet: follow docs/MODELS.md (LTX-2.5 section)"

echo "== ComfyUI (image, image edit, avatar; optional video)"
if [ ! -d "$HOME/ComfyUI" ]; then
  git clone https://github.com/comfyanonymous/ComfyUI "$HOME/ComfyUI"
  (cd "$HOME/ComfyUI" && uv venv .venv --python 3.12 && source .venv/bin/activate && uv pip install torch torchvision torchaudio && uv pip install -r requirements.txt)
  git clone https://github.com/noreff/ComfyUI-LTX-MLX-A2V "$HOME/ComfyUI/custom_nodes/ComfyUI-LTX-MLX-A2V" || true
fi

echo "== ACE-Step 1.5 (music)"
if [ ! -d "$HOME/ACE-Step-1.5" ]; then
  git clone https://github.com/ace-step/ACE-Step-1.5 "$HOME/ACE-Step-1.5"
  (cd "$HOME/ACE-Step-1.5" && uv venv .venv --python 3.12 && source .venv/bin/activate && uv pip install -e .) || true
fi

echo "== Raise the GPU memory limit to 56 GB (reverts at reboot; add to /etc/sysctl.conf to keep)"
sudo sysctl iogpu.wired_limit_mb=57344 || true

echo "== Agency config"
.venv/bin/agency init || true
echo
echo "Done. Next:"
echo "  1. scripts/download_models.sh"
echo "  2. Start LM Studio (server on :1234), ComfyUI (:8188), ACE-Step (:7867)"
echo "  3. .venv/bin/agency doctor"
echo "  4. .venv/bin/agency run   ->  http://127.0.0.1:8765"
