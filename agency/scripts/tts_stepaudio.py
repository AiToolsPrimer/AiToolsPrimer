#!/usr/bin/env python3
"""Step-Audio-EditX (Apache-2.0) English voice through the community MLX int8 port.
python scripts/tts_stepaudio.py --text-file in.txt --out out.wav [--voice ref.wav] [--model appautomaton/step-audio-editx-8bit-mlx]
Install: pip install step-audio-editx-mlx   (see https://huggingface.co/appautomaton/step-audio-editx-8bit-mlx)
The port's Python API has moved between releases; this script tries the documented entry points in order."""
import argparse
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default="default", help="path to a 3-10 s reference WAV to clone, or 'default'")
    ap.add_argument("--model", default="appautomaton/step-audio-editx-8bit-mlx")
    ap.add_argument("--style", default="warm, clear, confident narration")
    a = ap.parse_args()
    text = open(a.text_file, encoding="utf-8").read().strip()
    ref = None if a.voice in ("", "default") else a.voice
    # 1) Python API of the MLX port
    try:
        from step_audio_editx_mlx import StepAudioEditX  # type: ignore

        model = StepAudioEditX.from_pretrained(a.model)
        audio, sr = model.tts(text, ref_audio=ref, style=a.style)
        import soundfile as sf

        sf.write(a.out, audio, sr)
        return 0
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"step_audio_editx_mlx failed: {e}", file=sys.stderr)
    # 2) CLI of the MLX port
    cmd = ["step-audio-editx", "tts", "--model", a.model, "--text", text, "--output", a.out]
    if ref:
        cmd += ["--prompt-audio", ref]
    try:
        subprocess.run(cmd, check=True)
        return 0
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"step-audio-editx CLI failed: {e}. Install the MLX port or let the agency fall back to Kokoro.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
