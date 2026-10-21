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
| Image editing | **Qwen-Image-Edit-2511**, Apache 2.0 | GGUF Q8, 22 GB | 1235 Elo on Arena image-edit, best commercially usable | FLUX.2 [klein] 9B is non-commercial |
| Video | **LTX-2.5**, free under $10M revenue | bf16 (runs alone), 36 GB | 2nd open model on the AA video board; native audio; 5 s clip in 30-45 s on M5 Max via MLX (about twice that on M5 Pro) | Wan 2.2: no FP8 on Metal, 82 min per 2 s clip; MiniMax H3 (1st): licence excludes EU use, 340+ GB |
| Presenter | **LTX MLX audio-to-video** (ComfyUI node) | | photo + voice → talking presenter on Apple Silicon | Wan-S2V, InfiniteTalk (Wan-based) |
| Voice (English) | **Step-Audio-EditX**, Apache 2.0 | int8 MLX, 4 GB | 1102-1111 Elo on the AA Speech Arena, highest among commercially usable open voices; English cloning, emotion and style from text | Breeze TTS 2 (1215) non-commercial, English/Chinese only; Voxtral TTS CC BY-NC; Fish S2 Pro research licence |
| Voice fallbacks | Kokoro 82M (Apache, 1062 Elo), Chatterbox (MIT, 1020) | | | |
| Transcription | **Parakeet TDT 0.6B v2**, CC BY 4.0 | 2 GB | 6.05 WER on the Open ASR Leaderboard at ~3,400x realtime; subtitles come from our own scripts anyway | Canary-Qwen 2.5B 5.63 but 8x slower; Whisper large-v3 7.44 |
| Music | **ACE-Step 1.5**, MIT, commercial outputs explicitly granted | 4 GB | runs natively on Mac | HeartMuLa carries CC BY-NC code |
| Memory | **Qwen3-Embedding-8B**, Apache 2.0 | 6 GB | 4th on MTEB Multilingual v2; fits because it runs alone | harrier-oss-27B is 1st but wasteful here |
| Safety | **Qwen3Guard-Gen-4B**, Apache 2.0 | 3 GB | dedicated classifier | Llama Guard 4 |

## Quantization, in short

8-bit is a quantization too and is the default for the brain's second pen and for images, because
it is near-lossless. 4-bit is used where it is the only way to fit (Flash-Next) or for speed where
quality is not the point (the optional draft lane). bf16 is used where the model fits alone (video).
A Mac with one model in memory can afford higher precision than a Mac juggling several.

## Honest limits

- No local model matches a frontier model as director; the Anthropic switch exists for that and is off.
- Flash-Next on 64 GB rests on community reports (M1 Max, M4 Max), none yet on M5 Pro: hence the benchmark and the automatic fallback.
- Video on a Mac is the slow part: a four-minute video is 20-40 scenes, 20-40 minutes of rendering with mixed visuals.
- Package names for the MLX ports move fast; `scripts/install_mac.sh` names the ones current at writing.
- X: API pay-per-post since February 2026, reads also paid; browser with your click only, no metrics.

## Corrections made during the research

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
