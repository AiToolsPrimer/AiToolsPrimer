"""Wires settings, memory, the model host, media, platforms and agents into one ``Agency``."""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

import os

from agency.agents.analyst import Analyst
from agency.agents.authority import Authority
from agency.agents.mail import MailAgent, Mailbox
from agency.agents.network import NetworkAgent
from agency.agents.pr import PRAgent
from agency.agents.questions import QuestionsAgent
from agency.agents.community import CommunityManager
from agency.agents.creative import ImageAgent, VideoAgent
from agency.agents.factcheck import FactChecker
from agency.agents.safety import Safety
from agency.agents.team import Team
from agency.agents.scout import Scout
from agency.agents.strategist import Strategist
from agency.agents.writer import Writer
from agency.director.orchestrator import Director
from agency.knowledge.base import KnowledgeBase
from agency.knowledge.news_watch import NewsWatch
from agency.llm.client import AnthropicLLM
from agency.llm.hosted import HostedLLM
from agency.media.audio import ASR, TTS, Music
from agency.media.ffmpeg import FF
from agency.media.images import Images
from agency.media.runner import ComfyUI
from agency.media.video import VideoAssembler
from agency.memory.store import Store
from agency.models import registry
from agency.models.host import BrainChoice, ModelHost
from agency.office import Office
from agency.browser.operator import BrowserOperator, default_executable
from agency.platforms import build_all
from agency.platforms.indexnow import IndexNow
from agency.platforms.podcast import PodcastFeed
from agency.safety.payment_guard import GuardedHTTP
from agency.safety.policy import PolicyEngine
from agency.settings import ASSETS_DIR, ROOT, STATE_DIR, Prefs, Settings, Toggles

log = logging.getLogger("agency")


class Agency:
    def __init__(self, settings: Settings | None = None, *, dry_run: bool | None = None, llm: Any = None, state_dir: Path | None = None, assets_dir: Path | None = None, http_transport: Any = None):
        self.settings = settings or Settings.load()
        self.dry_run = self.settings.dry_run if dry_run is None else dry_run
        self.state_dir = state_dir or STATE_DIR
        self.assets_dir = assets_dir or ASSETS_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.toggles = Toggles(self.state_dir / "toggles.json")
        self.prefs = Prefs(self.state_dir / "prefs.json")
        self.events: list[str] = []
        self.office = Office()
        s = self.settings

        # ---------------------------------------------------------------- models (one at a time)
        self.models: dict[str, registry.ModelSpec] = {task: registry.resolve(task, s.hardware.profile, s.models.overrides) for task in registry.ASSIGNMENTS}
        self.brain_choice = BrainChoice(self.state_dir / "brain.json")
        self.models["brain"] = self._pick_brain()
        self.host = ModelHost(lms_cli=s.runtimes.lms_cli, lmstudio_url=s.runtimes.lmstudio_url, python=s.runtimes.python, state_dir=self.state_dir, dry_run=self.dry_run or llm is not None, on_event=self._model_event)
        self.comfy = ComfyUI(s.runtimes.comfyui_url)
        self.ff = FF(s.runtimes.ffmpeg, s.runtimes.ffprobe)

        brain_fallback = next((m for m in registry.candidates("brain") if m.id != self.models["brain"].id), None)
        if llm is not None:                       # tests inject a fake model for everything
            self.brain = self.second = self.embed_llm = self.guard_llm = llm
        else:
            self.brain = HostedLLM(self.host, self.models["brain"], thinking_effort=s.models.thinking_effort, fallback=brain_fallback)
            self.second = HostedLLM(self.host, self.models["second_writer"], thinking_effort=s.models.draft_effort)
            self.embed_llm = HostedLLM(self.host, self.models["embeddings"])
            self.guard_llm = HostedLLM(self.host, self.models["safety"], thinking_effort="low")
        self.director_llm = AnthropicLLM(s.director.anthropic_model) if (s.director.provider == "anthropic" and llm is None) else self.brain

        # ---------------------------------------------------------------- memory & network
        embed = None if (llm is not None or self.dry_run) else (lambda texts: self.embed_llm.embed(texts))
        self.store = Store(self.state_dir / "agency.db", embed=embed)
        self.http = GuardedHTTP(audit=self.store.audit_http, transport=http_transport)
        self.platforms = build_all(s, self.http, dry_run=self.dry_run)
        self.indexnow = IndexNow(self.http, s.brand.site, key_dir=self.state_dir, dry_run=self.dry_run)
        exe = s.browser.executable or (None if s.browser.channel else default_executable())
        self.operator = BrowserOperator(ROOT / s.browser.profile_dir if not Path(s.browser.profile_dir).is_absolute() else Path(s.browser.profile_dir), self.assets_dir / "screenshots", headless=s.browser.headless, executable_path=exe, channel=(s.browser.channel or None) if not exe else None, dry_run=self.dry_run, pace_s=s.browser.pace_seconds, on_event=lambda kind, text: self.office.emit(kind, "operator", text))

        # ---------------------------------------------------------------- media
        wf = ROOT / "workflows"
        self.images = Images(self.models["image"], self.host, self.comfy, wf, self.ff, dry_run=self.dry_run, command=s.media.image_command, steps=s.media.image_steps, edit_spec=self.models["image_edit"])
        tts_fallbacks = tuple(m for m in registry.candidates("tts") if m.id != self.models["tts"].id)
        self.tts = TTS(self.models["tts"], self.host, self.ff, voice=s.media.tts_voice, dry_run=self.dry_run, root=ROOT, fallbacks=tts_fallbacks)
        self.asr = ASR(self.models["asr"], self.host, dry_run=self.dry_run)
        self.music = Music(self.models["music"], self.host, self.ff, dry_run=self.dry_run, endpoint=s.media.music_endpoint, payload=s.media.music_payload) if self.toggles.get("make_music") else None
        presenter = ROOT / s.media.presenter_image
        self.assembler = VideoAssembler(
            ff=self.ff, tts=self.tts, asr=self.asr, music=self.music, images=self.images, video_spec=self.models["video"], avatar_spec=self.models["avatar"],
            comfy=self.comfy, workflows_dir=wf, defaults=s.video, host=self.host, python=s.runtimes.python, dry_run=self.dry_run, video_command=s.media.video_command,
            presenter_image=presenter if presenter.exists() else None, progress=self._video_progress,
        )

        # ---------------------------------------------------------------- knowledge
        self.kb = KnowledgeBase(ROOT / "knowledge")

        # ---------------------------------------------------------------- agents
        brand = s.brand
        self.writer = Writer(self.brain, self.store, brand)
        self.writer.kb = self.kb
        self.second_writer = None
        if llm is None and s.models.team_mode == "team":
            self.second_writer = Writer(self.second, self.store, brand)
            self.second_writer.kb = self.kb
        self.team = Team(self.writer, self.second_writer, judge=self.brain, mode=s.models.team_mode, candidates=s.models.candidates_per_draft)
        self.factcheck = FactChecker(self.brain, self.store, brand, self.http)
        self.strategist = Strategist(self.brain, self.store, brand, self.http, indexnow=self.indexnow, toggles=self.toggles)
        self.podcast = PodcastFeed(self.assets_dir / "podcast", brand.site, f"{brand.name} Audio", brand.tagline, s.media.podcast_base_url or f"{brand.site.rstrip('/')}/podcast", self.ff, author=brand.name)
        self.safety = Safety(self.brain, self.store, brand, guard=self.guard_llm if llm is None else None)
        self.image_agent = ImageAgent(self.brain, self.store, brand, self.images, self.assets_dir, vision=self.brain)
        self.video_agent = VideoAgent(self.brain, self.store, brand, self.writer, self.assembler, self.assets_dir, max_seconds=s.video.max_seconds)
        self.policy = PolicyEngine(self.toggles, s.limits, count_recent=lambda platform, kind, window: self.store.count_recent_actions(platform, kind.value, window))
        self.director = Director(
            llm=self.director_llm, store=self.store, settings=s, toggles=self.toggles, policy=self.policy, platforms=self.platforms,
            strategist=self.strategist, writer=self.writer, safety=self.safety, image_agent=self.image_agent, video_agent=self.video_agent, kb=self.kb,
            factcheck=self.factcheck, team=self.team, operator=self.operator, mode_for=self.mode_for, log=self.note,
        )
        self.director.podcast = self.podcast if self.toggles.get("make_podcast") else None
        self.news_watch = NewsWatch(self.brain, self.store, brand, self.http, self.kb)
        self.community = CommunityManager(self.brain, self.store, brand, self.writer, self.platforms, self.director.submit, safety=self.safety, factcheck=self.factcheck)
        self.scout = Scout(self.brain, self.store, brand, self.http, self.director.submit, image_agent=self.image_agent)
        self.analyst = Analyst(self.brain, self.store, brand, self.platforms, self.director.submit)
        self.authority = Authority(self.store, self.http, dry_run=self.dry_run)
        mailbox = None
        if os.environ.get("MAIL_USER") and os.environ.get("MAIL_APP_PASSWORD"):
            mailbox = Mailbox(os.environ.get("MAIL_IMAP_HOST", "imap.gmail.com"), os.environ["MAIL_USER"], os.environ["MAIL_APP_PASSWORD"])
        self.mail = MailAgent(self.brain, self.store, brand, mailbox, self.director.submit, from_addr=os.environ.get("MAIL_USER", ""))
        self.pr = PRAgent(self.brain, self.store, brand, self.http, self.authority, factcheck=self.factcheck)
        self.network = NetworkAgent(self.brain, self.store, brand, self.http, self.authority, self.director.submit, writer=self.writer, factcheck=self.factcheck)
        self.questions = QuestionsAgent(self.brain, self.store, brand, self.http, factcheck=self.factcheck)
        self.director.community, self.director.scout, self.director.analyst = self.community, self.scout, self.analyst
        self.director.mail, self.director.pr, self.director.network, self.director.questions = self.mail, self.pr, self.network, self.questions
        for agent in (self.director, self.writer, self.second_writer, self.strategist, self.safety, self.factcheck, self.image_agent, self.video_agent, self.community, self.scout, self.analyst, self.news_watch, self.mail, self.pr, self.network, self.questions):
            if agent is not None:
                agent.office = self.office
        if self.second_writer is not None:
            self.second_writer.desk = "second"

    # -------------------------------------------------------------------- brain selection
    def _pick_brain(self) -> registry.ModelSpec:
        s = self.settings
        cands = registry.candidates("brain")
        if s.models.brain == "27b":
            return next(m for m in cands if "27B" in m.name)
        if s.models.brain == "flash-next":
            return cands[0]
        chosen = self.brain_choice.chosen_name()
        if chosen:
            for m in cands:
                if m.name == chosen:
                    return m
        return registry.resolve("brain", s.hardware.profile, s.models.overrides)

    def benchmark_brains(self) -> dict[str, Any]:
        """Try each brain candidate on this machine; keep the strongest one that runs well."""
        results = [self.host.benchmark(m) for m in registry.candidates("brain")]
        chosen = None
        for r in results:                       # candidates are ordered strongest first
            if r.get("ok") and (r.get("dry_run") or r.get("tokens_per_s", 0) >= 6):
                chosen = r["model"]
                break
        if chosen is None:
            chosen = results[-1]["model"]
        self.brain_choice.save({"brain": chosen, "results": results, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
        self.models["brain"] = next(m for m in registry.candidates("brain") if m.name == chosen)
        return {"chosen": chosen, "results": results}

    # -------------------------------------------------------------------- events
    def _video_progress(self, msg: str) -> None:
        self.office.step("video", msg)
        self.note(f"[video] {msg}")

    def note(self, msg: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.events.append(f"{stamp} {msg}")
        self.events = self.events[-300:]
        log.info(msg)

    def _model_event(self, e: dict[str, Any]) -> None:
        self.office.model_event(e)
        self.note(f"[models] {e.get('kind')}: {e.get('model')} ({e.get('memory_gb')} GB)" + (f" reason={e.get('reason')}" if e.get("reason") else ""))

    def mode_for(self, platform: str) -> str:
        return self.prefs.get(f"mode:{platform}") or self.settings.mode_for(platform)

    # -------------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        resident = self.host.resident()
        return {
            "dry_run": self.dry_run,
            "profile": self.settings.hardware.profile,
            "director_provider": self.settings.director.provider,
            "brain": self.models["brain"].name,
            "team_mode": self.settings.models.team_mode,
            "models": {task: {"name": m.name, "id": m.id, "runtime": m.runtime, "memory_gb": m.memory_gb, "license": m.license, "precision": m.precision} for task, m in self.models.items()},
            "resident": resident.name if resident else None,
            "resident_gb": self.host.resident_gb(),
            "budget_gb": self.settings.hardware.gpu_budget_gb,
            "platforms": {n: {"label": p.label, "configured": p.configured(), "missing": p.missing_env(), "enabled": self.toggles.platform_enabled(n), "mode": self.mode_for(n), "modes": list(p.publish_modes), "kinds": sorted(p.kinds), "note": p.free_tier_note} for n, p in self.platforms.items()},
            "toggles": self.toggles.all(),
            "queued": len(self.store.list_content(status="queued")),
            "published": len(self.store.list_content(status="published")),
            "events": self.events[-50:],
            "office": self.office.board(),
            "corrections": self.store.count_corrections(),
            "outreach": {"mail_drafts": len(self.store.list_mail_drafts(status="drafted")), "pr": len(self.store.list_pr_opportunities(status="found")) + len(self.store.list_pr_opportunities(status="pitched")), "network_suggested": len(self.store.list_network_sources(status="suggested"))},
            "knowledge_updates": len(self.store.list_knowledge_updates()),
        }
