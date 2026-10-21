"""The models folder: one place for every model, internal disk or external SSD."""
import os
from pathlib import Path

from agency.models import paths, registry
from agency.models.host import ModelHost


def _fake_cache(root: Path, repo: str, files: list[str], commit: str = "abc123") -> Path:
    repo_dir = root / "hf" / "hub" / ("models--" + repo.replace("/", "--"))
    snap = repo_dir / "snapshots" / commit
    for f in files:
        p = snap / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"gguf")
    (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
    (repo_dir / "refs" / "main").write_text(commit)
    return snap


def test_models_dir_precedence(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AGENCY_MODELS", raising=False)
    assert paths.models_dir("") == Path.home() / "models"
    assert paths.models_dir("~/elsewhere") == Path.home() / "elsewhere"
    monkeypatch.setenv("AGENCY_MODELS", "/Volumes/AI/models")
    assert paths.models_dir("~/elsewhere") == Path("/Volumes/AI/models")
    env = paths.runtime_env(Path("/Volumes/AI/models"))
    assert env["HF_HOME"] == "/Volumes/AI/models/hf" and env["LLAMA_CACHE"] == "/Volumes/AI/models/llama.cpp"
    assert paths.is_external(Path("/Volumes/AI/models")) and not paths.is_external(tmp_path)
    assert paths.volume_root(Path("/Volumes/AI/models/hf")) == Path("/Volumes/AI")


def test_prefetched_gguf_is_launched_from_disk_with_its_projector(tmp_path: Path):
    brain = registry.QWEN38_FLASH_NEXT
    _fake_cache(tmp_path, brain.id, ["UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00002-of-00003.gguf", "UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf", "UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00003-of-00003.gguf", "mmproj-BF16.gguf", "mmproj-F16.gguf", "Q8_0/Qwen3.8-Flash-Next-Q8_0-00001-of-00006.gguf"])
    shards = paths.gguf_shards(brain.id, tmp_path, "UD-IQ4_XS")
    assert [p.name[-19:] for p in shards] == ["00001-of-00003.gguf", "00002-of-00003.gguf", "00003-of-00003.gguf"]
    assert paths.mmproj(brain.id, tmp_path).name == "mmproj-BF16.gguf"
    host = ModelHost(dry_run=True, models_dir=tmp_path)
    cmd = host.launch_command(brain, 8081)
    assert "-hf" not in cmd and "UD-IQ4_XS-00001-of-00003.gguf" in cmd and "--mmproj" in cmd and "mmproj-BF16.gguf" in cmd
    assert "--port 8081" in cmd and "--jinja" in cmd
    assert host.env["HF_HOME"] == str(tmp_path / "hf")


def test_without_prefetched_files_llama_server_downloads_itself(tmp_path: Path):
    host = ModelHost(dry_run=True, models_dir=tmp_path)
    cmd = host.launch_command(registry.QWEN38_FLASH_NEXT, 8081)
    assert "-hf unsloth/Qwen3.8-Flash-Next-GGUF:UD-IQ4_XS" in cmd
    assert ModelHost(dry_run=True).env is None


def test_disk_status_and_speed(tmp_path: Path):
    d = paths.disk_status(tmp_path)
    assert d["exists"] and d["mounted"] and not d["external"] and d["free_gb"] > 0
    unplugged = paths.disk_status(Path("/Volumes/NoSuchDisk/models"))
    assert unplugged["external"] and not unplugged["mounted"] and not unplugged["exists"]
    (tmp_path / "x.bin").write_bytes(b"0" * 1_000_000)
    assert paths.used_gb(tmp_path) == 0.0   # rounds to GB
    speed = paths.read_speed_mb_s(tmp_path, size_mb=16)
    assert speed is None or speed > 0
    assert not (tmp_path / ".agency-speed-test").exists()
    assert "fast" in paths.speed_verdict(5000) and "slow" in paths.speed_verdict(300) and "not measured" == paths.speed_verdict(None)


def test_disk_plan_counts_each_model_once_and_comfy_yaml():
    plan = registry.disk_plan("m5pro-64gb")
    assert plan["unsloth/Qwen3.8-Flash-Next-GGUF"] == 94.6
    assert 200 < sum(plan.values()) < 320
    assert registry.resolve("video").id == "dgrauet/ltx-2.5-mlx-q8" and registry.resolve("video", "128gb").name == "LTX-2.5 (bf16)"
    y = paths.comfy_extra_paths_yaml(Path("/Volumes/AI/models"))
    assert "base_path: /Volumes/AI/models/comfyui" in y and "  unet: unet" in y


def test_dotenv_sets_models_dir_for_settings(monkeypatch, tmp_path: Path):
    import importlib

    from agency import settings as settings_mod

    monkeypatch.delenv("AGENCY_MODELS", raising=False)
    monkeypatch.delenv("AGENCY_ASSETS", raising=False)
    (tmp_path / ".env").write_text("AGENCY_MODELS=/Volumes/AI/models\nAGENCY_ASSETS=\n")   # empty value = not set
    monkeypatch.setenv("AGENCY_ROOT", str(tmp_path))
    importlib.reload(settings_mod)
    try:
        assert os.environ["AGENCY_MODELS"] == "/Volumes/AI/models"
        assert "AGENCY_ASSETS" not in os.environ and settings_mod.ASSETS_DIR == tmp_path / "assets"
        s = settings_mod.Settings()
        assert s.models_dir == Path("/Volumes/AI/models")
    finally:
        monkeypatch.delenv("AGENCY_MODELS", raising=False)
        monkeypatch.delenv("AGENCY_ROOT", raising=False)
        importlib.reload(settings_mod)


def test_video_sides_rounded_to_32():
    from agency.media.video import _round32

    assert _round32(1080) == 1088 and _round32(1920) == 1920 and _round32(720) == 704 and _round32(10) == 32
