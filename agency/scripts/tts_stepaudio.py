#!/usr/bin/env python3
"""Step-Audio-EditX (Apache-2.0) English voice through mlx-speech (pure MLX, int8).

python scripts/tts_stepaudio.py --text-file in.txt --out out.wav --voice config/voice.wav [--model step-audio]

Install:  uv tool install --python 3.13 mlx-speech   (scripts/install_mac.sh does it)
Step-Audio-EditX clones a voice: it needs a 5-10 s English reference WAV and its exact transcript,
read from a .txt file with the same name (config/voice.wav + config/voice.txt) or --voice-text.
Without a reference the script exits with 2 and the agency falls back to Kokoro.
The weights (appautomaton/step-audio-editx-8bit-mlx) download once into the Hugging Face cache,
which the agency points at the models folder (HF_HOME), so an external SSD works too.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_cli() -> str | None:
    for cand in (shutil.which("mlx-speech"), str(Path.home() / ".local/bin/mlx-speech")):
        if cand and os.access(cand, os.X_OK):
            return cand
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default="default", help="path to a 5-10 s English reference WAV to clone, or 'default'")
    ap.add_argument("--voice-text", default="", help="exact transcript of the reference WAV (default: <voice>.txt next to it)")
    ap.add_argument("--model", default="step-audio", help="mlx-speech selector or a local pack folder")
    a = ap.parse_args()
    text = open(a.text_file, encoding="utf-8").read().strip()
    if a.voice in ("", "default") or not Path(a.voice).exists():
        print("Step-Audio-EditX needs a reference voice (config/voice.wav + config/voice.txt); falling back.", file=sys.stderr)
        return 2
    transcript = a.voice_text.strip()
    if not transcript:
        sidecar = Path(a.voice).with_suffix(".txt")
        if sidecar.exists():
            transcript = sidecar.read_text(encoding="utf-8").strip()
    if not transcript:
        print(f"No transcript for {a.voice}: write its exact words in {Path(a.voice).with_suffix('.txt')}; falling back.", file=sys.stderr)
        return 2
    cli = find_cli()
    if not cli:
        print("mlx-speech is not installed (uv tool install --python 3.13 mlx-speech); falling back.", file=sys.stderr)
        return 2
    model = a.model if (a.model == "step-audio" or Path(a.model).is_dir()) else "step-audio"
    cmd = [cli, "tts", "--model", model, "--reference-audio", a.voice, "--reference-text", transcript, "--text", text, "-o", a.out]
    try:
        subprocess.run(cmd, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"mlx-speech failed: {e}; falling back.", file=sys.stderr)
        return 2
    return 0 if Path(a.out).exists() else 2


if __name__ == "__main__":
    raise SystemExit(main())
