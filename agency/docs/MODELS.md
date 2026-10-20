# Model choices and the evidence behind them

Checked on 20 October 2026 against Artificial Analysis, Arena (formerly LMArena), MTEB,
the Open ASR Leaderboard and the official model cards. Two filters were applied before
quality: **runs on Apple Silicon** and **licence allows commercial use**.

| Task | Chosen | Why | Rejected and why |
|---|---|---|---|
| Director, writer, coder | **Qwen3.8-27B** (Apache 2.0, ~17 GB at 4-bit) | Strongest small open model on the AA Intelligence Index (34); dense, multimodal, 262K context; 61.7 % SWE-bench Pro | Gemma 4 31B scores 19. Qwen3.8-Flash-Next (39.8) needs 96-120 GB alone. GLM-5.3-Flash (41.8) needs 192-256 GB. Qwen2.5-72B is superseded. |
| Vision QA | **Qwen3-VL-8B** (Apache 2.0, 6 GB) | consensus local pick; keeps the 27B free for thinking | Qwen3-VL-32B only on 64 GB with nothing else loaded |
| Images | **Qwen-Image-2512** (Apache 2.0) | best permissively licensed model on Arena text-to-image (1125 Elo); excellent in-image text | Qwen-Image-2.1 ranks higher but is research-only. FLUX.2 [dev] needs a paid licence. |
| Image editing | **Qwen-Image-Edit-2511** (Apache 2.0) | 1235 Elo on Arena image-edit, best commercially usable | FLUX.2 [klein] 9B is non-commercial; the 4B is the alternate |
| Video | **LTX-2.5** (free under $10M revenue) | 2nd open model on the AA video board; native audio; MLX port renders a 5 s clip in 30-45 s on M5 Max | Wan 2.2: no FP8 on Metal, 82 min per 2 s clip on M1 Max. MiniMax H3 (1st): licence excludes EU use, 340+ GB. |
| Presenter / avatar | **LTX MLX audio-to-video** (ComfyUI node) | photo + voice → talking presenter on Apple Silicon | Wan-S2V and InfiniteTalk are Wan-based (see above) |
| Lip re-sync | **LatentSync MLX**, MuseTalk MLX (MIT) | native MLX ports | |
| Voice (English) | **Chatterbox** (MIT) | English-native, 5 s cloning, emotion control; 1020 Elo on the AA Speech Arena | Breeze TTS 2 tops the arena but its weights are non-commercial and English/Chinese only; Voxtral TTS is CC BY-NC; Fish S2 Pro licence unverified |
| Voice fallback | Kokoro 82M (Apache 2.0, 1062 Elo), Qwen3-TTS 1.7B (Apache 2.0, 10 languages) | | |
| Transcription | **Parakeet TDT 0.6B v3** (CC BY 4.0) | top English accuracy on the Open ASR Leaderboard at very high speed | Whisper large-v3 (MIT) is the alternate; Voxtral Small 24B is more accurate but heavy |
| Music | **ACE-Step 1.5** (MIT, commercial outputs explicitly granted) | runs natively on Mac | HeartMuLa is Apache but carries CC BY-NC code; YuE heavier |
| Embeddings | **Qwen3-Embedding-4B** (Apache 2.0) | 8B is 4th on MTEB Multilingual v2; 4B is the memory-friendly sibling | harrier-oss-27B is 1st but 27B for an embedder is wasteful here |
| Safety | **Qwen3Guard-Gen-4B** (Apache 2.0) | | Llama Guard 4 alternate |

## Honest limits

- No local model matches a frontier model as director. The optional Anthropic switch exists for that.
- Video on a Mac is the slow part. Four minutes of video is 20-40 scenes; budget 20-40 minutes of rendering on an M5 Pro with mixed visuals.
- Package names for the MLX ports move fast. `scripts/install_mac.sh` tries the names current at the time of writing and tells you which ones to check.
- Metrics on X need a paid API tier; the free tier is write-only, so engagement there is not read.

## Sources

- Artificial Analysis Intelligence Index v4.3 and model leaderboard; AA video, image-editing and speech arenas
- Arena text-to-image and image-edit boards (open-licence filter)
- Qwen3.8-27B, Qwen3.8-Flash-Next, Qwen-Image-2512, Qwen-Image-Edit-2511, LTX-2.5, Breeze TTS 2, Voxtral TTS model cards
- Open ASR Leaderboard paper (arXiv 2510.06961) and the Canary/Parakeet v3 paper (arXiv 2509.14128)
- ACE-Step 1.5 repository; HeartMuLa paper
- Community reports: Wan 2.2 vs LTX-2 on Apple Silicon, LTX-2.5 MLX one-command setup, ComfyUI-LTX-MLX-A2V, latentsync-mlx, MuseTalk MLX
