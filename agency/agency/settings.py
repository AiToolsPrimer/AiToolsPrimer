"""Configuration: brand, hardware profile, toggles, platform credentials.

Two layers:
  * ``config/agency.yaml``  (copied from ``agency.example.yaml``) holds the static setup.
  * ``state/toggles.json``   holds the switches the control panel flips at runtime.

Secrets are never written to YAML: every platform credential is read from the
environment (or a ``.env`` file next to the config).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("AGENCY_ROOT", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
STATE_DIR = Path(os.environ.get("AGENCY_STATE", ROOT / "state"))
ASSETS_DIR = Path(os.environ.get("AGENCY_ASSETS", ROOT / "assets"))


class Brand(BaseModel):
    name: str = "AI Tools Primer"
    site: str = "https://aitoolsprimer.com"
    tagline: str = "Independent, plain-English guides to AI tools and everyday software."
    language: str = "en"
    voice: str = (
        "Plain English, specific, verified. No hype, no affiliate links, no paid placements. "
        "Say when something was checked; say when it could not be verified."
    )
    audience: str = "People choosing and using AI tools and everyday software."
    pillars: list[str] = Field(
        default_factory=lambda: [
            "AI tools compared and explained",
            "Documents, PDF, images, video software",
            "Windows, Mac and iPhone how-tos",
            "Passwords, scams, malware, data leaks",
        ]
    )
    handles: dict[str, str] = Field(default_factory=dict)
    banned_claims: list[str] = Field(
        default_factory=lambda: ["guaranteed", "best in the world", "#1", "100% safe"]
    )


class Hardware(BaseModel):
    profile: str = "m5pro-64gb"
    unified_memory_gb: int = 64
    gpu_budget_gb: int = 56  # after `sudo sysctl iogpu.wired_limit_mb=57344`; macOS default is ~70-75% of unified memory
    one_model_at_a_time: bool = True


class Models(BaseModel):
    brain: Literal["auto", "flash-next", "27b"] = "auto"   # auto = whatever the doctor benchmark chose on this Mac
    overrides: dict[str, str] = Field(default_factory=dict)  # task -> model name from the registry
    team_mode: Literal["team", "best_of_n", "single"] = "team"  # team = brain + second writer, brain judges
    thinking_effort: Literal["xhigh", "high", "medium", "low"] = "xhigh"   # brain decisions, judging, fact-check
    draft_effort: Literal["xhigh", "high", "medium", "low"] = "medium"    # first drafts
    candidates_per_draft: int = 2


class Runtimes(BaseModel):
    lmstudio_url: str = "http://127.0.0.1:1234"
    llamacpp_port: int = 8081
    comfyui_url: str = "http://127.0.0.1:8188"
    acestep_url: str = "http://127.0.0.1:7867"
    lms_cli: str = "lms"  # LM Studio CLI, used to load/unload models
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    python: str = "python3"


class VideoDefaults(BaseModel):
    max_seconds: int = 240
    clip_seconds: int = 8  # native generated clip length
    fps: int = 24
    width: int = 1920
    height: int = 1080
    shorts_seconds: int = 45
    music_db: float = -18.0
    subtitles: Literal["burned", "sidecar", "none"] = "sidecar"
    default_visual_mode: Literal["generated", "image_motion", "mixed"] = "mixed"


class Media(BaseModel):
    image_command: str = ""      # overrides the mflux template from the registry (or set to "comfyui")
    image_steps: int = 20
    video_command: str = ""      # overrides the LTX-2.5 MLX template from the registry
    tts_voice: str = "default"   # path to a 5-10 s reference WAV for Chatterbox cloning, or a Kokoro voice id
    music_endpoint: str = "/generate"
    music_payload: dict[str, Any] = Field(default_factory=lambda: {"prompt": "{prompt}", "lyrics": "[inst]", "duration": "{seconds}", "format": "wav"})
    presenter_image: str = "config/presenter.png"


class Limits(BaseModel):
    posts_per_platform_per_day: int = 4
    replies_per_platform_per_hour: int = 10
    articles_per_week: int = 3
    videos_per_week: int = 3
    quiet_hours_utc: tuple[int, int] = (1, 6)  # no publishing between 01:00 and 06:00 UTC
    max_revisions: int = 2


class Director(BaseModel):
    provider: Literal["local", "anthropic"] = "local"
    anthropic_model: str = "claude-fable-5-1"
    daily_cycle_utc: str = "07:30"
    community_every_minutes: int = 30
    analyst_daily_utc: str = "22:00"
    scout_weekly: str = "mon 09:00"


PublishMode = Literal["api", "browser", "intent", "manual", "off"]

# Platforms whose API costs money or does not exist publish through the agent's browser with your click.
DEFAULT_MODES: dict[str, str] = {
    "x": "browser", "medium": "browser", "substack": "browser", "linkedin_articles": "browser", "blogger": "browser",
    "dailymotion": "browser", "reddit": "manual", "quora": "manual", "hackernews": "manual", "stackexchange": "manual",
    "flipboard": "intent",
}


class PlatformConfig(BaseModel):
    enabled: bool = False
    mode: PublishMode | None = None   # None = default for that platform (api, or DEFAULT_MODES)
    env_prefix: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class Settings(BaseModel):
    brand: Brand = Brand()
    hardware: Hardware = Hardware()
    models: Models = Models()
    runtimes: Runtimes = Runtimes()
    video: VideoDefaults = VideoDefaults()
    media: Media = Media()
    limits: Limits = Limits()
    director: Director = Director()
    platforms: dict[str, PlatformConfig] = Field(default_factory=dict)
    dry_run: bool = True  # nothing leaves the machine until this is False
    panel_host: str = "127.0.0.1"
    panel_port: int = 8765
    ui_language: str = "en"

    def mode_for(self, platform: str) -> str:
        cfg = self.platforms.get(platform)
        if cfg and cfg.mode:
            return cfg.mode
        return DEFAULT_MODES.get(platform, "api")

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or CONFIG_DIR / "agency.yaml"
        if not path.exists():
            path = CONFIG_DIR / "agency.example.yaml"
        data: dict[str, Any] = {}
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}
        _load_dotenv(ROOT / ".env")
        return cls.model_validate(data)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# --------------------------------------------------------------------------- toggles

TOGGLE_DEFAULTS: dict[str, bool] = {
    # Master switches
    "master_enabled": True,          # kill switch: False freezes every agent
    "publishing": False,             # nothing is published while False (approval queue still fills)
    "approval_required": True,       # every outgoing action waits for a human click
    # Agent capabilities
    "write_posts": True,
    "write_articles": True,
    "make_images": True,
    "make_videos": True,
    "make_shorts": True,
    "make_voiceover": True,
    "make_music": True,
    "auto_reply_own_posts": False,   # answer comments under our own posts
    "draft_external_engagement": False,  # draft (never post) replies on other people's posts
    "discover_platforms": True,      # the scout looks for new places to be present
    "prepare_signup_kits": False,    # when a platform is found, build bio/avatar/first posts
    "collect_metrics": True,
    # Hard guarantees (not switchable from the panel; listed so the UI can show them)
    "block_payments": True,
    "block_account_creation": True,
    "block_mass_actions": True,
}

LOCKED_TOGGLES = {"block_payments", "block_account_creation", "block_mass_actions"}


class Toggles:
    """Thread-safe, file-backed switches the panel can flip at runtime."""

    def __init__(self, path: Path | None = None):
        self.path = path or STATE_DIR / "toggles.json"
        self._lock = threading.Lock()
        self._values = dict(TOGGLE_DEFAULTS)
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text())
                for k, v in stored.items():
                    if k in TOGGLE_DEFAULTS and k not in LOCKED_TOGGLES:
                        self._values[k] = bool(v)
            except json.JSONDecodeError:
                pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._values, indent=2, sort_keys=True))

    def get(self, name: str) -> bool:
        with self._lock:
            return self._values[name]

    def set(self, name: str, value: bool) -> None:
        if name in LOCKED_TOGGLES:
            raise PermissionError(f"{name} is a hard guarantee and cannot be switched off")
        if name not in TOGGLE_DEFAULTS:
            raise KeyError(name)
        with self._lock:
            self._values[name] = bool(value)
            self._save()

    def all(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._values)

    # Per-platform publishing switches live alongside the global ones.
    def platform_enabled(self, platform: str) -> bool:
        with self._lock:
            return self._values.get(f"platform:{platform}", True)

    def set_platform(self, platform: str, value: bool) -> None:
        with self._lock:
            self._values[f"platform:{platform}"] = bool(value)
            self._save()
