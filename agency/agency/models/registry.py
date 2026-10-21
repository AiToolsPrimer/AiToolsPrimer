"""Which model does which job, on which hardware.

Every row was chosen against independent leaderboards (Artificial Analysis, Arena,
MTEB, Open ASR Leaderboard) and the official model cards, with two hard filters: it
must run on Apple Silicon, and its licence must allow commercial use.  The agency runs
ONE model at a time, so each model gets the whole machine and runs at the highest
precision that fits.  See docs/MODELS.md for the evidence behind each row.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Runtime = Literal["lmstudio", "llamacpp", "mlx-server", "comfyui", "mlx-cli", "python-script", "http-service"]


@dataclass(frozen=True)
class ModelSpec:
    id: str                       # identifier the runtime understands (Hugging Face repo or LM Studio id)
    name: str
    runtime: Runtime
    memory_gb: float              # resident memory at the chosen precision
    license: str
    precision: str = ""           # "8-bit", "4-bit", "bf16", "int8"
    notes: str = ""
    command: str = ""             # server launch (llamacpp / mlx-server / http-service) or job command (mlx-cli / python-script)
    alt_ids: tuple[str, ...] = ()  # other repos carrying the same weights
    multimodal: bool = False
    port: int = 0                 # for servers the host starts


@dataclass(frozen=True)
class TaskAssignment:
    task: str
    primary: ModelSpec
    alternates: tuple[ModelSpec, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------------- brains

QWEN38_FLASH_NEXT = ModelSpec(
    id="unsloth/Qwen3.8-Flash-Next-GGUF",
    name="Qwen3.8-Flash-Next",
    runtime="llamacpp",
    memory_gb=46,
    license="Qwen Community License 1.0 (commercial use allowed; name display above 100M MAU)",
    precision="~4-bit (UD-IQ4_XS), n-gram table paged from SSD",
    notes="125B MoE, 6B active, multimodal (image+video in). AA index 39.8 vs 34 for the 27B on the same index. Runs on 64 GB only with the 51B n-gram table left on the SSD; measured 18-70 tok/s on 64 GB M1/M4 Max, no public M5 Pro run yet. The doctor benchmark decides whether it stays the brain.",
    command="llama-server -hf {model}:UD-IQ4_XS --port {port} --ctx-size 65536 --n-gpu-layers 999 --jinja --flash-attn on",
    alt_ids=("AtomicChat/Qwen3.8-Flash-Next-GGUF", "Qwen/Qwen3.8-Flash-Next-FP8"),
    multimodal=True,
    port=8081,
)
QWEN38_27B_8BIT = ModelSpec(
    id="malekoo/Qwen3.8-27B-MLX-8bit",
    name="Qwen3.8-27B (8-bit)",
    runtime="lmstudio",
    memory_gb=29,
    license="Apache-2.0",
    precision="8-bit MLX",
    notes="Strongest small open model on the AA index; dense, multimodal, 262K context, thinking mode with effort control. 8-bit is near-lossless; ~18 tok/s on M5 Max.",
    alt_ids=("lmstudio-community/Qwen3.8-27B-MLX-8bit", "unsloth/Qwen3.8-27B-GGUF"),
    multimodal=True,
)
QWEN38_27B_4BIT = ModelSpec(
    id="lmstudio-community/Qwen3.8-27B-MLX-4bit",
    name="Qwen3.8-27B (4-bit)",
    runtime="lmstudio",
    memory_gb=17,
    license="Apache-2.0",
    precision="4-bit MLX",
    notes="Twice the speed of 8-bit (~36 tok/s on M5 Pro) with a small quality loss; used only for the fast 'draft' lane if enabled.",
    multimodal=True,
)
QWEN3_EMBED_8B = ModelSpec(
    id="Qwen/Qwen3-Embedding-8B-GGUF",
    name="Qwen3-Embedding-8B",
    runtime="lmstudio",
    memory_gb=6,
    license="Apache-2.0",
    precision="8-bit",
    notes="4th on MTEB Multilingual v2; the 8B fits because nothing else is loaded.",
    alt_ids=("Qwen/Qwen3-Embedding-4B-GGUF",),
)
QWEN3_GUARD = ModelSpec(
    id="Qwen/Qwen3Guard-Gen-4B",
    name="Qwen3Guard-Gen-4B",
    runtime="lmstudio",
    memory_gb=3,
    license="Apache-2.0",
    precision="8-bit",
    notes="Content safety classifier run before anything is published.",
)

# ----------------------------------------------------------------------------- images

QWEN_IMAGE_2512 = ModelSpec(
    id="mlx-community/Qwen-Image-2512-8bit",
    name="Qwen-Image-2512",
    runtime="mlx-cli",
    memory_gb=36,
    license="Apache-2.0",
    precision="8-bit MLX",
    notes="Best permissively licensed model on Arena text-to-image (1125 Elo), excellent in-image text. 8-bit is the floor for diffusion transformers: runtime 4-bit produces mosaic noise. ~8.5 s/step on M-series.",
    command="mflux-generate-qwen --model {model} --prompt {prompt} --output {out} --width {width} --height {height} --seed {seed} --steps {steps} -q 8",
)
QWEN_IMAGE_EDIT_2511 = ModelSpec(
    id="Qwen/Qwen-Image-Edit-2511",
    name="Qwen-Image-Edit-2511",
    runtime="comfyui",
    memory_gb=22,
    license="Apache-2.0",
    precision="GGUF Q8",
    notes="Top commercially usable model on the Arena image-edit board (1235 Elo).",
)
Z_IMAGE_TURBO = ModelSpec(
    id="Tongyi-MAI/Z-Image-Turbo",
    name="Z-Image-Turbo",
    runtime="comfyui",
    memory_gb=12,
    license="Apache-2.0",
    precision="bf16",
    notes="Fast 6B model for drafts, thumbnails and bulk variants.",
)
HIDREAM_O1 = ModelSpec(
    id="HiDream-ai/HiDream-O1-Image",
    name="HiDream-O1-Image",
    runtime="comfyui",
    memory_gb=30,
    license="MIT",
    notes="Arena 1116 Elo; alternate style.",
)

# ----------------------------------------------------------------------------- video

LTX_25 = ModelSpec(
    id="Lightricks/LTX-2.5",
    name="LTX-2.5",
    runtime="mlx-cli",
    memory_gb=36,
    license="LTX-2.x Community (free under $10M revenue)",
    precision="bf16 (runs alone)",
    notes="Second open model on the AA video board; native audio; MLX port renders a 5 s clip in 30-45 s on M5 Max (expect ~2x on M5 Pro). Wan 2.2 is unusable on Apple Silicon (no FP8 on Metal, 82 min per 2 s clip).",
    command="{python} -m ltx_mlx generate --model {model} --prompt {prompt} --output {out} --width {width} --height {height} --num-frames {frames} --fps {fps} --seed {seed}",
)
LTX_A2V = ModelSpec(
    id="noreff/ComfyUI-LTX-MLX-A2V",
    name="LTX MLX audio-to-video",
    runtime="comfyui",
    memory_gb=36,
    license="LTX-2.x Community",
    notes="One photo + one audio track -> a presenter that speaks, on Apple Silicon (337 s for 97 frames on M5 Max).",
)
LATENTSYNC_MLX = ModelSpec(
    id="sb1992/latentsync-mlx",
    name="LatentSync MLX",
    runtime="python-script",
    memory_gb=8,
    license="Apache-2.0",
    notes="Re-sync lips on an existing video.",
)

# ----------------------------------------------------------------------------- audio

STEP_AUDIO_EDITX = ModelSpec(
    id="appautomaton/step-audio-editx-8bit-mlx",
    name="Step-Audio-EditX",
    runtime="python-script",
    memory_gb=4,
    license="Apache-2.0",
    precision="int8 MLX",
    notes="Highest Elo among commercially usable open voices on the AA Speech Arena (1102-1111); English zero-shot cloning, emotion and style controlled from text. Community MLX port, 1.46x realtime.",
    command="{python} scripts/tts_stepaudio.py --text-file {text} --out {out} --voice {voice} --model {model}",
    alt_ids=("stepfun-ai/Step-Audio-EditX",),
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
CHATTERBOX = ModelSpec(
    id="ResembleAI/chatterbox",
    name="Chatterbox",
    runtime="python-script",
    memory_gb=3,
    license="MIT",
    notes="English voice with 5-second cloning and emotion control (1020 Elo).",
    command="{python} scripts/tts_chatterbox.py --text-file {text} --out {out} --voice {voice}",
)
PARAKEET_V2 = ModelSpec(
    id="mlx-community/parakeet-tdt-0.6b-v2",
    name="Parakeet TDT 0.6B v2",
    runtime="mlx-cli",
    memory_gb=2,
    license="CC-BY-4.0",
    notes="English-only, 6.05 WER on the Open ASR Leaderboard at ~3,400x realtime. Canary-Qwen 2.5B is more accurate (5.63) but 8x slower; Whisper large-v3 is 7.44.",
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
    runtime="http-service",
    memory_gb=4,
    license="MIT (commercial use of outputs explicitly granted)",
    notes="Runs natively on Mac; full tracks with or without vocals for video beds.",
    command="acestep --port {port}",
    port=7867,
)


# ----------------------------------------------------------------------------- tasks

ASSIGNMENTS: dict[str, TaskAssignment] = {
    # the brain: direction, strategy, writing, judging, fact-checking, vision QA
    "brain":         TaskAssignment("brain", QWEN38_FLASH_NEXT, (QWEN38_27B_8BIT,)),
    # the second hand: an independent draft from a different model, merged by the brain
    "second_writer": TaskAssignment("second_writer", QWEN38_27B_8BIT, (QWEN38_27B_4BIT,)),
    "fast_draft":    TaskAssignment("fast_draft", QWEN38_27B_4BIT),
    "embeddings":    TaskAssignment("embeddings", QWEN3_EMBED_8B),
    "safety":        TaskAssignment("safety", QWEN3_GUARD),
    "image":         TaskAssignment("image", QWEN_IMAGE_2512, (HIDREAM_O1, Z_IMAGE_TURBO)),
    "image_fast":    TaskAssignment("image_fast", Z_IMAGE_TURBO),
    "image_edit":    TaskAssignment("image_edit", QWEN_IMAGE_EDIT_2511),
    "video":         TaskAssignment("video", LTX_25),
    "avatar":        TaskAssignment("avatar", LTX_A2V, (LATENTSYNC_MLX,)),
    "tts":           TaskAssignment("tts", STEP_AUDIO_EDITX, (KOKORO, CHATTERBOX)),
    "asr":           TaskAssignment("asr", PARAKEET_V2, (WHISPER_V3,)),
    "music":         TaskAssignment("music", ACE_STEP_15),
}

# Tasks that are served by the brain model (aliases)
BRAIN_TASKS = ("director", "writer", "judge", "factcheck", "vision", "coder", "strategist")


HARDWARE_PROFILES: dict[str, dict[str, str]] = {
    # task -> model name override. Empty dict = primaries everywhere.
    "m5pro-64gb": {},                                            # brain A: Flash-Next, 27B second hand
    "m5pro-64gb-b": {"brain": "Qwen3.8-27B (8-bit)", "second_writer": "Qwen3.8-27B (4-bit)"},
    "128gb": {},
    "32gb": {"brain": "Qwen3.8-27B (8-bit)", "second_writer": "Qwen3.8-27B (4-bit)", "image": "Z-Image-Turbo"},
}


def resolve(task: str, profile: str = "m5pro-64gb", overrides: dict[str, str] | None = None) -> ModelSpec:
    """Pick the model for a task on a hardware profile, honouring user overrides by model name."""
    if task in BRAIN_TASKS:
        task = "brain"
    assignment = ASSIGNMENTS[task]
    wanted = (overrides or {}).get(task) or HARDWARE_PROFILES.get(profile, {}).get(task)
    if wanted:
        for spec in (assignment.primary, *assignment.alternates):
            if spec.name == wanted or spec.id == wanted:
                return spec
        raise KeyError(f"model {wanted!r} is not an option for task {task!r}")
    return assignment.primary


def candidates(task: str) -> list[ModelSpec]:
    if task in BRAIN_TASKS:
        task = "brain"
    a = ASSIGNMENTS[task]
    return [a.primary, *a.alternates]


def memory_plan(profile: str = "m5pro-64gb") -> dict[str, float]:
    """Resident memory per task for the given profile (one model at a time: the max matters)."""
    return {task: resolve(task, profile).memory_gb for task in ASSIGNMENTS}
