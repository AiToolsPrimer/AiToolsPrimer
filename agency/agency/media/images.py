"""Image generation and editing through ComfyUI workflows (or a CLI template)."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from agency.media.ffmpeg import FF
from agency.media.runner import ComfyUI, MediaError, run_template
from agency.models.registry import ModelSpec

PLATFORM_SIZES: dict[str, tuple[int, int]] = {
    "square": (1080, 1080),
    "landscape": (1920, 1080),
    "portrait": (1080, 1350),
    "story": (1080, 1920),
    "thumbnail": (1280, 720),
    "pin": (1000, 1500),
    "og": (1200, 630),
}


class Images:
    def __init__(self, spec: ModelSpec, comfy: ComfyUI | None, workflows_dir: Path, ff: FF, dry_run: bool = False, python: str = "python3", command: str = ""):
        self.spec, self.comfy, self.workflows_dir, self.ff, self.dry_run, self.python, self.command = spec, comfy, workflows_dir, ff, dry_run, python, command

    def _workflow_for(self, spec: ModelSpec, edit: bool = False) -> Path:
        slug = spec.name.lower().replace(" ", "-").replace(".", "")
        cands = [self.workflows_dir / f"{slug}{'-edit' if edit else ''}.json", self.workflows_dir / ("image-edit.json" if edit else "image.json")]
        for c in cands:
            if c.exists():
                return c
        raise MediaError(f"no ComfyUI workflow found for {spec.name}; export one as API JSON to {cands[0]}")

    def generate(self, prompt: str, out: Path, size: str = "landscape", seed: int | None = None, negative: str = "") -> Path:
        width, height = PLATFORM_SIZES.get(size, PLATFORM_SIZES["landscape"])
        seed = seed if seed is not None else random.randint(1, 2**31)
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            return self._placeholder(out, width, height, prompt)
        if self.command:
            run_template(self.command, {"python": self.python, "prompt": prompt, "out": out, "width": width, "height": height, "seed": seed, "model": self.spec.id})
            if not out.exists():
                raise MediaError("image command produced no file")
            return out
        if not self.comfy:
            raise MediaError("no image backend: start ComfyUI or set an image command template")
        wf = ComfyUI.fill(self._workflow_for(self.spec), {"prompt": prompt, "negative": negative, "seed": seed, "width": width, "height": height, "model": self.spec.id})
        files = self.comfy.run(wf, out.parent)
        files[0].replace(out)
        return out

    def edit(self, image: Path, instruction: str, out: Path, seed: int | None = None) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            out.write_bytes(image.read_bytes())
            return out
        if not self.comfy:
            raise MediaError("image editing needs ComfyUI")
        wf = ComfyUI.fill(self._workflow_for(self.spec, edit=True), {"prompt": instruction, "seed": seed or random.randint(1, 2**31), "image": str(image.resolve()), "model": self.spec.id})
        files = self.comfy.run(wf, out.parent)
        files[0].replace(out)
        return out

    def _placeholder(self, out: Path, width: int, height: int, text: str) -> Path:
        tmp = out.with_suffix(".mp4")
        self.ff.placeholder_clip(tmp, 0.1, width, height, 1, text[:60])
        self.ff.thumbnail(tmp, out, 0.0)
        tmp.unlink(missing_ok=True)
        return out
