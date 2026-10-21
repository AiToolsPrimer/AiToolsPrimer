#!/usr/bin/env bash
# Fetch every model in the registry for the 64 GB one-model-at-a-time profile (about 130 GB).
set -euo pipefail
export PATH="$HOME/.lmstudio/bin:$PATH"
pip show huggingface_hub >/dev/null 2>&1 || pip install -q huggingface_hub
hf() { python3 -c "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1], local_dir=sys.argv[2] if len(sys.argv)>2 else None, allow_patterns=sys.argv[3].split(',') if len(sys.argv)>3 else None)" "$@"; }
MODELS="${MODELS:-$HOME/models}"; mkdir -p "$MODELS"

echo "== Brain A: Qwen3.8-Flash-Next (~4-bit GGUF, n-gram table stays on the SSD)"
hf unsloth/Qwen3.8-Flash-Next-GGUF "$MODELS/Qwen3.8-Flash-Next-GGUF" "*UD-IQ4_XS*,*.json,*ngram*,*mmproj*" || echo "  (if the repo layout changed, see docs/MODELS.md)"
echo "== Brain B / second pen: Qwen3.8-27B 8-bit and 4-bit (LM Studio)"
lms get malekoo/Qwen3.8-27B-MLX-8bit -y || lms get lmstudio-community/Qwen3.8-27B-MLX-8bit -y || true
lms get lmstudio-community/Qwen3.8-27B-MLX-4bit -y
echo "== Embeddings and safety"
lms get Qwen/Qwen3-Embedding-8B-GGUF -y || lms get Qwen/Qwen3-Embedding-4B-GGUF -y
lms get Qwen/Qwen3Guard-Gen-4B -y

echo "== Images: Qwen-Image-2512 8-bit (MLX, mflux)"
hf mlx-community/Qwen-Image-2512-8bit "$MODELS/Qwen-Image-2512-8bit"
COMFY="${COMFY:-$HOME/ComfyUI/models}"; mkdir -p "$COMFY/diffusion_models" "$COMFY/unet"
echo "== Image editing: Qwen-Image-Edit-2511 GGUF Q8 (ComfyUI-GGUF)"
hf QuantStack/Qwen-Image-Edit-2511-GGUF "$COMFY/unet/Qwen-Image-Edit-2511-GGUF" "*Q8_0*" || echo "  (pick the Q8 GGUF of Qwen-Image-Edit-2511 on Hugging Face into $COMFY/unet)"

echo "== Video: LTX-2.5 (bf16, MLX)"
hf Lightricks/LTX-2.5 "$MODELS/LTX-2.5"

echo "== Voice: Step-Audio-EditX MLX int8 (Kokoro and Chatterbox are fetched by their packages on first use)"
hf appautomaton/step-audio-editx-8bit-mlx "$MODELS/step-audio-editx-8bit-mlx"
echo "== Transcription: Parakeet TDT 0.6B v2 (MLX)"
hf mlx-community/parakeet-tdt-0.6b-v2 "$MODELS/parakeet-tdt-0.6b-v2"
echo "== Music: ACE-Step 1.5 (fetched by ACE-Step on first start)"
echo "Done. Run: agency doctor --benchmark"
