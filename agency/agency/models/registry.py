"""Which model does which job, on which hardware.

Everything here was chosen against independent leaderboards (Artificial Analysis,
Arena, MTEB, Open ASR Leaderboard) and the official model cards, with two hard
filters: it must run on Apple Silicon, and its licence must allow commercial use.
See docs/MODELS.md for the evidence behind each row.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Runtime = Literal["lmstudio", "comfyui", "mlx-cli", "python-script", "http"]


@dataclass(frozen=True)
class ModelSpec:
    id: str                       # identifier the runtime understands
    name: str
    runtime: Runtime
    memory_gb: float              # approximate resident memory at the default quantisation
    license: str
    notes: str = ""
    command: str = ""             # for mlx-cli / python-script runtimes: template with {placeholders}


@dataclass(frozen=True)
class TaskAssignment:
    task: str
    primary: ModelSpec
    alternates: tuple[ModelSpec, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------------- models

QWEN38_27B = ModelSpec(
    id="lmstudio-community/Qwen3.8-27B-MLX-4bit",
    name="Qwen3.8-27B",
    runtime="lmstudio",
    memory_gb=17,
    license="Apache-2.0",
    notes="Strongest small open model on the AA Intelligence Index (34); dense, multimodal (image+video in), 262K context.",
)
QWEN38_FLASH_NEXT = ModelSpec(
    id="Qwen/Qwen3.8-Flash-Next",
    name="Qwen3.8-Flash-Next",
    runtime="lmstudio",
    memory_gb=100,
    license="Qwen Community License 1.0 (commercial OK)",
    notes="AA index 39.8; 125B+ MoE, 6B active. Needs a dedicated 128 GB machine; not for the 64 GB profile.",
)
QWEN3_VL_8B = ModelSpec(
    id="lmstudio-community/Qwen3-VL-8B-Instruct-MLX-4bit",
    name="Qwen3-VL-8B",
    runtime="lmstudio",
    memory_gb=6,
    license="Apache-2.0",
    notes="Light vision worker for quality checks on generated images and screenshots.",
)
QWEN3_EMBED_4B = ModelSpec(
    id="Qwen/Qwen3-Embedding-4B-GGUF",
    name="Qwen3-Embedding-4B",
    runtime="lmstudio",
    memory_gb=3,
    license="Apache-2.0",
    notes="Multilingual embeddings for the agency memory (brand knowledge, past posts, metrics).",
)
QWEN3_EMBED_06B = ModelSpec(
    id="Qwen/Qwen3-Embedding-0.6B-GGUF",
    name="Qwen3-Embedding-0.6B",
    runtime="lmstudio",
    memory_gb=1,
    license="Apache-2.0",
)
QWEN3_GUARD = ModelSpec(
    id="Qwen/Qwen3Guard-Gen-4B",
    name="Qwen3Guard-Gen-4B",
    runtime="lmstudio",
    memory_gb=3,
    license="Apache-2.0",
    notes="Content safety classifier run before anything is published.",
)

QWEN_IMAGE_2512 = ModelSpec(
    id="mlx-community/Qwen-Image-2512-4bit",
    name="Qwen-Image-2512",
    runtime="comfyui",
    memory_gb=14,
    license="Apache-2.0",
    notes="Best permissively licensed model on Arena text-to-image (1125 Elo). Excellent in-image text. Qwen-Image-2.1 scores higher but is research-only.",
)
HIDREAM_O1 = ModelSpec(
    id="HiDream-ai/HiDream-O1-Image",
    name="HiDream-O1-Image",
    runtime="comfyui",
    memory_gb=16,
    license="MIT",
    notes="Arena 1116 Elo; alternate style.",
)
Z_IMAGE_TURBO = ModelSpec(
    id="Tongyi-MAI/Z-Image-Turbo",
    name="Z-Image-Turbo",
    runtime="comfyui",
    memory_gb=8,
    license="Apache-2.0",
    notes="Fast 6B model for drafts, thumbnails and bulk variants.",
)
QWEN_IMAGE_EDIT_2511 = ModelSpec(
    id="Qwen/Qwen-Image-Edit-2511",
    name="Qwen-Image-Edit-2511",
    runtime="comfyui",
    memory_gb=14,
    license="Apache-2.0",
    notes="Top commercially usable model on the Arena image-edit board (1235 Elo).",
)
FLUX2_KLEIN_4B = ModelSpec(
    id="black-forest-labs/FLUX.2-klein-4B",
    name="FLUX.2 klein 4B",
    runtime="comfyui",
    memory_gb=8,
    license="Apache-2.0",
)

LTX_25 = ModelSpec(
    id="Lightricks/LTX-2.5",
    name="LTX-2.5",
    runtime="mlx-cli",
    memory_gb=24,
    license="LTX-2.x Community (free under $10M revenue)",
    notes="Second open model on the AA video board; native audio; MLX port runs a 5 s clip in well under a minute on M5-class chips. Wan 2.2 is unusable on Apple Silicon (no FP8 on Metal).",
    command="{python} -m ltx_mlx generate --prompt {prompt} --output {out} --width {width} --height {height} --num-frames {frames} --fps {fps} --seed {seed}",
)
HUNYUAN_VIDEO_15 = ModelSpec(
    id="tencent/HunyuanVideo-1.5",
    name="HunyuanVideo 1.5",
    runtime="comfyui",
    memory_gb=20,
    license="Tencent Community",
    notes="Only worth it on an NVIDIA box; kept as an alternate for a Linux render node.",
)
LTX_A2V = ModelSpec(
    id="noreff/ComfyUI-LTX-MLX-A2V",
    name="LTX MLX audio-to-video",
    runtime="comfyui",
    memory_gb=24,
    license="LTX-2.x Community",
    notes="One photo + one audio track -> a presenter that speaks, on Apple Silicon.",
)
LATENTSYNC_MLX = ModelSpec(
    id="sb1992/latentsync-mlx",
    name="LatentSync MLX",
    runtime="python-script",
    memory_gb=8,
    license="Apache-2.0",
    notes="Re-sync lips on an existing video.",
)

CHATTERBOX = ModelSpec(
    id="ResembleAI/chatterbox",
    name="Chatterbox",
    runtime="python-script",
    memory_gb=3,
    license="MIT",
    notes="English-native voice with 5-second cloning and emotion control. Primary for English voiceover.",
    command="{python} scripts/tts_chatterbox.py --text-file {text} --out {out} --voice {voice}",
)
KOKORO = ModelSpec(
    id="hexgrad/Kokoro-82M",
    name="Kokoro 82M",
    runtime="python-script",
    memory_gb=0.5,
    license="Apache-2.0",
    notes="Speech Arena 1062 Elo, CPU-fast; preset voices, ideal for long narration.",
    command="{python} scripts/tts_kokoro.py --text-file {text} --out {out} --voice {voice}",
)
QWEN3_TTS = ModelSpec(
    id="Qwen/Qwen3-TTS-1.7B",
    name="Qwen3-TTS 1.7B",
    runtime="python-script",
    memory_gb=4,
    license="Apache-2.0",
    notes="Multilingual fallback (10 languages) with 3-second cloning.",
    command="{python} scripts/tts_qwen3.py --text-file {text} --out {out} --voice {voice}",
)

PARAKEET_V3 = ModelSpec(
    id="mlx-community/parakeet-tdt-0.6b-v3",
    name="Parakeet TDT 0.6B v3",
    runtime="mlx-cli",
    memory_gb=2,
    license="CC-BY-4.0",
    notes="Top English accuracy on the Open ASR Leaderboard at very high speed; subtitles and transcripts.",
    command="parakeet-mlx {audio} --model {model} --output-format srt --output-dir {out_dir}",
)
WHISPER_V3 = ModelSpec(
    id="mlx-community/whisper-large-v3-mlx",
    name="Whisper large-v3",
    runtime="mlx-cli",
    memory_gb=3,
    license="MIT",
    command="mlx_whisper {audio} --model {model} --output-format srt --output-dir {out_dir}",
)

ACE_STEP_15 = ModelSpec(
    id="ACE-Step/Ace-Step1.5",
    name="ACE-Step 1.5",
    runtime="http",
    memory_gb=4,
    license="MIT (commercial use of outputs explicitly granted)",
    notes="Runs natively on Mac; full tracks with or without vocals for video beds.",
)


# ----------------------------------------------------------------------------- tasks

ASSIGNMENTS: dict[str, TaskAssignment] = {
    "director":   TaskAssignment("director", QWEN38_27B, (QWEN38_FLASH_NEXT,)),
    "writer":     TaskAssignment("writer", QWEN38_27B),
    "coder":      TaskAssignment("coder", QWEN38_27B),
    "vision":     TaskAssignment("vision", QWEN38_27B, (QWEN3_VL_8B,)),
    "vision_lite": TaskAssignment("vision_lite", QWEN3_VL_8B),
    "embeddings": TaskAssignment("embeddings", QWEN3_EMBED_4B, (QWEN3_EMBED_06B,)),
    "safety":     TaskAssignment("safety", QWEN3_GUARD),
    "image":      TaskAssignment("image", QWEN_IMAGE_2512, (HIDREAM_O1, Z_IMAGE_TURBO)),
    "image_fast": TaskAssignment("image_fast", Z_IMAGE_TURBO, (FLUX2_KLEIN_4B,)),
    "image_edit": TaskAssignment("image_edit", QWEN_IMAGE_EDIT_2511, (FLUX2_KLEIN_4B,)),
    "video":      TaskAssignment("video", LTX_25, (HUNYUAN_VIDEO_15,)),
    "avatar":     TaskAssignment("avatar", LTX_A2V, (LATENTSYNC_MLX,)),
    "tts":        TaskAssignment("tts", CHATTERBOX, (KOKORO, QWEN3_TTS)),
    "asr":        TaskAssignment("asr", PARAKEET_V3, (WHISPER_V3,)),
    "music":      TaskAssignment("music", ACE_STEP_15),
}


HARDWARE_PROFILES: dict[str, dict[str, str]] = {
    # task -> model name override. Empty dict = primaries everywhere.
    "m5pro-64gb": {"vision": "Qwen3-VL-8B"},          # keep the 27B for thinking, use the 8B for QA
    "64gb": {"vision": "Qwen3-VL-8B"},
    "128gb": {},
    "32gb": {"image": "Z-Image-Turbo", "embeddings": "Qwen3-Embedding-0.6B", "vision": "Qwen3-VL-8B"},
}


def resolve(task: str, profile: str = "m5pro-64gb", overrides: dict[str, str] | None = None) -> ModelSpec:
    """Pick the model for a task on a hardware profile, honouring user overrides by model name."""
    assignment = ASSIGNMENTS[task]
    wanted = (overrides or {}).get(task) or HARDWARE_PROFILES.get(profile, {}).get(task)
    if wanted:
        for spec in (assignment.primary, *assignment.alternates):
            if spec.name == wanted or spec.id == wanted:
                return spec
        raise KeyError(f"model {wanted!r} is not an option for task {task!r}")
    return assignment.primary


def candidates(task: str) -> list[ModelSpec]:
    a = ASSIGNMENTS[task]
    return [a.primary, *a.alternates]


def memory_plan(profile: str = "m5pro-64gb") -> dict[str, float]:
    """Resident memory per task for the given profile (used by `agency doctor`)."""
    return {task: resolve(task, profile).memory_gb for task in ASSIGNMENTS}
