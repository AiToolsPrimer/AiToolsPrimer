#!/usr/bin/env bash
# Fetch every model in the registry for the 64 GB profile. ~90 GB of downloads.
set -euo pipefail
export PATH="$HOME/.lmstudio/bin:$PATH"
pip show huggingface_hub >/dev/null 2>&1 || pip install -q huggingface_hub
hf() { python3 -c "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1], local_dir=sys.argv[2] if len(sys.argv)>2 else None)" "$@"; }

echo "== LM Studio models (text, vision, embeddings, safety)"
lms get lmstudio-community/Qwen3.8-27B-MLX-4bit -y
lms get lmstudio-community/Qwen3-VL-8B-Instruct-MLX-4bit -y
lms get Qwen/Qwen3-Embedding-4B-GGUF -y
lms get Qwen/Qwen3Guard-Gen-4B -y

COMFY="${COMFY:-$HOME/ComfyUI/models}"
echo "== Image: Qwen-Image-2512 + Qwen-Image-Edit-2511 (ComfyUI)"
mkdir -p "$COMFY/diffusion_models" "$COMFY/text_encoders" "$COMFY/vae"
hf Qwen/Qwen-Image-2512 "$COMFY/diffusion_models/Qwen-Image-2512"
hf Qwen/Qwen-Image-Edit-2511 "$COMFY/diffusion_models/Qwen-Image-Edit-2511"
echo "   (ComfyUI's Qwen-Image template downloads the matching text encoder and VAE on first run)"

echo "== Video: LTX-2.5 (MLX)"
hf Lightricks/LTX-2.5 "$HOME/models/LTX-2.5"

echo "== Voice: Chatterbox + Kokoro (fetched on first use by their Python packages)"
echo "== Transcription: Parakeet TDT 0.6B v3 (MLX)"
hf mlx-community/parakeet-tdt-0.6b-v3 "$HOME/models/parakeet-tdt-0.6b-v3"

echo "== Music: ACE-Step 1.5 (fetched by ACE-Step on first start)"
echo "Done."
