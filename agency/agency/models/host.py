"""One model at a time.

The ``ModelHost`` owns the machine's memory: it starts, stops, loads and unloads
model runtimes so that only one model is resident.  Agents never touch runtimes;
they ask the host for a task ("brain", "second_writer", "embeddings", "safety", …)
and get an OpenAI-compatible endpoint back.  Media models (image, video, voice,
transcription, music) are run as jobs through the same gate, so a video render
never competes with the brain for memory.

Backends:
  * lmstudio     - ``lms load/unload`` and LM Studio's server on :1234
  * llamacpp     - a ``llama-server`` process the host starts and stops
  * mlx-server   - a ``mlx_vlm.server`` / ``mlx_lm.server`` process
  * http-service - a long-running service (ACE-Step) started on demand
  * mlx-cli / python-script / comfyui - per-job commands, nothing resident
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from agency.models import paths
from agency.models.registry import ModelSpec


class HostError(RuntimeError):
    pass


@dataclass
class Endpoint:
    base_url: str
    model_id: str
    spec: ModelSpec


@dataclass
class Backend:
    spec: ModelSpec
    base_url: str = ""
    process: subprocess.Popen | None = None
    started_at: float = 0.0

    def alive(self) -> bool:
        return self.process is None or self.process.poll() is None


class ModelHost:
    def __init__(
        self,
        *,
        lms_cli: str = "lms",
        lmstudio_url: str = "http://127.0.0.1:1234",
        python: str = "python3",
        state_dir: Path | None = None,
        dry_run: bool = False,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        start_timeout: float = 900.0,
        models_dir: Path | None = None,
    ):
        self.lms_cli, self.lmstudio_url, self.python = lms_cli, lmstudio_url, python
        self.models_dir = models_dir
        # every runtime process inherits the caches under the models folder (internal disk or external SSD)
        self.env: dict[str, str] | None = {**os.environ, **paths.runtime_env(models_dir)} if models_dir else None
        self.state_dir = state_dir
        self.dry_run = dry_run
        self.on_event = on_event or (lambda e: None)
        self.start_timeout = start_timeout
        self._lock = threading.RLock()
        self.active: Backend | None = None
        self.job_lock = threading.Lock()   # media jobs run one at a time, after the resident model is released
        self.history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ public
    def activate(self, spec: ModelSpec) -> Endpoint:
        """Make ``spec`` the resident model (swapping out whatever was there) and return its endpoint."""
        with self._lock:
            if self.active and self.active.spec.id == spec.id and self.active.alive():
                return Endpoint(self.active.base_url, spec.id, spec)
            if self.active:
                self._stop(self.active)
            backend = self._start(spec)
            self.active = backend
            self._event("model.loaded", spec)
            return Endpoint(backend.base_url, spec.id, spec)

    def release(self) -> None:
        """Unload the resident model (called before a heavy media job)."""
        with self._lock:
            if self.active:
                self._stop(self.active)
                self.active = None

    def run_job(self, spec: ModelSpec, command: str, mapping: dict[str, Any], *, cwd: Path | None = None, timeout: int = 7200) -> str:
        """Run a media command with the machine to itself: the resident model is unloaded first."""
        with self.job_lock:
            self.release()
            self._event("job.start", spec, command=command)
            filled = _fill(command, {"python": self.python, "model": spec.id, **mapping})
            if self.dry_run:
                self._event("job.done", spec)
                return f"[dry-run] {filled}"
            proc = subprocess.run(filled, shell=True, cwd=cwd, env=self.env, capture_output=True, text=True, timeout=timeout)
            self._event("job.done" if proc.returncode == 0 else "job.failed", spec, returncode=proc.returncode)
            if proc.returncode != 0:
                raise HostError(f"{spec.name} job failed ({proc.returncode}): {filled}\n{proc.stderr[-2000:]}")
            return proc.stdout

    def resident(self) -> ModelSpec | None:
        return self.active.spec if self.active and self.active.alive() else None

    def resident_gb(self) -> float:
        s = self.resident()
        return s.memory_gb if s else 0.0

    def shutdown(self) -> None:
        self.release()

    # ------------------------------------------------------------------ benchmark
    def benchmark(self, spec: ModelSpec, prompt: str = "Write one sentence about why verified facts matter in marketing.", max_tokens: int = 120) -> dict[str, Any]:
        """Load a brain candidate, time a short generation, unload. Returns tokens/s and errors."""
        result: dict[str, Any] = {"model": spec.name, "id": spec.id, "ok": False}
        if self.dry_run:
            return {**result, "ok": True, "tokens_per_s": 0.0, "dry_run": True}
        t0 = time.time()
        try:
            ep = self.activate(spec)
            result["load_s"] = round(time.time() - t0, 1)
            with httpx.Client(base_url=ep.base_url, timeout=600) as c:
                t1 = time.time()
                r = c.post("/v1/chat/completions", json={"model": ep.model_id, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0.2})
                r.raise_for_status()
                data = r.json()
                dt = time.time() - t1
                toks = data.get("usage", {}).get("completion_tokens") or max_tokens
                result.update(ok=True, tokens_per_s=round(toks / max(dt, 0.01), 1), reply=data["choices"][0]["message"]["content"][:200])
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)[:300]
        finally:
            self.release()
        return result

    # ------------------------------------------------------------------ internals
    def launch_command(self, spec: ModelSpec, port: int) -> str:
        """The server command for ``spec``; a GGUF already fetched into the models folder is launched from disk.

        ``-hf repo:QUANT`` would make llama-server download into its own cache; when the shards are in
        ``<models>/hf`` (scripts/download_models.sh puts them there) they are passed with ``-m``,
        plus ``--mmproj`` for multimodal models.
        """
        cmd = _fill(spec.command, {"python": self.python, "model": spec.id, "port": port})
        if spec.runtime == "llamacpp" and self.models_dir is not None:
            m = re.search(r"-hf\s+(\S+?):(\S+)", cmd)
            if m:
                shards = paths.gguf_shards(spec.id, self.models_dir, m.group(2))
                if shards:
                    repl = f"-m {shlex.quote(str(shards[0]))}"
                    proj = paths.mmproj(spec.id, self.models_dir)
                    if proj is not None and spec.multimodal:
                        repl += f" --mmproj {shlex.quote(str(proj))}"
                    cmd = cmd[: m.start()] + repl + cmd[m.end():]
        return cmd

    def _start(self, spec: ModelSpec) -> Backend:
        if self.dry_run:
            return Backend(spec, base_url="http://dry-run")
        if spec.runtime == "lmstudio":
            if not shutil.which(self.lms_cli):
                raise HostError(f"LM Studio CLI '{self.lms_cli}' not on PATH; run: ~/.lmstudio/bin/lms bootstrap")
            proc = subprocess.run([self.lms_cli, "load", spec.id, "--identifier", spec.id, "-y"], env=self.env, capture_output=True, text=True, timeout=self.start_timeout)
            if proc.returncode != 0:
                raise HostError(f"lms load {spec.id} failed: {proc.stderr[-500:]}")
            return Backend(spec, base_url=self.lmstudio_url, started_at=time.time())
        if spec.runtime in ("llamacpp", "mlx-server", "http-service"):
            if not spec.command:
                raise HostError(f"{spec.name} has no launch command")
            port = spec.port or 8081
            cmd = self.launch_command(spec, port)
            exe = shlex.split(cmd)[0]
            if not shutil.which(exe) and not Path(exe).exists():
                raise HostError(f"'{exe}' is not installed (needed for {spec.name})")
            log = open(self.state_dir / f"{_slug(spec.name)}.log", "ab") if self.state_dir else subprocess.DEVNULL
            process = subprocess.Popen(cmd, shell=True, stdout=log, stderr=subprocess.STDOUT, env=self.env)
            base_url = f"http://127.0.0.1:{port}"
            health = "/health" if spec.runtime == "llamacpp" else "/v1/models" if spec.runtime == "mlx-server" else "/"
            if not _wait_http(base_url + health, self.start_timeout, process):
                process.kill()
                raise HostError(f"{spec.name} did not come up on {base_url} within {self.start_timeout:.0f}s (see state/{_slug(spec.name)}.log)")
            return Backend(spec, base_url=base_url, process=process, started_at=time.time())
        # mlx-cli / python-script / comfyui: nothing resident
        return Backend(spec, base_url="")

    def _stop(self, backend: Backend) -> None:
        spec = backend.spec
        if self.dry_run:
            self._event("model.unloaded", spec)
            return
        if spec.runtime == "lmstudio" and shutil.which(self.lms_cli):
            subprocess.run([self.lms_cli, "unload", spec.id], env=self.env, capture_output=True, text=True, timeout=120)
        elif backend.process is not None and backend.process.poll() is None:
            backend.process.terminate()
            try:
                backend.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                backend.process.kill()
        self._event("model.unloaded", spec)

    def _event(self, kind: str, spec: ModelSpec, **extra: Any) -> None:
        e = {"kind": kind, "model": spec.name, "memory_gb": spec.memory_gb, "at": time.time(), **extra}
        self.history.append(e)
        self.history = self.history[-200:]
        self.on_event(e)


def _fill(template: str, mapping: dict[str, Any]) -> str:
    out = template
    for k, v in mapping.items():
        out = out.replace("{" + k + "}", shlex.quote(str(v)) if k not in ("port",) else str(v))
    return out


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


def _wait_http(url: str, timeout: float, process: subprocess.Popen) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            r = httpx.get(url, timeout=3)
            if r.status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


class BrainChoice:
    """Remembers which brain candidate passed the benchmark on this machine."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def chosen_name(self) -> str | None:
        return self.load().get("brain")
