"""The director: plans the day, commissions work from the agents, reviews it,
runs it through safety and policy, publishes or queues it, and learns from the
analyst.  Every outgoing action passes through ``submit`` which is the single
chokepoint between the agency and the outside world.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Callable

from agency.agents.analyst import Analyst
from agency.agents.base import Agent
from agency.agents.community import CommunityManager
from agency.agents.creative import ImageAgent, VideoAgent
from agency.agents.factcheck import FactChecker
from agency.agents.safety import Safety
from agency.agents.team import Team
from agency.agents.scout import Scout
from agency.agents.strategist import Strategist
from agency.agents.writer import Writer
from agency.knowledge.base import KnowledgeBase, check_constraints, fix_for_platform
from agency.memory.store import Store
from agency.platforms.base import Platform, PublishItem
from agency.safety.policy import Action, ActionKind, Decision, PolicyEngine, Verdict, BROWSER_KINDS
from agency.settings import Limits, Settings, Toggles

POST_PLATFORMS = ("bluesky", "mastodon", "x", "threads", "linkedin", "facebook", "telegram", "reddit", "tumblr")
ARTICLE_PLATFORMS = ("devto", "hashnode", "wordpress", "medium")
VIDEO_PLATFORMS = ("youtube",)
SHORT_PLATFORMS = ("youtube", "tiktok", "instagram")
IMAGE_PLATFORMS = ("instagram", "pinterest")

KIND_TO_ACTION = {"post": ActionKind.PUBLISH_POST, "image": ActionKind.PUBLISH_POST, "article": ActionKind.PUBLISH_ARTICLE, "video": ActionKind.PUBLISH_VIDEO, "short": ActionKind.PUBLISH_VIDEO, "link": ActionKind.PUBLISH_POST, "answer": ActionKind.PUBLISH_POST}


class Director(Agent):
    role = "marketing director"
    desk = "director"
    temperature = 0.4

    def __init__(
        self,
        *,
        llm,
        store: Store,
        settings: Settings,
        toggles: Toggles,
        policy: PolicyEngine,
        platforms: dict[str, Platform],
        strategist: Strategist,
        writer: Writer,
        safety: Safety,
        image_agent: ImageAgent | None,
        video_agent: VideoAgent | None,
        community: CommunityManager | None = None,
        scout: Scout | None = None,
        analyst: Analyst | None = None,
        kb: KnowledgeBase | None = None,
        factcheck: FactChecker | None = None,
        team: Team | None = None,
        operator=None,
        mode_for: Callable[[str], str] | None = None,
        log: Callable[[str], None] | None = None,
    ):
        super().__init__(llm, store, settings.brand)
        self.kb, self.factcheck, self.team = kb, factcheck, team
        self.operator = operator
        self.mode_for = mode_for or settings.mode_for
        self.settings, self.toggles, self.policy, self.platforms = settings, toggles, policy, platforms
        self.strategist, self.writer, self.safety = strategist, writer, safety
        self.image_agent, self.video_agent = image_agent, video_agent
        self.community, self.scout, self.analyst = community, scout, analyst
        self.log = log or (lambda m: None)

    # ------------------------------------------------------------------ the chokepoint
    def submit(self, action: Action, context: dict[str, Any] | None = None) -> Decision:
        """Policy decides; allowed outbound actions are executed here, queued ones wait for a click."""
        context = context or {}
        decision = self.policy.evaluate(action)
        cid = action.payload.get("content_id")
        self.store.log_action(action.kind.value, action.platform, decision.verdict.value, decision.reason, cid, action.payload)
        if decision.verdict is Verdict.ALLOW and action.kind in {ActionKind.PUBLISH_POST, ActionKind.PUBLISH_ARTICLE, ActionKind.PUBLISH_VIDEO, ActionKind.PREPARE_MANUAL, ActionKind.BROWSER_PUBLISH}:
            self._publish_now(action)
        elif decision.verdict is Verdict.ALLOW and action.kind is ActionKind.REPLY_OWN:
            self._reply_now(action, context)
        elif decision.verdict is Verdict.QUEUE and cid and action.kind is not ActionKind.REPLY_OWN:
            self.store.update_content(cid, status="queued", meta={**(self.store.get_content(cid) or {}).get("meta", {}), "hold_reason": decision.reason})
        elif decision.verdict is Verdict.QUEUE and action.kind is ActionKind.REPLY_OWN:
            author = context["comment"].author if context.get("comment") else "reader"
            self.store.add_content("reply", action.platform, title=f"reply to {author}", body=action.payload["text"], status="queued", meta={"reply_to": action.payload["reply_to"], "engagement_id": action.payload.get("engagement_id"), "hold_reason": decision.reason})
        elif decision.verdict is Verdict.DENY and cid and action.kind is not ActionKind.REPLY_OWN:
            self.store.update_content(cid, status="rejected", meta={**(self.store.get_content(cid) or {}).get("meta", {}), "reject_reason": decision.reason})
        return decision

    def _action_for(self, row: dict[str, Any], safety_passed: bool | None = True, human_click: bool = False) -> Action:
        """The outbound action for a content row, by the platform's publishing mode."""
        mode = self.mode_for(row["platform"])
        payload: dict[str, Any] = {"content_id": row["id"]}
        if mode == "browser":
            return Action(ActionKind.BROWSER_PUBLISH, row["platform"], {**payload, "human_click": human_click}, safety_passed=safety_passed)
        if mode in ("intent", "manual"):
            return Action(ActionKind.PREPARE_MANUAL, row["platform"], payload, safety_passed=safety_passed)
        if mode == "off":
            return Action(ActionKind.PUBLISH_POST, row["platform"], payload, safety_passed=safety_passed)
        return Action(KIND_TO_ACTION.get(row["kind"], ActionKind.PUBLISH_POST), row["platform"], payload, safety_passed=safety_passed)

    def _prepare_manual(self, cid: int) -> None:
        row = self.store.get_content(cid)
        if not row:
            return
        p = self.platforms.get(row["platform"])
        meta = dict(row.get("meta", {}))
        mode = self.mode_for(row["platform"])
        item = PublishItem(kind=row["kind"], text=row.get("body") or "", title=row.get("title") or "", link=meta.get("link", ""))
        if mode == "intent" and p is not None and hasattr(p, "intent_url"):
            meta["intent_url"] = p.intent_url(item)
        meta["manual_mode"] = mode
        self.store.update_content(cid, status="manual", meta=meta)
        self.log(f"prepared #{cid} for {row['platform']} ({mode})")

    def _prepare_browser(self, cid: int) -> None:
        row = self.store.get_content(cid)
        if not row or self.operator is None:
            return
        meta = dict(row.get("meta", {}))
        media = [self.store.get_asset(a)["path"] for a in row.get("assets", []) if self.store.get_asset(a)]
        variables = {"publication": self.settings.platforms.get(row["platform"]).extra.get("publication", "") if self.settings.platforms.get(row["platform"]) else "", "blog_id": self.settings.platforms.get(row["platform"]).extra.get("blog_id", "") if self.settings.platforms.get(row["platform"]) else ""}
        payload = {"content_id": cid, "text": row.get("body") or "", "title": row.get("title") or "", "body": row.get("body") or "", "link": meta.get("link", ""), "media": media, "variables": variables}
        if self.office is not None:
            self.office.begin("operator", f"filling {row['kind']} #{cid} on {row['platform']}")
        task = self.operator.prepare(row["platform"], "publish", payload)
        if self.office is not None:
            self.office.end("operator", f"task {task.id}: {task.status}", ok=task.status != "failed")
        meta.update({"browser_task": task.id, "browser_status": task.status, "screenshot": task.screenshot, "browser_error": task.error})
        self.store.update_content(cid, status="ready_to_click" if task.status in ("ready", "needs_your_click") else "failed", meta=meta)

    def browser_publish(self, task_id: int) -> Decision:
        """The human clicked Publish in the dashboard: the operator clicks it in the browser."""
        if self.operator is None:
            return Decision(Verdict.DENY, "no browser operator")
        task = self.operator.task(task_id)
        if not task:
            return Decision(Verdict.DENY, "no such browser task")
        cid = task.payload.get("content_id")
        row = self.store.get_content(cid) if cid else None
        platform = task.platform
        action = Action(ActionKind.BROWSER_PUBLISH if task.kind == "publish" else ActionKind.BROWSER_COMMENT, platform, {"content_id": cid, "human_click": True, "task": task_id}, safety_passed=True)
        decision = self.policy.evaluate(action)
        self.store.log_action(action.kind.value, platform, decision.verdict.value, decision.reason, cid, action.payload)
        if not decision.allowed:
            return decision
        if self.office is not None:
            self.office.begin("operator", f"clicking Publish on {platform} (task {task_id})")
        task = self.operator.publish(task_id)
        if self.office is not None:
            self.office.end("operator", f"task {task_id}: {task.status}", ok=task.status != "failed")
        if row:
            meta = {**row["meta"], "browser_status": task.status, "screenshot": task.screenshot, "browser_error": task.error}
            if task.status == "published":
                self.store.update_content(cid, status="published", published_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), remote_url=task.url, remote_id=f"browser-{task_id}", meta=meta)
                self.log(f"published #{cid} on {platform} via the browser: {task.url}")
            elif task.status == "needs_your_click":
                self.store.update_content(cid, status="ready_to_click", meta=meta)
            else:
                self.store.update_content(cid, status="failed", meta=meta)
        return Decision(Verdict.ALLOW, task.status)

    def browser_cancel(self, task_id: int) -> None:
        if self.operator is None:
            return
        task = self.operator.task(task_id)
        if task:
            self.operator.cancel(task_id)
            cid = task.payload.get("content_id")
            if cid and self.store.get_content(cid):
                self.store.update_content(cid, status="rejected", meta={**self.store.get_content(cid)["meta"], "reject_reason": "browser task cancelled"})

    def _publish_now(self, action: Action) -> None:
        cid = action.payload["content_id"]
        row = self.store.get_content(cid)
        if not row:
            return
        if action.kind is ActionKind.PREPARE_MANUAL:
            self._prepare_manual(cid)
            return
        if action.kind in BROWSER_KINDS:
            self._prepare_browser(cid)
            return
        p = self.platforms.get(action.platform)
        if not p:
            self.store.update_content(cid, status="failed", meta={**row["meta"], "error": "unknown platform"})
            return
        media = [Path(self.store.get_asset(a)["path"]) for a in row.get("assets", []) if self.store.get_asset(a)]
        meta = row.get("meta", {})
        thumb = Path(meta["thumbnail"]) if meta.get("thumbnail") else None
        item = PublishItem(kind=row["kind"], text=row.get("body") or "", title=row.get("title") or "", link=meta.get("link", ""), tags=meta.get("tags", []), media=media, alt_texts=meta.get("alt_texts", []), thumbnail=thumb, extra=meta.get("extra", {}))
        res = p.publish(item)
        if res.ok:
            self.store.update_content(cid, status="published", published_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), remote_id=res.remote_id, remote_url=res.url, meta={**meta, "dry_run": res.dry_run})
            self.log(f"published {row['kind']} #{cid} on {p.name}: {res.url or res.remote_id}")
        else:
            self.store.update_content(cid, status="failed", meta={**meta, "error": res.error})
            self.log(f"FAILED {row['kind']} #{cid} on {p.name}: {res.error}")

    def _reply_now(self, action: Action, context: dict[str, Any]) -> None:
        p = self.platforms.get(action.platform)
        comment = context.get("comment")
        if not p or not comment:
            return
        res = p.reply(comment, action.payload["text"])
        if res.ok:
            self.store.add_content("reply", p.name, title=f"reply to {comment.author}", body=action.payload["text"], status="published", meta={"reply_to": comment.remote_id, "remote_id": res.remote_id, "dry_run": res.dry_run})
            if action.payload.get("engagement_id"):
                self.store.mark_replied(action.payload["engagement_id"])

    # ------------------------------------------------------------------ approvals from the panel
    def approve(self, cid: int, edited_body: str | None = None) -> Decision:
        row = self.store.get_content(cid)
        if not row:
            return Decision(Verdict.DENY, "no such content")
        if edited_body is not None and edited_body.strip() != (row.get("body") or "").strip():
            self.store.add_correction(cid, row["platform"], row["kind"], row.get("body") or "", edited_body)
            self.store.update_content(cid, body=edited_body)
            row["body"] = edited_body
        verdict = self.safety.check(row.get("body") or row.get("title") or "", facts_supplied=bool(row["meta"].get("facts")))
        if row["kind"] == "comment":
            return self._approve_external_comment(row, verdict.ok)
        if row["kind"] == "reply":
            action = Action(ActionKind.REPLY_OWN, row["platform"], {"text": row["body"], "reply_to": row["meta"].get("reply_to"), "engagement_id": row["meta"].get("engagement_id"), "content_id": cid}, safety_passed=verdict.ok)
            from agency.platforms.base import Comment
            decision = self._force_through(action, {"comment": Comment(row["meta"].get("reply_to", ""), "reader", "", "")})
            if decision.allowed:
                self.store.update_content(cid, status="published", published_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
            return decision
        return self._force_through(self._action_for(row, safety_passed=verdict.ok), {})

    def _approve_external_comment(self, row: dict[str, Any], safety_ok: bool) -> Decision:
        """A comment under someone else's post: your approval is the click. API where the platform has one
        (Bluesky, Mastodon reply), otherwise the browser operator fills it and you click Reply."""
        cid, platform, meta = row["id"], row["platform"], row["meta"]
        p = self.platforms.get(platform)
        action = Action(ActionKind.EXTERNAL_COMMENT, platform, {"content_id": cid, "human_click": True}, safety_passed=safety_ok)
        decision = self.policy.evaluate(action)
        self.store.log_action(action.kind.value, platform, decision.verdict.value, decision.reason, cid, action.payload)
        if not decision.allowed:
            return decision
        from agency.platforms.base import Comment
        if p is not None and self.mode_for(platform) == "api" and meta.get("target_remote_id"):
            res = p.reply(Comment(meta["target_remote_id"], "author", "", ""), row["body"])
            if res.ok:
                self.store.update_content(cid, status="published", published_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), remote_id=res.remote_id, remote_url=res.url, meta={**meta, "dry_run": res.dry_run})
                if meta.get("network_item"):
                    self.store.mark_network_item(meta["network_item"], "commented")
                return Decision(Verdict.ALLOW, "comment posted")
            self.store.update_content(cid, status="failed", meta={**meta, "error": res.error})
            return Decision(Verdict.DENY, res.error)
        if self.operator is not None:
            task = self.operator.prepare(platform if platform in self.operator.recipes else "x", "comment", {"content_id": cid, "text": row["body"], "post_url": meta.get("target_url", "")})
            self.store.update_content(cid, status="ready_to_click" if task.status in ("ready", "needs_your_click") else "failed", meta={**meta, "browser_task": task.id, "browser_status": task.status, "screenshot": task.screenshot})
            return Decision(Verdict.ALLOW, f"browser task {task.id}: {task.status}")
        self.store.update_content(cid, status="manual", meta={**meta, "manual_mode": "manual"})
        return Decision(Verdict.ALLOW, "prepared for manual posting")

    def _force_through(self, action: Action, context: dict[str, Any]) -> Decision:
        """A human click overrides 'approval_required' and the publishing switch, nothing else."""
        decision = self.policy.evaluate(action)
        if decision.verdict is Verdict.QUEUE and decision.reason.startswith(("approval required", "publishing switch", "browser action")):
            decision = Decision(Verdict.ALLOW, "approved by human")
        self.store.log_action(action.kind.value, action.platform, decision.verdict.value, decision.reason, action.payload.get("content_id"), action.payload)
        if decision.allowed:
            if action.kind is ActionKind.REPLY_OWN:
                self._reply_now(action, context)
            else:
                self._publish_now(action)
        return decision

    def reject(self, cid: int, reason: str = "rejected by human") -> None:
        self.store.update_content(cid, status="rejected", meta={**(self.store.get_content(cid) or {}).get("meta", {}), "reject_reason": reason})

    # ------------------------------------------------------------------ planning
    def plan_day(self, opportunities: list[dict[str, Any]]) -> dict[str, Any]:
        t = self.toggles.all()
        active = [n for n, p in self.platforms.items() if p.configured() or self.settings.dry_run]
        enabled = [n for n in active if self.toggles.platform_enabled(n)]
        caps = {
            "post": t["write_posts"], "article": t["write_articles"], "video": t["make_videos"] and self.video_agent is not None,
            "short": t["make_shorts"] and self.video_agent is not None, "image": t["make_images"] and self.image_agent is not None,
        }
        recent_counts = {k: self.store.count_recent_actions("*", k, dt.timedelta(days=7)) for k in ("video", "article")}
        plan = self.ask_json(
            f"Today is {dt.date.today().isoformat()}. Build the day's production plan.\n"
            f"Opportunities from the strategist: {opportunities}\n"
            f"Platforms available: {enabled}\nFormats allowed today: {[k for k, v in caps.items() if v]}\n"
            f"Weekly budgets: {self.settings.limits.videos_per_week} videos, {self.settings.limits.articles_per_week} articles; "
            f"max {self.settings.limits.posts_per_platform_per_day} posts per platform per day. Produced this week so far: {recent_counts}.\n"
            "Rules: one video at most per day (it is the most expensive), every video gets shorts; every article gets 2-3 posts announcing it on social platforms; "
            "spread posts across the day in UTC; prefer the platforms where our audience actually is; keep the plan small and excellent rather than large.\n"
            'Return JSON: {"items": [{"kind": "post|article|video|image", "platforms": ["..."], "topic": "...", "angle": "...", "link": "...", "when_utc": "HH:MM", "with_image": true, "target_seconds": 180}]}'
        )
        items = [i for i in plan.get("items", []) if i.get("kind") in caps and caps[i["kind"]] and i.get("platforms")] if isinstance(plan, dict) else []
        return {"items": items}

    # ------------------------------------------------------------------ production
    def review(self, kind: str, draft: dict[str, Any], platform: str) -> str:
        """Editor pass. Returns '' when the draft is good, otherwise notes for the writer."""
        with self.report(f"reviewing a {kind} for {platform}"):
            return self._review(kind, draft, platform)

    def _review(self, kind: str, draft: dict[str, Any], platform: str) -> str:
        data = self.ask_json(
            f"You are reviewing a {kind} for {platform} before publication. Our standards: {self.brand.voice}\n"
            f"Draft: {json.dumps(draft)[:6000]}\n"
            "Check: hook strength, specificity, no unverifiable claims, correct length for the platform, no hype words, reads like a person. "
            'Return JSON: {"approved": true, "notes": "what to change (empty if approved)"}',
            temperature=0.2,
        )
        return "" if data.get("approved") else (data.get("notes") or "tighten and verify")

    def _facts(self, link: str, facts: str) -> tuple[list[dict[str, Any]], str]:
        """Verified facts for a guide URL (fetched and cached by the fact checker)."""
        if facts:
            return [], facts
        if self.factcheck and link:
            fl = self.factcheck.facts_for(link)
            return fl, FactChecker.facts_text(fl)
        return [], ""

    def _compose(self, kind: str, platform: str, brief: str, make):
        if self.team is not None:
            return self.team.compose(kind, platform, brief, make)
        return make(self.writer)

    def _verify(self, cid_hint: str, text: str, facts_list: list[dict[str, Any]], kind: str) -> tuple[str, dict[str, Any] | None, str]:
        """Returns (clean_text, report, reject_reason)."""
        if not self.factcheck:
            return text, None, ""
        r = self.factcheck.verify(text, facts_list, kind=kind)
        if not r.language_ok:
            return "", r.report(), "not English"
        if not r.text.strip():
            return "", r.report(), "nothing survived the fact check: " + "; ".join(x["reason"] for x in r.removed[:3])
        if r.removed:
            self.log(f"fact check on {cid_hint}: removed {len(r.removed)} sentence(s)")
        return r.text, r.report(), ""

    def produce_post(self, platform: str, topic: str, angle: str, link: str = "", facts: str = "", with_image: bool = False, when_utc: str | None = None) -> int:
        facts_list, facts = self._facts(link, facts)
        brief = f"topic: {topic}; angle: {angle}; link: {link}"
        draft = self._compose("post", platform, brief, lambda w: w.post(platform, topic, angle, link=link, facts=facts, with_image=with_image))
        for _ in range(self.settings.limits.max_revisions):
            notes = self.review("post", draft, platform)
            if not notes:
                break
            draft = self.writer.revise("post", draft, notes)
        clean, report, reject = self._verify(f"{platform} post '{topic[:40]}'", draft.get("text", ""), facts_list, "post")
        if reject:
            cid = self.store.add_content("post", platform, topic=topic, title=draft.get("title", topic), body=draft.get("text", ""), status="rejected", meta={"link": link, "reject_reason": f"fact check: {reject}", "factcheck": report})
            return cid
        draft["text"] = clean
        assets: list[int] = []
        alt: list[str] = []
        if with_image and self.image_agent and self.toggles.get("make_images"):
            try:
                assets.append(self.image_agent.make(draft.get("image_prompt") or topic, size="square" if platform in ("instagram", "threads") else "landscape", topic=topic))
                alt.append(draft.get("alt_text", topic))
            except Exception as e:  # noqa: BLE001
                self.log(f"image failed for {topic}: {e}")
        kind = "image" if platform in IMAGE_PLATFORMS else "post"
        cid = self.store.add_content(kind, platform, topic=topic, title=draft.get("title", topic), body=draft["text"], assets=assets, status="draft", scheduled_for=when_utc, meta={"link": link, "tags": draft.get("tags", []), "alt_texts": alt, "facts": facts, "angle": angle, "factcheck": report, "team": draft.get("_team")})
        self._gate(cid)
        return cid

    def produce_article(self, platform: str, topic: str, angle: str, link: str = "", facts: str = "", when_utc: str | None = None) -> int:
        facts_list, facts = self._facts(link, facts)
        draft = self._compose("article", platform, f"topic: {topic}; angle: {angle}; link: {link}", lambda w: w.article(topic, angle, link=link, facts=facts, platform=platform))
        for _ in range(self.settings.limits.max_revisions):
            notes = self.review("article", {"title": draft.get("title"), "markdown": draft.get("markdown", "")[:5000]}, platform)
            if not notes:
                break
            draft = self.writer.revise("article", draft, notes)
        clean, report, reject = self._verify(f"{platform} article '{topic[:40]}'", draft.get("markdown", ""), facts_list, "article")
        if reject:
            return self.store.add_content("article", platform, topic=topic, title=draft.get("title", topic), body=draft.get("markdown", ""), status="rejected", meta={"link": link, "reject_reason": f"fact check: {reject}", "factcheck": report})
        draft["markdown"] = clean
        assets: list[int] = []
        if self.image_agent and self.toggles.get("make_images"):
            try:
                assets.append(self.image_agent.make(draft.get("cover_prompt") or topic, size="og", topic=topic))
            except Exception as e:  # noqa: BLE001
                self.log(f"cover failed for {topic}: {e}")
        cid = self.store.add_content("article", platform, topic=topic, title=draft["title"], body=draft["markdown"], assets=assets, status="draft", scheduled_for=when_utc, meta={"link": link, "tags": draft.get("tags", []), "facts": facts, "extra": {"excerpt": draft.get("excerpt", "")}, "factcheck": report, "team": draft.get("_team")})
        self._gate(cid)
        self._podcast_episode(cid, draft["title"], draft["markdown"], link, draft.get("excerpt", ""))
        return cid

    def _podcast_episode(self, article_cid: int, title: str, markdown: str, link: str, summary: str) -> int | None:
        podcast = getattr(self, "podcast", None)
        if podcast is None or not self.toggles.get("make_podcast") or self.video_agent is None:
            return None
        try:
            text = _markdown_to_speech(markdown)
            intro = f"This episode is read by an AI voice. The facts come from the guides on {self.brand.site}. "
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or f"episode-{article_cid}"
            wav = self.video_agent.assembler.tts.speak(intro + text, podcast.out_dir / f"{slug}.m4a")
            mp3 = podcast.add_episode(slug, title, summary or title, wav, link or self.brand.site)
            aid = self.store.add_asset("audio", mp3, prompt=title, model=self.video_agent.assembler.tts.spec.name, meta={"episode": slug})
            cid = self.store.add_content("podcast", "podcast", topic=title, title=title, body=summary or title, assets=[aid], status="manual", meta={"link": link, "parent_article": article_cid, "manual_mode": "feed", "feed": str(podcast.out_dir / "feed.xml")})
            self.log(f"podcast episode ready: {mp3.name}")
            return cid
        except Exception as e:  # noqa: BLE001
            self.log(f"podcast episode failed: {e}")
            return None

    def produce_video(self, topic: str, angle: str, link: str = "", facts: str = "", target_seconds: int | None = None, platforms: tuple[str, ...] = VIDEO_PLATFORMS, when_utc: str | None = None) -> list[int]:
        if not self.video_agent:
            return []
        facts_list, facts = self._facts(link, facts)
        verifier = (lambda scenes: self.factcheck.verify_scenes(scenes, facts_list)) if self.factcheck else None
        out = self.video_agent.produce(topic, angle, target_seconds=target_seconds, link=link, facts=facts, with_shorts=self.toggles.get("make_shorts"), verifier=verifier)
        if not out:
            self.log(f"video '{topic[:40]}' dropped: nothing survived the fact check")
            return []
        ids = []
        for platform in platforms:
            if platform not in self.platforms:
                continue
            cid = self.store.add_content("video", platform, topic=topic, title=out["title"], body=out["description"], assets=[out["asset_id"]], status="draft", scheduled_for=when_utc, meta={"link": link, "tags": out["tags"], "facts": facts, "thumbnail": str(out["thumbnail"]), "seconds": out["seconds"], "factcheck": out.get("factcheck")})
            self._gate(cid)
            ids.append(cid)
        for n, sid in enumerate(out.get("short_asset_ids", [])):
            for platform in SHORT_PLATFORMS:
                if platform not in self.platforms or not self.toggles.platform_enabled(platform):
                    continue
                cap = self.writer.captions_for_short(out["title"], platform)
                cid = self.store.add_content("short", platform, topic=topic, title=cap.get("title", out["title"]), body=cap.get("text", ""), assets=[sid], status="draft", meta={"link": link, "tags": cap.get("tags", []), "facts": facts, "parent_video": out["asset_id"], "short_index": n})
                self._gate(cid)
                ids.append(cid)
        return ids

    def _gate(self, cid: int) -> Decision:
        row = self.store.get_content(cid)
        if self.kb is not None and row["kind"] in ("post", "image", "short", "reply"):
            c = self.kb.constraints(row["platform"])
            fixed, first_comment = fix_for_platform(row.get("body") or "", c, link=row["meta"].get("link", ""))
            problems = check_constraints(fixed, row["platform"], c, title=row.get("title") or "", is_ai_generated_media=bool(row.get("assets")))
            meta = {**row["meta"], "first_comment": first_comment} if first_comment else dict(row["meta"])
            if problems:
                meta["constraint_notes"] = problems
            if fixed != row.get("body"):
                self.store.update_content(cid, body=fixed, meta=meta)
                row = self.store.get_content(cid)
            elif meta != row["meta"]:
                self.store.update_content(cid, meta=meta)
                row = self.store.get_content(cid)
            if problems and any("label" in p for p in problems):
                self.store.update_content(cid, status="rejected", meta={**row["meta"], "reject_reason": "; ".join(problems)})
                return Decision(Verdict.DENY, "; ".join(problems))
        verdict = self.safety.check(row.get("body") or row.get("title") or "", facts_supplied=bool(row["meta"].get("facts")))
        if not verdict.ok:
            self.store.update_content(cid, status="rejected", meta={**row["meta"], "reject_reason": f"safety: {verdict.reason}"})
            self.log(f"safety rejected #{cid}: {verdict.reason}")
            return Decision(Verdict.DENY, verdict.reason)
        if self.mode_for(row["platform"]) == "off":
            self.store.update_content(cid, status="rejected", meta={**row["meta"], "reject_reason": f"{row['platform']} is switched off"})
            return Decision(Verdict.DENY, "platform mode is off")
        return self.submit(self._action_for(row))

    # ------------------------------------------------------------------ cycles
    def _phase(self, name: str) -> None:
        if self.office is not None:
            self.office.set_phase(name)
        self.log(f"phase: {name}")

    def daily_cycle(self) -> dict[str, Any]:
        if not self.toggles.get("master_enabled"):
            return {"skipped": "master switch off"}
        self._phase("research")
        opportunities = self.strategist.opportunities()
        self._phase(f"planning ({len(opportunities)} opportunities)")
        with self.report("planning the day"):
            plan = self.plan_day(opportunities)
        produced: list[int] = []
        self._phase(f"production ({len(plan['items'])} items)")
        for item in plan["items"]:
            kind, topic, angle = item["kind"], item.get("topic", ""), item.get("angle", "")
            link, when = item.get("link", "") or "", item.get("when_utc")
            try:
                if kind == "video":
                    produced += self.produce_video(topic, angle, link=link, target_seconds=item.get("target_seconds"), when_utc=when)
                elif kind == "article":
                    for p in item["platforms"]:
                        if p in ARTICLE_PLATFORMS:
                            produced.append(self.produce_article(p, topic, angle, link=link, when_utc=when))
                else:
                    for p in item["platforms"]:
                        if p in POST_PLATFORMS or p in IMAGE_PLATFORMS:
                            produced.append(self.produce_post(p, topic, angle, link=link, with_image=bool(item.get("with_image") or p in IMAGE_PLATFORMS), when_utc=when))
            except Exception as e:  # noqa: BLE001
                self.log(f"item failed ({kind} {topic}): {e}")
        self.store.add_note("director", f"Day plan: {json.dumps(plan)[:1500]}")
        self._phase("done")
        return {"opportunities": opportunities, "plan": plan, "content_ids": produced}

    def community_cycle(self) -> dict[str, Any]:
        if not self.community or not self.toggles.get("master_enabled"):
            return {}
        new = self.community.collect()
        responses = self.community.respond() if self.toggles.get("auto_reply_own_posts") else []
        return {"new_comments": new, "responses": responses}

    def analyst_cycle(self) -> str:
        if not self.analyst or not self.toggles.get("master_enabled"):
            return ""
        self.analyst.collect()
        return self.analyst.lessons()

    def network_cycle(self) -> dict[str, Any]:
        agent = getattr(self, "network", None)
        if agent is None or not self.toggles.get("master_enabled"):
            return {}
        self._phase("network")
        found = agent.discover() if not self.store.list_network_sources() else []
        watched = agent.watch()
        drafts = agent.draft_comments() if self.toggles.get("network_watch") else []
        return {"discovered": len(found), **watched, "comment_drafts": len(drafts)}

    def mail_cycle(self) -> dict[str, Any]:
        agent = getattr(self, "mail", None)
        if agent is None or not self.toggles.get("master_enabled"):
            return {}
        self._phase("mail")
        out = agent.run()
        if self.toggles.get("read_mail"):
            out["saved_to_gmail_drafts"] = agent.save_drafts_to_gmail()
        return out

    def pr_cycle(self) -> dict[str, Any]:
        agent = getattr(self, "pr", None)
        if agent is None or not self.toggles.get("master_enabled"):
            return {}
        self._phase("pr")
        agent.authority.refresh()
        mentions = agent.unlinked_mentions()
        pages = [s["url"] for s in self.store.list_network_sources(status="following") if s["kind"] == "site"][:10]
        guides = [{"url": p["url"], "title": p["title"]} for p in self.strategist.site_inventory()]
        broken = agent.broken_links(pages, guides) if pages else []
        pitched = 0
        for opp in self.store.list_pr_opportunities(status="found")[:10]:
            if float(opp.get("fit") or 0) >= 0.6 and agent.write_pitch(opp["id"]):
                pitched += 1
        return {"unlinked_mentions": len(mentions), "broken_links": len(broken), "pitches": pitched}

    def questions_cycle(self) -> list[dict[str, Any]]:
        agent = getattr(self, "questions", None)
        if agent is None or not self.toggles.get("master_enabled"):
            return []
        self._phase("community questions")
        guides = [{"url": p["url"], "title": p["title"]} for p in self.strategist.site_inventory()]
        return agent.run(guides)

    def scout_cycle(self) -> list[dict[str, Any]]:
        if not self.scout or not self.toggles.get("master_enabled"):
            return []
        found = self.scout.run()
        if self.toggles.get("prepare_signup_kits"):
            for f in found:
                if f.get("id") and float(f.get("fit_score", 0)) >= 0.6:
                    self.scout.prepare_kit(f["id"])
        return found


def _markdown_to_speech(md: str) -> str:
    """Markdown → plain narration: drop links' URLs, code, images, emphasis marks and headings' hashes."""
    text = re.sub(r"```.*?```", " ", md, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"[*_`>]+", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()
