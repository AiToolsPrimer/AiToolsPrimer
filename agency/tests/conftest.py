from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agency.llm.client import ChatResult, Message  # noqa: E402


class FakeLLM:
    """Deterministic stand-in for the local model: answers by looking at the prompt."""

    def __init__(self):
        self.calls: list[str] = []

    def chat(self, messages: list[Message], **kw: Any) -> ChatResult:
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        text = user if isinstance(user, str) else json.dumps(user)
        self.calls.append(text)
        return ChatResult(text=json.dumps(self._answer(text)))

    def complete_json(self, system: str, user: str, **kw: Any) -> Any:
        self.calls.append(user)
        return self._answer(user)

    def embed(self, texts, model_id):
        return [[float(len(t) % 7), 1.0, 0.5] for t in texts]

    def describe_image(self, b64, question, mime="image/png"):
        return "OK"

    def _answer(self, text: str) -> Any:
        t = text.lower()
        if "propose the most promising content opportunities" in t:
            return {"opportunities": [{"topic": "free PDF editors", "angle": "tested on a real contract", "why_now": "trending", "guide_url": "https://aitoolsprimer.com/pdf", "formats": ["post", "video"], "platforms": ["bluesky", "youtube"], "keywords": ["pdf"], "priority": 1}]}
        if "build the day's production plan" in t:
            return {"items": [
                {"kind": "post", "platforms": ["bluesky", "mastodon"], "topic": "free PDF editors", "angle": "tested", "link": "https://aitoolsprimer.com/pdf", "when_utc": "09:00", "with_image": True},
                {"kind": "video", "platforms": ["youtube"], "topic": "free PDF editors", "angle": "tested", "link": "https://aitoolsprimer.com/pdf", "when_utc": "15:00", "target_seconds": 60},
            ]}
        if "write the script for a youtube video" in t:
            m = re.search(r"about (\d+) seconds", t)
            target = int(m.group(1)) if m else 60
            n = max(3, target // 10)
            return {"title": "Free PDF editors tested", "description": "We tested them. Guide: https://aitoolsprimer.com/pdf", "tags": ["pdf", "tools"], "music_prompt": "calm bed",
                    "scenes": [{"narration": "Scene number " + str(i) + " with a sentence of narration that lasts a few seconds.", "visual_prompt": "desk", "mode": "image_motion", "seconds": 8} for i in range(n)]}
        if "you are reviewing a" in t:
            return {"approved": True, "notes": ""}
        if "write one " in t and " post." in t:
            return {"text": "We tested five free PDF editors on a real contract. The surprises are in the guide: https://aitoolsprimer.com/pdf", "title": "Free PDF editors tested", "tags": ["pdf"], "alt_text": "a desk with a laptop", "image_prompt": "a laptop on a desk"}
        if "write a full article" in t:
            return {"title": "Five free PDF editors, tested", "markdown": "## What we tested\n\nFive tools on one contract.\n\n## Verdict\n\nSee https://aitoolsprimer.com/pdf", "excerpt": "Tested.", "tags": ["pdf"], "cover_prompt": "pdf icons"}
        if "write the caption for a vertical short" in t:
            return {"text": "Five PDF editors, one contract.", "title": "PDF editors tested", "tags": ["pdf"]}
        if "a reader commented" in t:
            if "wrote: spam" in t:
                return {"text": "", "skip": True, "reason": "spam"}
            return {"text": "Thanks! The guide has the full table.", "skip": False, "reason": ""}
        if "revise this" in t:
            return {"text": "revised", "title": "revised", "tags": []}
        if "identify platforms" in t:
            return {"platforms": [{"name": "Lemmy", "url": "https://lemmy.world", "kind": "forum", "free": True, "has_api": True, "fit_score": 0.8, "rationale": "fediverse forum"}]}
        if "prepare a sign-up kit" in t:
            return {"handle": "aitoolsprimer", "display_name": "AI Tools Primer", "short_bio": "Plain-English guides.", "long_bio": "x", "website": "https://aitoolsprimer.com", "avatar_prompt": "monogram", "banner_prompt": "abstract", "first_posts": ["hi"], "steps": ["sign up"]}
        if "here are the last 14 days" in t:
            return {"insights": ["posts with images did better"], "instructions": ["more images"]}
        return {"text": "ok", "approved": True}


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def agency(tmp_path, fake_llm):
    from agency.app import Agency
    from agency.settings import Settings, VideoDefaults

    s = Settings(video=VideoDefaults(width=320, height=180, fps=8, max_seconds=240, shorts_seconds=5))
    s.limits.quiet_hours_utc = (25, 25)  # never
    a = Agency(settings=s, dry_run=True, llm=fake_llm, state_dir=tmp_path / "state", assets_dir=tmp_path / "assets")
    return a
