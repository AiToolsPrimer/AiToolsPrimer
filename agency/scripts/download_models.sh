#!/usr/bin/env bash
# Fetch every model of the 64 GB one-model-at-a-time lineup into ONE folder (about 260 GB;
# about 300 GB with the options below).  The folder can be on an external SSD.
#
#   AGENCY_MODELS=/Volumes/AI/models scripts/download_models.sh      (or put AGENCY_MODELS in .env)
#   LTX_FULL=1       also fetch the LTX-2.5 dev transformer + LoRA (two-stage video, +29 GB)
#   DRAFT_LANE=1     also fetch Qwen3.8-27B 4-bit for the optional fast draft lane (+16 GB)
#   SKIP_LMSTUDIO=1  skip the LM Studio downloads (do them in the app)
#
# Layout (see agency/models/paths.py): <models>/hf (Hugging Face cache, used by llama.cpp, mflux,
# ltx-2-mlx, mlx-speech, Kokoro, Parakeet), <models>/lmstudio (LM Studio), <models>/comfyui (ComfyUI).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.lmstudio/bin:$HOME/.local/bin:$PATH"

# ---- where
if [ -z "${AGENCY_MODELS:-}" ] && [ -f .env ]; then
  AGENCY_MODELS="$(grep -E '^AGENCY_MODELS=' .env | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" || true)"
fi
MODELS="${MODELS:-${AGENCY_MODELS:-$HOME/models}}"
MODELS="${MODELS/#\~/$HOME}"
case "$MODELS" in
  /Volumes/*)
    VOL="/Volumes/$(echo "$MODELS" | cut -d/ -f3)"
    if ! mount | grep -q " on $VOL "; then
      echo "!! $VOL is not mounted. Plug in the SSD (or fix AGENCY_MODELS) and run again."; exit 1
    fi
    echo "== Models disk: $MODELS (external SSD $VOL)";;
  *) echo "== Models folder: $MODELS";;
esac
mkdir -p "$MODELS/hf" "$MODELS/llama.cpp" "$MODELS/lmstudio" "$MODELS/comfyui"
export HF_HOME="$MODELS/hf" HF_HUB_CACHE="$MODELS/hf/hub" LLAMA_CACHE="$MODELS/llama.cpp"
export HF_HUB_ENABLE_HF_TRANSFER=0

NEED=260
if [ "${LTX_FULL:-0}" = 1 ]; then NEED=$((NEED+29)); fi
if [ "${DRAFT_LANE:-0}" = 1 ]; then NEED=$((NEED+16)); fi
FREE=$(df -g "$MODELS" | awk 'NR==2{print $4}')
echo "   free: ${FREE} GB, needed for what is not there yet: up to ${NEED} GB"
if [ "${FREE:-0}" -lt 40 ]; then echo "!! Less than 40 GB free on $MODELS: make room or pick another disk."; exit 1; fi

# ---- Python with huggingface_hub (the agency venv if present)
PY=".venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
"$PY" -c "import huggingface_hub" 2>/dev/null || "$PY" -m pip install -q huggingface_hub
hf() {  # hf <repo> [allow_patterns,comma,separated]  -> into the Hugging Face cache under $MODELS/hf
  "$PY" - "$@" <<'PYEOF'
import sys
from huggingface_hub import snapshot_download
repo = sys.argv[1]
allow = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] else None
path = snapshot_download(repo, allow_patterns=allow, max_workers=4)
print("   ->", path)
PYEOF
}

echo "== Brain A: Qwen3.8-Flash-Next, UD-IQ4_XS shards + vision projector (94.6 GB; the 50 GB n-gram shard stays on this disk at run time)"
hf unsloth/Qwen3.8-Flash-Next-GGUF "UD-IQ4_XS/*,mmproj-BF16.gguf,*.json,README.md"

echo "== Images: Qwen-Image-2512 8-bit MLX for mflux (36.1 GB)"
hf mlx-community/Qwen-Image-2512-8bit

echo "== Video: LTX-2.5 int8 MLX pack for ltx-2-mlx (45.2 GB distilled; LTX_FULL=1 adds the dev transformer + LoRA)"
if [ "${LTX_FULL:-0}" = 1 ]; then hf dgrauet/ltx-2.5-mlx-q8; else hf dgrauet/ltx-2.5-mlx-q8 "transformer-distilled.safetensors,text_encoder*,connector.safetensors,vae_*,audio_vae.safetensors,vocoder.safetensors,spatial_upscaler*,temporal_upscaler*,duration_head.safetensors,*.json,*.md,*.txt,*.model,tokenizer*"; fi

echo "== Voice: Step-Audio-EditX int8 MLX (4.4 GB; mlx-speech reads it from this cache)"
hf appautomaton/step-audio-editx-8bit-mlx
echo "== Voice fallback: Kokoro 82M (0.4 GB)"
hf hexgrad/Kokoro-82M "*.pth,*.json,*.md,voices/*" || true
echo "== Transcription: Parakeet TDT 0.6B v2 (2.5 GB)"
hf mlx-community/parakeet-tdt-0.6b-v2

echo "== Image editing for ComfyUI: Qwen-Image-Edit-2511 Q8_0 (21.8 GB) + Qwen2.5-VL text encoder fp8 (9.4 GB) + VAE"
COMFY="$MODELS/comfyui"; mkdir -p "$COMFY/unet" "$COMFY/diffusion_models" "$COMFY/text_encoders" "$COMFY/vae" "$COMFY/loras"
"$PY" - "$COMFY" <<'PYEOF'
import sys
from pathlib import Path
from huggingface_hub import hf_hub_download
comfy = Path(sys.argv[1])
hf_hub_download("unsloth/Qwen-Image-Edit-2511-GGUF", "qwen-image-edit-2511-Q8_0.gguf", local_dir=comfy / "unet")
hf_hub_download("Comfy-Org/Qwen-Image_ComfyUI", "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", local_dir=comfy / "_tmp")
hf_hub_download("Comfy-Org/Qwen-Image_ComfyUI", "split_files/vae/qwen_image_vae.safetensors", local_dir=comfy / "_tmp")
for src, dst in ((comfy / "_tmp/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", comfy / "text_encoders"), (comfy / "_tmp/split_files/vae/qwen_image_vae.safetensors", comfy / "vae")):
    dst.mkdir(parents=True, exist_ok=True)
    target = dst / src.name
    if not target.exists():
        src.replace(target)
print("   -> ComfyUI models in", comfy)
PYEOF
if [ -d "$HOME/ComfyUI" ]; then
  "$PY" -c "from pathlib import Path; from agency.models.paths import comfy_extra_paths_yaml; Path.home().joinpath('ComfyUI/extra_model_paths.yaml').write_text(comfy_extra_paths_yaml(Path('$MODELS')))" \
    && echo "   -> ~/ComfyUI/extra_model_paths.yaml points ComfyUI at $COMFY" || echo "   (write ~/ComfyUI/extra_model_paths.yaml by hand: base_path $COMFY)"
fi

# ---- LM Studio: the 27B, embeddings and the safety model live in LM Studio's own models directory
if [ "${SKIP_LMSTUDIO:-0}" != 1 ]; then
  echo "== LM Studio models (27B second pen, embeddings, safety)"
  if ! command -v lms >/dev/null; then echo "!! lms not found: open LM Studio once, run ~/.lmstudio/bin/lms bootstrap, then rerun this script"; exit 1; fi
  if [ "$MODELS" != "$HOME/models" ] || [ ! -d "$HOME/.lmstudio/models" ]; then
    if [ -L "$HOME/.lmstudio/models" ] || [ ! -d "$HOME/.lmstudio/models" ] || [ -z "$(ls -A "$HOME/.lmstudio/models" 2>/dev/null)" ]; then
      rm -rf "$HOME/.lmstudio/models"; ln -sfn "$MODELS/lmstudio" "$HOME/.lmstudio/models"
      echo "   ~/.lmstudio/models -> $MODELS/lmstudio (LM Studio follows the link; or set My Models > Models Directory to that folder)"
    else
      echo "!! LM Studio already has models in ~/.lmstudio/models. In LM Studio open My Models > Models Directory and choose $MODELS/lmstudio, then rerun with SKIP_LMSTUDIO=0."
      echo "   Continuing with the downloads into the current LM Studio directory."
    fi
  fi
  lms get "lmstudio-community/Qwen3.8-27B-MLX-8bit" -y || lms get "malekoo/Qwen3.8-27B-MLX-8bit" -y
  if [ "${DRAFT_LANE:-0}" = 1 ]; then lms get "lmstudio-community/Qwen3.8-27B-MLX-4bit" -y; fi
  lms get "Qwen/Qwen3-Embedding-8B-GGUF@q8_0" -y || lms get "Qwen/Qwen3-Embedding-8B-GGUF" -y
  lms get "mradermacher/Qwen3Guard-Gen-4B-GGUF@q8_0" -y || lms get "mradermacher/Qwen3Guard-Gen-4B-GGUF" -y
fi

echo "== Music: ACE-Step 1.5 fetches its own weights on first start (a few GB, inside ~/ACE-Step-1.5)"
echo "Done. Models on $MODELS. Next: .venv/bin/agency doctor --benchmark"
