#!/usr/bin/env python3
"""Chatterbox (MIT) voiceover: python scripts/tts_chatterbox.py --text-file in.txt --out out.wav [--voice ref.wav]
Install: pip install chatterbox-tts   (Apple Silicon: runs on MPS)."""
import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default="default", help="path to a 5-10 s reference WAV, or 'default'")
    ap.add_argument("--exaggeration", type=float, default=0.5)
    ap.add_argument("--cfg", type=float, default=0.5)
    a = ap.parse_args()
    try:
        import torch
        import torchaudio as ta
        from chatterbox.tts import ChatterboxTTS
    except ImportError as e:
        print(f"chatterbox not installed: {e}. Run: pip install chatterbox-tts", file=sys.stderr)
        return 2
    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxTTS.from_pretrained(device=device)
    text = open(a.text_file, encoding="utf-8").read().strip()
    kw = {}
    if a.voice and a.voice != "default":
        kw["audio_prompt_path"] = a.voice
    wav = model.generate(text, exaggeration=a.exaggeration, cfg_weight=a.cfg, **kw)
    ta.save(a.out, wav, model.sr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
