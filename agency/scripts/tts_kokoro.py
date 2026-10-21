#!/usr/bin/env python3
"""Kokoro-82M (Apache-2.0) narration: python scripts/tts_kokoro.py --text-file in.txt --out out.wav --voice af_heart
Install: pip install kokoro soundfile   (brew install espeak-ng for out-of-dictionary words)."""
import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args()
    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
    except ImportError as e:
        print(f"kokoro not installed: {e}. Run: pip install kokoro soundfile", file=sys.stderr)
        return 2
    voice = a.voice if a.voice != "default" else "af_heart"
    pipe = KPipeline(lang_code="a")  # American English
    text = open(a.text_file, encoding="utf-8").read().strip()
    chunks = [audio for _, _, audio in pipe(text, voice=voice, speed=a.speed)]
    sf.write(a.out, np.concatenate(chunks), 24000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
