"""Wires settings, memory, models, media, platforms and agents into one ``Agency`` object."""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

from agency.agents.analyst import Analyst
from agency.agents.community import CommunityManager
from agency.agents.creative import ImageAgent, VideoAgent
from agency.agents.safety import Safety
from agency.agents.scout import Scout
from agency.agents.strategist import Strategist
from agency.agents.writer import Writer
from agency.director.orchestrator import Director
from agency.llm.client import AnthropicLLM, LocalLLM
from agency.media.audio import ASR, TTS, Music
from agency.media.ffmpeg import FF
from agency.media.images import Images
from agency.media.runner import ComfyUI, ModelManager
from agency.media.video import VideoAssembler
from agency.memory.store import Store
from agency.models import registry
from agency.platforms import build_all
from agency.safety.payment_guard import GuardedHTTP
from agency.safety.policy import PolicyEngine
from agency.settings import ASSETS_DIR, ROOT, STATE_DIR, Settings, Toggles

log = logging.getLogger("agency")


class Agency:
    def __init__(self, settings: Settings | None = None, *, dry_run: bool | None = None, llm: Any = None, state_dir: Path | None = None, assets_dir: Path | None = None):
        self.settings = settings or Settings.load()
        self.dry_run = self.settings.dry_run if dry_run is None else dry_run
        self.state_dir = state_dir or STATE_DIR
        self.assets_dir = assets_dir or ASSETS_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.toggles = Toggles(self.state_dir / "toggles.json")
        self.events: list[str] = []

        s = self.settings
        profile = s.hardware.profile
        self.models = {task: registry.resolve(task, profile) for task in registry.ASSIGNMENTS}

        # Runtimes
        self.comfy = ComfyUI(s.runtimes.comfyui_url)
        self.manager = ModelManager(s.runtimes.lms_cli, s.hardware.gpu_budget_gb, comfy=self.comfy, dry_run=self.dry_run)
        self.ff = FF(s.runtimes.ffmpeg, s.runtimes.ffprobe)

        # Brain
        self.local_llm = llm or LocalLLM(s.runtimes.lmstudio_url, self.models["director"])
        if s.director.provider == "anthropic" and llm is None:
            self.director_llm = AnthropicLLM(s.director.anthropic_model)
        else:
            self.director_llm = self.local_llm
        self.vision_llm = llm or LocalLLM(s.runtimes.lmstudio_url, self.models["vision"])
        self.guard_llm = None if llm else LocalLLM(s.runtimes.lmstudio_url, self.models["safety"])

        # Memory
        embed = None if (llm or self.dry_run) else (lambda texts: self.local_llm.embed(texts, self.models["embeddings"].id))
        self.store = Store(self.state_dir / "agency.db", embed=embed)

        # Network
        self.http = GuardedHTTP(audit=self.store.audit_http)
        self.platforms = build_all(s, self.http, dry_run=self.dry_run)

        # Media
        wf = ROOT / "workflows"
        self.images = Images(self.models["image"], self.comfy, wf, self.ff, dry_run=self.dry_run, python=s.runtimes.python, command=s.media.image_command)
        self.tts = TTS(self.models["tts"], self.ff, python=s.runtimes.python, voice=s.media.tts_voice, dry_run=self.dry_run, root=ROOT)
        self.asr = ASR(self.models["asr"], dry_run=self.dry_run)
        self.music = Music(s.runtimes.acestep_url, self.ff, dry_run=self.dry_run, endpoint=s.media.music_endpoint, payload=s.media.music_payload) if self.toggles.get("make_music") else None
        presenter = ROOT / s.media.presenter_image
        self.assembler = VideoAssembler(
            ff=self.ff, tts=self.tts, asr=self.asr, music=self.music, images=self.images, video_spec=self.models["video"], avatar_spec=self.models["avatar"],
            comfy=self.comfy, workflows_dir=wf, defaults=s.video, python=s.runtimes.python, dry_run=self.dry_run, video_command=s.media.video_command,
            presenter_image=presenter if presenter.exists() else None, progress=self.note,
        )

        # Agents
        brand = s.brand
        self.writer = Writer(self.local_llm, self.store, brand)
        self.strategist = Strategist(self.local_llm, self.store, brand, self.http)
        self.safety = Safety(self.local_llm, self.store, brand, guard=self.guard_llm)
        self.image_agent = ImageAgent(self.local_llm, self.store, brand, self.images, self.assets_dir, vision=self.vision_llm)
        self.video_agent = VideoAgent(self.local_llm, self.store, brand, self.writer, self.assembler, self.assets_dir, max_seconds=s.video.max_seconds)
        self.policy = PolicyEngine(self.toggles, s.limits, count_recent=lambda platform, kind, window: self.store.count_recent_actions(platform, kind.value, window))

        self.director = Director(
            llm=self.director_llm, store=self.store, settings=s, toggles=self.toggles, policy=self.policy, platforms=self.platforms,
            strategist=self.strategist, writer=self.writer, safety=self.safety, image_agent=self.image_agent, video_agent=self.video_agent, log=self.note,
        )
        self.community = CommunityManager(self.local_llm, self.store, brand, self.writer, self.platforms, self.director.submit, safety=self.safety)
        self.scout = Scout(self.local_llm, self.store, brand, self.http, self.director.submit, image_agent=self.image_agent)
        self.analyst = Analyst(self.local_llm, self.store, brand, self.platforms, self.director.submit)
        self.director.community, self.director.scout, self.director.analyst = self.community, self.scout, self.analyst

    def note(self, msg: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.events.append(f"{stamp} {msg}")
        self.events = self.events[-300:]
        log.info(msg)

    # ------------------------------------------------------------------ status for the panel / doctor
    def status(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "profile": self.settings.hardware.profile,
            "director_provider": self.settings.director.provider,
            "models": {task: {"name": m.name, "id": m.id, "runtime": m.runtime, "memory_gb": m.memory_gb, "license": m.license} for task, m in self.models.items()},
            "resident_gb": self.manager.resident_gb(),
            "budget_gb": self.settings.hardware.gpu_budget_gb,
            "platforms": {n: {"label": p.label, "configured": p.configured(), "missing": p.missing_env(), "enabled": self.toggles.platform_enabled(n), "kinds": sorted(p.kinds), "note": p.free_tier_note} for n, p in self.platforms.items()},
            "toggles": self.toggles.all(),
            "queued": len(self.store.list_content(status="queued")),
            "published": len(self.store.list_content(status="published")),
            "events": self.events[-50:],
        }
