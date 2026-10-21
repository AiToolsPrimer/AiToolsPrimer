"""The director: plans the day, commissions work from the agents, reviews it,
runs it through safety and policy, publishes or queues it, and learns from the
analyst.  Every outgoing action passes through ``submit`` which is the single
chokepoint between the agency and the outside world.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Callable

from agency.agents.analyst import Analyst
from agency.agents.base import Agent
from agency.agents.community import CommunityManager
from agency.agents.creative import ImageAgent, VideoAgent
from agency.agents.safety import Safety
from agency.agents.scout import Scout
from agency.agents.strategist import Strategist
from agency.agents.writer import Writer
from agency.knowledge.base import KnowledgeBase, check_constraints, fix_for_platform
from agency.memory.store import Store
from agency.platforms.base import Platform, PublishItem
from agency.safety.policy import Action, ActionKind, Decision, PolicyEngine, Verdict
from agency.settings import Limits, Settings, Toggles

POST_PLATFORMS = ("bluesky", "mastodon", "x", "threads", "linkedin", "facebook", "telegram", "reddit", "tumblr")
ARTICLE_PLATFORMS = ("devto", "hashnode", "wordpress", "medium")
VIDEO_PLATFORMS = ("youtube",)
SHORT_PLATFORMS = ("youtube", "tiktok", "instagram")
IMAGE_PLATFORMS = ("instagram", "pinterest")

KIND_TO_ACTION = {"post": ActionKind.PUBLISH_POST, "image": ActionKind.PUBLISH_POST, "article": ActionKind.PUBLISH_ARTICLE, "video": ActionKind.PUBLISH_VIDEO, "short": ActionKind.PUBLISH_VIDEO}


class Director(Agent):
    role = "marketing director"
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
        log: Callable[[str], None] | None = None,
    ):
        super().__init__(llm, store, settings.brand)
        self.kb = kb
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
        if decision.verdict is Verdict.ALLOW and action.kind in {ActionKind.PUBLISH_POST, ActionKind.PUBLISH_ARTICLE, ActionKind.PUBLISH_VIDEO}:
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

    def _publish_now(self, action: Action) -> None:
        cid = action.payload["content_id"]
        row = self.store.get_content(cid)
        if not row:
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
        if edited_body is not None:
            self.store.update_content(cid, body=edited_body)
            row["body"] = edited_body
        verdict = self.safety.check(row.get("body") or row.get("title") or "", facts_supplied=bool(row["meta"].get("facts")))
        if row["kind"] == "reply":
            action = Action(ActionKind.REPLY_OWN, row["platform"], {"text": row["body"], "reply_to": row["meta"].get("reply_to"), "engagement_id": row["meta"].get("engagement_id"), "content_id": cid}, safety_passed=verdict.ok)
            from agency.platforms.base import Comment
            decision = self._force_through(action, {"comment": Comment(row["meta"].get("reply_to", ""), "reader", "", "")})
            if decision.allowed:
                self.store.update_content(cid, status="published", published_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
            return decision
        action = Action(KIND_TO_ACTION[row["kind"]], row["platform"], {"content_id": cid}, safety_passed=verdict.ok)
        return self._force_through(action, {})

    def _force_through(self, action: Action, context: dict[str, Any]) -> Decision:
        """A human click overrides 'approval_required' and the publishing switch, nothing else."""
        decision = self.policy.evaluate(action)
        if decision.verdict is Verdict.QUEUE and decision.reason.startswith(("approval required", "publishing switch")):
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
        data = self.ask_json(
            f"You are reviewing a {kind} for {platform} before publication. Our standards: {self.brand.voice}\n"
            f"Draft: {json.dumps(draft)[:6000]}\n"
            "Check: hook strength, specificity, no unverifiable claims, correct length for the platform, no hype words, reads like a person. "
            'Return JSON: {"approved": true, "notes": "what to change (empty if approved)"}',
            temperature=0.2,
        )
        return "" if data.get("approved") else (data.get("notes") or "tighten and verify")

    def produce_post(self, platform: str, topic: str, angle: str, link: str = "", facts: str = "", with_image: bool = False, when_utc: str | None = None) -> int:
        draft = self.writer.post(platform, topic, angle, link=link, facts=facts, with_image=with_image)
        for _ in range(self.settings.limits.max_revisions):
            notes = self.review("post", draft, platform)
            if not notes:
                break
            draft = self.writer.revise("post", draft, notes)
        assets: list[int] = []
        alt: list[str] = []
        if with_image and self.image_agent and self.toggles.get("make_images"):
            try:
                assets.append(self.image_agent.make(draft.get("image_prompt") or topic, size="square" if platform in ("instagram", "threads") else "landscape", topic=topic))
                alt.append(draft.get("alt_text", topic))
            except Exception as e:  # noqa: BLE001
                self.log(f"image failed for {topic}: {e}")
        kind = "image" if platform in IMAGE_PLATFORMS else "post"
        cid = self.store.add_content(kind, platform, topic=topic, title=draft.get("title", topic), body=draft["text"], assets=assets, status="draft", scheduled_for=when_utc, meta={"link": link, "tags": draft.get("tags", []), "alt_texts": alt, "facts": facts, "angle": angle})
        self._gate(cid)
        return cid

    def produce_article(self, platform: str, topic: str, angle: str, link: str = "", facts: str = "", when_utc: str | None = None) -> int:
        draft = self.writer.article(topic, angle, link=link, facts=facts, platform=platform)
        for _ in range(self.settings.limits.max_revisions):
            notes = self.review("article", {"title": draft.get("title"), "markdown": draft.get("markdown", "")[:5000]}, platform)
            if not notes:
                break
            draft = self.writer.revise("article", draft, notes)
        assets: list[int] = []
        if self.image_agent and self.toggles.get("make_images"):
            try:
                assets.append(self.image_agent.make(draft.get("cover_prompt") or topic, size="og", topic=topic))
            except Exception as e:  # noqa: BLE001
                self.log(f"cover failed for {topic}: {e}")
        cid = self.store.add_content("article", platform, topic=topic, title=draft["title"], body=draft["markdown"], assets=assets, status="draft", scheduled_for=when_utc, meta={"link": link, "tags": draft.get("tags", []), "facts": facts, "extra": {"excerpt": draft.get("excerpt", "")}})
        self._gate(cid)
        return cid

    def produce_video(self, topic: str, angle: str, link: str = "", facts: str = "", target_seconds: int | None = None, platforms: tuple[str, ...] = VIDEO_PLATFORMS, when_utc: str | None = None) -> list[int]:
        if not self.video_agent:
            return []
        out = self.video_agent.produce(topic, angle, target_seconds=target_seconds, link=link, facts=facts, with_shorts=self.toggles.get("make_shorts"))
        ids = []
        for platform in platforms:
            if platform not in self.platforms:
                continue
            cid = self.store.add_content("video", platform, topic=topic, title=out["title"], body=out["description"], assets=[out["asset_id"]], status="draft", scheduled_for=when_utc, meta={"link": link, "tags": out["tags"], "facts": facts, "thumbnail": str(out["thumbnail"]), "seconds": out["seconds"]})
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
        action = Action(KIND_TO_ACTION[row["kind"]], row["platform"], {"content_id": cid}, safety_passed=True)
        return self.submit(action)

    # ------------------------------------------------------------------ cycles
    def daily_cycle(self) -> dict[str, Any]:
        if not self.toggles.get("master_enabled"):
            return {"skipped": "master switch off"}
        self.log("daily cycle: research")
        opportunities = self.strategist.opportunities()
        self.log(f"daily cycle: {len(opportunities)} opportunities; planning")
        plan = self.plan_day(opportunities)
        produced: list[int] = []
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
        return self.analyst.report()

    def scout_cycle(self) -> list[dict[str, Any]]:
        if not self.scout or not self.toggles.get("master_enabled"):
            return []
        found = self.scout.run()
        if self.toggles.get("prepare_signup_kits"):
            for f in found:
                if f.get("id") and float(f.get("fit_score", 0)) >= 0.6:
                    self.scout.prepare_kit(f["id"])
        return found
