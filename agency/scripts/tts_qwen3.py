#!/usr/bin/env python3
"""Qwen3-TTS 1.7B (Apache-2.0) fallback voice with 3-second cloning.
python scripts/tts_qwen3.py --text-file in.txt --out out.wav [--voice ref.wav]
Install per the model card: https://huggingface.co/Qwen/Qwen3-TTS-1.7B  (pip install qwen-tts)."""
import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default="default")
    a = ap.parse_args()
    try:
        import soundfile as sf
        from qwen_tts import Qwen3TTS  # package name per the model card; adjust if it differs
    except ImportError as e:
        print(f"qwen-tts not installed: {e}", file=sys.stderr)
        return 2
    model = Qwen3TTS.from_pretrained("Qwen/Qwen3-TTS-1.7B")
    text = open(a.text_file, encoding="utf-8").read().strip()
    kw = {"ref_audio": a.voice} if a.voice != "default" else {}
    audio, sr = model.generate(text, language="en", **kw)
    sf.write(a.out, audio, sr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
