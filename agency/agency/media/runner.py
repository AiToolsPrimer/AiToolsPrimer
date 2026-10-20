"""Run local media models: shell command templates (MLX CLIs, Python scripts),
the ComfyUI HTTP API, and the model manager that loads/unloads models so the
64 GB budget is never exceeded.
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from agency.models.registry import ModelSpec


class MediaError(RuntimeError):
    pass


def run_template(template: str, mapping: dict[str, Any], *, cwd: Path | None = None, timeout: int = 3600, dry_run: bool = False) -> str:
    """Fill ``{placeholders}`` in a command template (values are shell-quoted) and run it."""
    cmd = template
    for key, value in mapping.items():
        cmd = cmd.replace("{" + key + "}", shlex.quote(str(value)))
    if "{" in cmd and "}" in cmd:
        missing = [p for p in _placeholders(cmd) if p not in mapping]
        if missing:
            raise MediaError(f"command template is missing values for {missing}: {template}")
    if dry_run:
        return f"[dry-run] {cmd}"
    proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise MediaError(f"command failed ({proc.returncode}): {cmd}\n{proc.stderr[-2000:]}")
    return proc.stdout


def _placeholders(cmd: str) -> list[str]:
    import re
    return re.findall(r"\{([a-z_]+)\}", cmd)


class ComfyUI:
    """Minimal client for the ComfyUI HTTP API: submit a workflow (API format JSON) with
    placeholders filled, wait, and collect the produced files."""

    def __init__(self, base_url: str, timeout: float = 7200.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.client_id = uuid.uuid4().hex

    def alive(self) -> bool:
        try:
            return self.client.get("/system_stats", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def free_memory(self) -> None:
        try:
            self.client.post("/free", json={"unload_models": True, "free_memory": True})
        except httpx.HTTPError:
            pass

    @staticmethod
    def fill(workflow_path: Path, values: dict[str, Any]) -> dict[str, Any]:
        """Workflows are exported from ComfyUI as API JSON and edited so that the fields the
        agency controls read ``"__PROMPT__"``, ``"__SEED__"``, ``"__WIDTH__"`` ... as strings."""
        text = workflow_path.read_text()
        for key, value in values.items():
            token = f'"__{key.upper()}__"'
            replacement = json.dumps(value) if not isinstance(value, str) else json.dumps(value)
            text = text.replace(token, replacement)
        return json.loads(text)

    def run(self, workflow: dict[str, Any], output_dir: Path, poll: float = 2.0) -> list[Path]:
        r = self.client.post("/prompt", json={"prompt": workflow, "client_id": self.client_id})
        if r.status_code >= 400:
            raise MediaError(f"ComfyUI rejected the workflow: {r.text[:500]}")
        pid = r.json()["prompt_id"]
        while True:
            h = self.client.get(f"/history/{pid}").json()
            if pid in h:
                entry = h[pid]
                if entry.get("status", {}).get("status_str") == "error":
                    raise MediaError(f"ComfyUI run failed: {json.dumps(entry.get('status'))[:500]}")
                break
            time.sleep(poll)
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        for node in entry.get("outputs", {}).values():
            for kind in ("images", "gifs", "videos", "audio"):
                for f in node.get(kind, []):
                    data = self.client.get("/view", params={"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")}).content
                    dest = output_dir / f["filename"]
                    dest.write_bytes(data)
                    files.append(dest)
        if not files:
            raise MediaError("ComfyUI produced no output files")
        return files


class ModelManager:
    """Keeps resident memory under the GPU budget: LM Studio models are loaded/unloaded
    with the ``lms`` CLI, ComfyUI is asked to free memory before a heavy job."""

    def __init__(self, lms_cli: str, budget_gb: float, comfy: ComfyUI | None = None, dry_run: bool = False):
        self.lms = lms_cli
        self.budget = budget_gb
        self.comfy = comfy
        self.dry_run = dry_run
        self.loaded: dict[str, ModelSpec] = {}
        self.pinned: set[str] = set()
        self._lock = threading.RLock()
        self.media_lock = threading.Lock()  # one heavy media job at a time

    def available(self) -> bool:
        return shutil.which(self.lms) is not None

    def resident_gb(self) -> float:
        return sum(m.memory_gb for m in self.loaded.values())

    def ensure(self, spec: ModelSpec, pin: bool = False) -> None:
        with self._lock:
            if spec.runtime != "lmstudio":
                # media runtimes manage their own memory; just make room
                self._make_room(spec.memory_gb)
                return
            if spec.id in self.loaded:
                if pin:
                    self.pinned.add(spec.id)
                return
            self._make_room(spec.memory_gb)
            if not self.dry_run and self.available():
                subprocess.run([self.lms, "load", spec.id, "--identifier", spec.id, "-y"], capture_output=True, text=True, timeout=600)
            self.loaded[spec.id] = spec
            if pin:
                self.pinned.add(spec.id)

    def release(self, spec: ModelSpec) -> None:
        with self._lock:
            if spec.id in self.loaded and spec.id not in self.pinned:
                self._unload(spec.id)

    def _make_room(self, needed_gb: float) -> None:
        if self.comfy and needed_gb > 8:
            self.comfy.free_memory()
        while self.loaded and self.resident_gb() + needed_gb > self.budget:
            victim = next((k for k in self.loaded if k not in self.pinned), None)
            if victim is None:
                break
            self._unload(victim)

    def _unload(self, model_id: str) -> None:
        if not self.dry_run and self.available():
            subprocess.run([self.lms, "unload", model_id], capture_output=True, text=True, timeout=120)
        self.loaded.pop(model_id, None)
