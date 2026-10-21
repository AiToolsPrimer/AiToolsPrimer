# Model choices and the evidence behind them

Checked 20-21 October 2026 against Artificial Analysis (Intelligence Index, video, image-editing
and speech arenas), Arena (text-to-image, image-edit), MTEB, the Open ASR Leaderboard and the
official model cards. Two filters before quality: **runs on Apple Silicon** and **licence allows
commercial use**. The agency runs **one model at a time**, so each runs at the highest precision
that fits in 64 GB on its own.

| Task | Chosen | Precision / memory | Why | Rejected and why |
|---|---|---|---|---|
| Brain (director, strategy, writing, judging, fact-check, vision) | **Qwen3.8-Flash-Next**, Qwen Community License 1.0 (commercial allowed) | ~4-bit (UD-IQ4_XS), 46 GB fast memory, 51B n-gram table on SSD | 39.8 on the AA Intelligence Index vs 34 for the 27B on the same index; multimodal; 18-70 tok/s measured on 64 GB M1/M4 Max with the table on SSD | gpt-oss-120b does not fit (65.8 GB); GLM-5.3-Flash needs 192+ GB; Step-3.5-Flash (196B) ~100 GB at 4-bit |
| Second pen, fallback brain | **Qwen3.8-27B**, Apache 2.0 | 8-bit MLX, 29 GB, ~18-20 tok/s | strongest small open model on the index; 8-bit is near-lossless | 4-bit: 2x faster, visible loss on long reasoning (kept for the optional draft lane); BF16: 54 GB, 6 tok/s, no real gain; Gemma 4 31B scores 19 |
| Images | **Qwen-Image-2512**, Apache 2.0 | 8-bit MLX (mflux), 34-40 GB, ~3 min per image | best permissively licensed model on Arena text-to-image (1125 Elo); excellent in-image text | Qwen-Image-2.1 ranks higher but is research-only; FLUX.2 [dev] needs a paid licence; runtime 4-bit produces mosaic noise |
| Image editing | **Qwen-Image-Edit-2511**, Apache 2.0 | GGUF Q8_0 (unsloth build), 22 GB + 9 GB fp8 text encoder, in ComfyUI | 1235 Elo on Arena image-edit, best commercially usable | FLUX.2 [klein] 9B is non-commercial |
| Video | **LTX-2.5**, free under $10M revenue | int8 MLX pack (`dgrauet/ltx-2.5-mlx-q8`, 45 GB on disk, ~44 GB resident) through `ltx-2-mlx` | 2nd open model on the AA video board; native audio; the port's recommended pack for 2.5; bf16 pack kept for 128 GB machines | bf16 on 64 GB: 62 GB peak with the 12B text encoder resident (measured by the port's authors), only with blocks streamed from the SSD; Wan 2.2: no FP8 on Metal, 82 min per 2 s clip; MiniMax H3 (1st): licence excludes EU use, 340+ GB |
| Presenter | **LTX MLX audio-to-video** (ComfyUI node) | | photo + voice → talking presenter on Apple Silicon | Wan-S2V, InfiniteTalk (Wan-based) |
| Voice (English) | **Step-Audio-EditX**, Apache 2.0 | int8 MLX, 4.4 GB, through the `mlx-speech` package (MIT, Python 3.13) | 1102-1111 Elo on the AA Speech Arena, highest among commercially usable open voices; English cloning, emotion and style from text; needs a 5-10 s reference voice + transcript | Breeze TTS 2 (1215) non-commercial, English/Chinese only; Voxtral TTS CC BY-NC; Fish S2 Pro research licence |
| Voice fallbacks | Kokoro 82M (Apache, 1062 Elo), Chatterbox (MIT, 1020) | | | |
| Transcription | **Parakeet TDT 0.6B v2**, CC BY 4.0 | 2 GB | 6.05 WER on the Open ASR Leaderboard at ~3,400x realtime; subtitles come from our own scripts anyway | Canary-Qwen 2.5B 5.63 but 8x slower; Whisper large-v3 7.44 |
| Music | **ACE-Step 1.5**, MIT, commercial outputs explicitly granted | 4 GB | runs natively on Mac | HeartMuLa carries CC BY-NC code |
| Memory | **Qwen3-Embedding-8B**, Apache 2.0 | GGUF Q8_0, 8 GB | 4th on MTEB Multilingual v2; fits because it runs alone | harrier-oss-27B is 1st but wasteful here |
| Safety | **Qwen3Guard-Gen-4B**, Apache 2.0 | GGUF Q8_0 (mradermacher build), 4.7 GB | dedicated classifier | Llama Guard 4 |

## Quantization, in short

8-bit is a quantization too and is the default for the brain's second pen and for images, because
it is near-lossless. 4-bit is used where it is the only way to fit (Flash-Next) or for speed where
quality is not the point (the optional draft lane). bf16 is used where the model fits alone (video).
A Mac with one model in memory can afford higher precision than a Mac juggling several.

## Disk: what the files really take (checked on Hugging Face, 21 October 2026)

| Files | GB |
|---|---|
| Qwen3.8-Flash-Next UD-IQ4_XS (3 shards: 44 GB of weights + 50 GB n-gram shard) + mmproj | 94.6 |
| Qwen3.8-27B MLX 8-bit | 29.5 |
| Qwen-Image-2512 8-bit MLX | 36.1 |
| Qwen-Image-Edit-2511 Q8_0 + Qwen2.5-VL fp8 text encoder + VAE | 31.4 |
| LTX-2.5 int8 MLX pack, distilled transformer only (full pack with dev transformer + LoRA: 74.7) | 45.2 |
| Qwen3-Embedding-8B Q8_0, Qwen3Guard-Gen-4B Q8_0 | 12.7 |
| Step-Audio-EditX int8, Kokoro, Parakeet v2 | 7.3 |
| **Total** (+16 GB for the optional 27B 4-bit draft lane, + a few GB ACE-Step fetches itself) | **~257** |

The earlier estimate of "about 130 GB" was wrong: it counted the brain's resident weights, not its
files. Everything goes under one folder (`AGENCY_MODELS`), which can be an external SSD; see the
README section "Models on an external SSD". A smaller brain file exists (ISTA-DASLab GSQ-RCO
IQ3_XXS, 76 GB, 3.0 bits per weight, the lab reports parity with the base model on AIME25); the
4.25-bit unsloth build stays the default because its transformer weights carry more precision, and
the 18 GB saved would not change which disk you need.

## Honest limits

- No local model matches a frontier model as director; the Anthropic switch exists for that and is off.
- Flash-Next on 64 GB rests on community reports (M1 Max, M4 Max), none yet on M5 Pro: hence the benchmark and the automatic fallback.
- Video on a Mac is the slow part: a four-minute video is 20-40 scenes, 20-40 minutes of rendering with mixed visuals.
- Package names for the MLX ports move fast; `scripts/install_mac.sh` names the ones current at writing (checked 21 October 2026: `mflux`, `parakeet-mlx`, `kokoro`, `mlx-speech` on PyPI; `ltx-2-mlx` as a git checkout, no PyPI package).
- X: API pay-per-post since February 2026, reads also paid; browser with your click only, no metrics.

## Corrections made during the research

- Two package names in the first install script did not exist on PyPI (`ltx-mlx`, `step-audio-editx-mlx`); the video runtime is the `ltx-2-mlx` checkout and the voice runs through `mlx-speech`.
- LTX-2.5 was first listed as bf16 at 36 GB; the bf16 pack needs 62 GB with its text encoder resident, so the int8 pack is the one that runs alone on 64 GB.
- "About 130 GB" of downloads was an under-count; the files take about 260 GB.

- An earlier draft listed a free tier for the X API; it closed on 6 February 2026.
- An earlier draft called Parakeet v3 the most accurate English model; Canary-Qwen is, Parakeet v2 is the fastest near the top.
- Two index versions were mixed for the 27B (34 vs 52); the robust statement is "best small open model".

## Sources

Artificial Analysis Intelligence Index v4.3 and leaderboard; AA video (text-to-video open weights),
image-editing and speech arenas; Arena text-to-image and image-edit boards (open-licence filter);
model cards: Qwen3.8-27B, Qwen3.8-Flash-Next, Qwen-Image-2512, Qwen-Image-Edit-2511, LTX-2.5,
Step-Audio-EditX, Breeze TTS 2, Voxtral TTS, Fish S2 Pro, Step-3.5-Flash; Open ASR Leaderboard paper
(arXiv 2510.06961) and the Canary/Parakeet v3 paper (arXiv 2509.14128); ACE-Step 1.5 repository;
community reports: Flash-Next on 64 GB Macs (Atomic Chat, xhinker, lilting.ch), Wan 2.2 vs LTX-2 on
Apple Silicon, LTX-2.5 MLX, ComfyUI-LTX-MLX-A2V, latentsync-mlx, MuseTalk MLX; X API pricing 2026.
