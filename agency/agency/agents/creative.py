"""Image, video, voice and music agents: they turn briefs into files in assets/."""
from __future__ import annotations

import base64
import datetime as dt
import re
from pathlib import Path
from typing import Any

from agency.agents.base import Agent
from agency.agents.writer import Writer
from agency.media.images import Images
from agency.media.video import VideoAssembler, VideoPlan

STYLE = "clean editorial illustration or crisp product photography, soft daylight, muted palette with one accent colour, no text, no logos, no watermarks, no real people's faces"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "item"


class ImageAgent(Agent):
    role = "art director"
    temperature = 0.6

    def __init__(self, llm, store, brand, images: Images, assets_dir: Path, vision=None):
        super().__init__(llm, store, brand)
        self.images, self.assets_dir, self.vision = images, assets_dir, vision

    def make(self, brief: str, size: str = "landscape", topic: str = "", attempts: int = 2) -> int:
        """Generate an image for a brief, quality-check it with the vision model, return the asset id."""
        prompt = f"{brief}. Style: {STYLE}."
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out = self.assets_dir / "images" / f"{stamp}-{_slug(topic or brief)}.png"
        last_issue = ""
        for attempt in range(attempts):
            path = self.images.generate(prompt, out)
            issue = self.inspect(path, brief)
            if not issue:
                break
            last_issue = issue
            prompt = f"{brief}. Style: {STYLE}. Avoid: {issue}."
        return self.store.add_asset("image", path, prompt=prompt, model=self.images.spec.name, meta={"brief": brief, "size": size, "issue": last_issue})

    def inspect(self, path: Path, brief: str) -> str:
        """Ask the vision model whether the picture matches the brief; '' means fine."""
        if not self.vision or self.images.dry_run:
            return ""
        try:
            b64 = base64.b64encode(path.read_bytes()).decode()
            answer = self.vision.describe_image(b64, f"Brief: {brief}. Does this image match the brief and contain no garbled text, extra limbs, logos or watermarks? Reply 'OK' or describe the single worst problem in one sentence.")
        except Exception:  # noqa: BLE001
            return ""
        return "" if answer.strip().upper().startswith("OK") else answer.strip()[:200]


class VideoAgent(Agent):
    role = "video producer"
    temperature = 0.6

    def __init__(self, llm, store, brand, writer: Writer, assembler: VideoAssembler, assets_dir: Path, max_seconds: int = 240):
        super().__init__(llm, store, brand)
        self.writer, self.assembler, self.assets_dir, self.max_seconds = writer, assembler, assets_dir, max_seconds

    def produce(self, topic: str, angle: str, target_seconds: int | None = None, link: str = "", facts: str = "", presenter: bool = False, with_shorts: bool = True, verifier=None) -> dict[str, Any] | None:
        target = min(target_seconds or self.max_seconds, self.max_seconds)
        script = self.writer.video_script(topic, angle, target, link=link, facts=facts, presenter=presenter)
        factcheck = None
        if verifier is not None:
            scenes, removed = verifier(script.get("scenes", []))
            factcheck = {"removed": removed, "scenes_kept": len(scenes), "scenes_written": len(script.get("scenes", []))}
            if not scenes:
                return None
            script["scenes"] = scenes
        plan = VideoPlan.from_json(script, self.max_seconds, default_mode=self.assembler.d.default_visual_mode)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        workdir = self.assets_dir / "video" / f"{stamp}-{_slug(topic)}"
        result = self.assembler.build(plan, workdir, with_shorts=with_shorts)
        script_path = workdir / "script.json"
        import json
        script_path.write_text(json.dumps(script, indent=2))
        video_id = self.store.add_asset("video", result["video"], prompt=topic, model=self.assembler.video_spec.name, meta={"seconds": result["seconds"], "scenes": result["scenes"], "srt": str(result["srt"]), "thumbnail": str(result["thumbnail"]), "script": str(script_path)})
        short_ids = [self.store.add_asset("video", p, prompt=f"short of {topic}", model=self.assembler.video_spec.name, meta={"short": True, "parent": video_id}) for p in result.get("shorts", [])]
        return {"asset_id": video_id, "short_asset_ids": short_ids, "title": script.get("title", topic), "description": script.get("description", ""), "tags": script.get("tags", []), "seconds": result["seconds"], "thumbnail": result["thumbnail"], "workdir": workdir, "factcheck": factcheck}
