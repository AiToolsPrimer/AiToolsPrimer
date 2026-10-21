"""Where the model files live: one folder, on the internal disk or on an external SSD.

Pick the folder once (``AGENCY_MODELS`` in ``.env``, or ``hardware.models_dir`` in
``config/agency.yaml``; default ``~/models``).  Everything the agency downloads or runs
goes under it:

  <models>/hf          Hugging Face cache: the Flash-Next GGUF, Qwen-Image (mflux), the LTX-2.5
                       MLX pack, Step-Audio-EditX, Kokoro, Parakeet (every runtime that uses
                       huggingface_hub reads this cache, so nothing is downloaded twice)
  <models>/llama.cpp   llama.cpp's own cache, used only if a GGUF was not pre-fetched
  <models>/lmstudio    LM Studio's models directory (set once in LM Studio: My Models -> Models Directory)
  <models>/comfyui     ComfyUI model folders, linked through ComfyUI/extra_model_paths.yaml

Every runtime the host starts inherits ``HF_HOME`` / ``LLAMA_CACHE`` pointing here, so an
external SSD mounted at ``/Volumes/AI`` works exactly like the internal disk.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

DEFAULT_DIR = Path.home() / "models"
SPEED_FAST_MB_S = 1500.0   # Thunderbolt / USB4 NVMe: the brain's n-gram table can live here
SPEED_OK_MB_S = 700.0      # USB 3.x NVMe: works, the brain is slower


def models_dir(configured: str = "") -> Path:
    """``AGENCY_MODELS`` (environment or .env) wins, then the YAML setting, then ``~/models``."""
    raw = os.environ.get("AGENCY_MODELS", "").strip() or (configured or "").strip() or str(DEFAULT_DIR)
    return Path(raw).expanduser()


def runtime_env(root: Path) -> dict[str, str]:
    """Environment for every runtime process so that all caches sit under ``root``."""
    hf = root / "hf"
    return {
        "HF_HOME": str(hf),
        "HF_HUB_CACHE": str(hf / "hub"),
        "HUGGINGFACE_HUB_CACHE": str(hf / "hub"),
        "LLAMA_CACHE": str(root / "llama.cpp"),
        "AGENCY_MODELS": str(root),
    }


def layout(root: Path) -> dict[str, Path]:
    return {"hf": root / "hf", "llama.cpp": root / "llama.cpp", "lmstudio": root / "lmstudio", "comfyui": root / "comfyui"}


# ------------------------------------------------------------------ Hugging Face cache lookups (no network)

def hub_snapshot(repo_id: str, root: Path) -> Path | None:
    """The local snapshot folder of a repo in ``<root>/hf/hub``, or None if it was never fetched."""
    repo = root / "hf" / "hub" / ("models--" + repo_id.replace("/", "--"))
    snaps = repo / "snapshots"
    if not snaps.is_dir():
        return None
    ref = repo / "refs" / "main"
    if ref.exists():
        cand = snaps / ref.read_text().strip()
        if cand.is_dir():
            return cand
    found = sorted((p for p in snaps.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def gguf_shards(repo_id: str, root: Path, tag: str) -> list[Path]:
    """GGUF files of a quantization (``tag`` like ``UD-IQ4_XS``) in the local snapshot, first shard first."""
    snap = hub_snapshot(repo_id, root)
    if snap is None:
        return []
    tag_l = tag.lower()
    return sorted(p for p in snap.rglob("*.gguf") if tag_l in p.name.lower() and "mmproj" not in p.name.lower())


def mmproj(repo_id: str, root: Path) -> Path | None:
    """The vision projector file of a multimodal GGUF repo, BF16 preferred."""
    snap = hub_snapshot(repo_id, root)
    if snap is None:
        return None
    files = sorted(snap.rglob("mmproj*.gguf"), key=lambda p: (0 if "bf16" in p.name.lower() else 1, p.name))
    return files[0] if files else None


# ------------------------------------------------------------------ disk facts for the doctor and the panel

def is_external(root: Path) -> bool:
    return str(root).startswith("/Volumes/")


def volume_root(root: Path) -> Path:
    """``/Volumes/AI`` for ``/Volumes/AI/models``; the path itself elsewhere."""
    parts = root.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
        return Path(*parts[:3])
    return root


def disk_status(root: Path) -> dict:
    """Existence, mount state and free space of the models folder (cheap: one statvfs)."""
    vol = volume_root(root)
    mounted = (not is_external(root)) or os.path.ismount(vol)
    out = {"path": str(root), "volume": str(vol), "external": is_external(root), "mounted": mounted, "exists": root.exists(), "free_gb": None, "total_gb": None}
    probe = root if root.exists() else (vol if vol.exists() else root.parent if root.parent.exists() else None)
    if probe is not None and mounted:
        try:
            u = shutil.disk_usage(probe)
            out["free_gb"] = round(u.free / 1e9, 1)
            out["total_gb"] = round(u.total / 1e9, 1)
        except OSError:
            pass
    return out


def used_gb(root: Path) -> float:
    """Space taken by the models already on disk (walks the folder; seconds on a large tree)."""
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return round(total / 1e9, 1)


def read_speed_mb_s(root: Path, size_mb: int = 256) -> float | None:
    """Sequential read speed of the disk under ``root``, bypassing the page cache where the OS allows.

    Writes a temporary file of ``size_mb`` and reads it back; returns MB/s or None on any error.
    """
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".agency-speed-test"
    chunk = 8 * 1024 * 1024
    try:
        with open(probe, "wb") as f:
            block = os.urandom(chunk)
            for _ in range(max(1, size_mb * 1024 * 1024 // chunk)):
                f.write(block)
            f.flush()
            os.fsync(f.fileno())
        fd = os.open(probe, os.O_RDONLY)
        try:
            if sys.platform == "darwin":
                import fcntl

                fcntl.fcntl(fd, 48, 1)                    # F_NOCACHE: read from the disk, not from memory
            elif hasattr(os, "posix_fadvise"):
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            t0 = time.perf_counter()
            n = 0
            while True:
                b = os.read(fd, chunk)
                if not b:
                    break
                n += len(b)
            dt = time.perf_counter() - t0
        finally:
            os.close(fd)
        return round(n / 1e6 / max(dt, 1e-6), 0)
    except OSError:
        return None
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def speed_verdict(mb_s: float | None) -> str:
    if mb_s is None:
        return "not measured"
    if mb_s >= SPEED_FAST_MB_S:
        return "fast: fine for every model, including the brain's n-gram table"
    if mb_s >= SPEED_OK_MB_S:
        return "ok: models load in a minute or two; the brain reads its n-gram table from here, expect fewer tokens/s"
    return "slow: fine for images, video and voices; for the brain prefer the internal disk or the 27B"


# ------------------------------------------------------------------ helpers for the setup scripts

def comfy_extra_paths_yaml(root: Path) -> str:
    base = root / "comfyui"
    folders = ("checkpoints", "diffusion_models", "unet", "text_encoders", "clip", "vae", "loras", "upscale_models")
    lines = ["# written by the agency: model folders on the models disk", "agency:", f"  base_path: {base}"]
    lines += [f"  {f}: {f}" for f in folders]
    return "\n".join(lines) + "\n"
