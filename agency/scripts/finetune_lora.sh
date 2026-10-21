#!/usr/bin/env bash
# Fine-tune the 27B on your approved texts with LoRA (MLX). Needs ~300+ examples (agency exports them
# to state/learning/train.jsonl) and a few hours on the Mac mini. The result is an adapter the agency
# loads on top of the 27B for writing in your voice.
set -euo pipefail
cd "$(dirname "$0")/.."
DATA=${1:-state/learning}
MODEL=${2:-lmstudio-community/Qwen3.8-27B-MLX-4bit}   # QLoRA on the 4-bit weights fits in 64 GB
OUT=${3:-state/learning/adapter}
python3 - <<PY
import json, random, pathlib
src = pathlib.Path("$DATA") / "train.jsonl"
rows = [l for l in src.read_text().splitlines() if l.strip()]
random.seed(7); random.shuffle(rows)
n = len(rows); cut = max(1, int(n * 0.9))
d = pathlib.Path("$DATA") / "split"; d.mkdir(exist_ok=True)
(d / "train.jsonl").write_text("\n".join(rows[:cut]) + "\n")
(d / "valid.jsonl").write_text("\n".join(rows[cut:] or rows[:1]) + "\n")
print(f"{n} examples: {cut} train, {n-cut} valid")
PY
python3 -m mlx_lm.lora --model "$MODEL" --train --data "$DATA/split" --adapter-path "$OUT" \
  --batch-size 1 --num-layers 16 --iters 600 --learning-rate 1e-5 --max-seq-length 2048
echo "Adapter saved to $OUT. Set models.overrides.second_writer or brain to the adapter in config/agency.yaml (see docs/MODELS.md)."
