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
                    "scenes": [{"narration": "Scene " + ["one", "two", "three", "four"][i % 4] + " says that we tested five free PDF editors on a real contract and two added a watermark.", "visual_prompt": "desk", "mode": "image_motion", "seconds": 8} for i in range(n)]}
        if "extract every atomic fact" in t:
            return {"facts": [{"id": "F1", "fact": "We tested five free PDF editors on a real contract", "quote": "we tested five free PDF editors on a real contract", "kind": "method"},
                              {"id": "F2", "fact": "Two of the five editors added a watermark after the trial", "quote": "two added a watermark", "kind": "verdict"},
                              {"id": "F3", "fact": "Checked on 15 October 2026", "quote": "checked 15 October 2026", "kind": "date"}]}
        if "for each sentence decide" in t or "there are no verified facts" in t:
            verdicts = []
            for m in re.finditer(r"s(\d+): (.+)", t):
                sent = m.group(2)
                if "unsupported" in sent or "guaranteed" in sent or "cures" in sent:
                    verdicts.append({"id": f"S{m.group(1)}", "verdict": "unsupported", "why": "not in the guide"})
                elif sent.strip().endswith("?") or "guide" in sent:
                    verdicts.append({"id": f"S{m.group(1)}", "verdict": "no_claim", "why": ""})
                else:
                    verdicts.append({"id": f"S{m.group(1)}", "verdict": "supported" if "facts from the source guide" in t else "no_claim", "facts": ["F1"], "why": ""})
            return {"verdicts": verdicts}
        if "choose the strongest draft" in t:
            return {"chosen": 0, "why": "first"}
        if "classify this email" in t:
            if "sponsored" in t:
                return {"category": "spam", "summary": "sponsored placement offer", "urgent": False, "reply": ""}
            return {"category": "reader", "summary": "reader asks about PDF editors", "urgent": False, "reply": "Thanks for writing. The guide has the full table of what we tested."}
        if "digest of journalist requests" in t:
            return {"requests": [{"outlet": "Reuters", "topic": "free PDF editors", "query": "Looking for experts who tested free PDF editors", "email": "reporter@reuters.example.com", "deadline": "Oct 25", "fit": 0.9, "guide_hint": "https://aitoolsprimer.com/pdf"},
                                 {"outlet": "Fake", "topic": "x", "query": "guessing address", "email": "nobody@nowhere.example.com", "deadline": "", "fit": 0.2, "guide_hint": ""}]}
        if "write a pitch email" in t:
            return {"subject": "Tested five free PDF editors on a real contract", "body": "Hello. We tested five free PDF editors on a real contract. Two added a watermark after the trial. Happy to share the table. Best, the editor", "to": "reporter@reuters.example.com"}
        if "links to these dead urls" in t:
            return {"matches": [{"dead": "https://dead.example.com/old-pdf-guide", "guide_url": "https://aitoolsprimer.com/pdf", "why": "same subject"}]}
        if "which of these sites and accounts are genuinely relevant" in t:
            return {"keep": [{"url": "https://niche-blog.example.com/", "relevance": 0.8, "why": "writes about AI tools"}, {"url": "https://bsky.app/profile/toolsnerd.bsky.social", "relevance": 0.9, "why": "reviews tools"}]}
        if "a source we follow published" in t:
            return {"text": "We tested five free PDF editors on a real contract. Which one kept the metadata for you?", "skip": False, "guide_url": "https://aitoolsprimer.com/pdf"}
        if "questions found online" in t:
            return {"matches": [{"url": "https://www.reddit.com/r/pdf/comments/1/free_pdf_editor", "guide_url": "https://aitoolsprimer.com/pdf", "fit": 0.9, "answer_points": ["two added a watermark"]},
                                {"url": "https://news.ycombinator.com/item?id=41", "guide_url": "https://aitoolsprimer.com/pdf", "fit": 0.8, "answer_points": ["we tested five free PDF editors"]}]}
        if "draft an answer to this" in t:
            return {"text": "We tested five free PDF editors on a real contract. Two added a watermark after the trial. I run the site that published the test."}
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


GUIDE_HTML = """<html><head><title>Five free PDF editors tested</title></head><body><nav>menu</nav>
<h1>Five free PDF editors tested on a real contract</h1><p>We tested five free PDF editors on a real contract. Two added a watermark after the trial.</p>
<p>Checked 15 October 2026.</p><footer>footer</footer></body></html>"""


DDG_HTML = """<html><body>
<a class="result__a" href="https://html.duckduckgo.com/l/?uddg=https%3A%2F%2Fbigtech.example.com%2Freview">Big Tech Review: AI Tools Primer tested</a>
<a class="result__a" href="https://lemmy.world/about">Lemmy</a>
<a class="result__a" href="https://www.quora.com/Which-free-PDF-editor-is-safe">Which free PDF editor is safe? - Quora</a>
<a class="result__a" href="https://niche-blog.example.com/">Niche blog about AI tools</a>
</body></html>"""
BIGTECH_HTML = """<html><body><h1>Review</h1><p>We like AI Tools Primer for its plain-English tests.</p>
<a href="https://dead.example.com/old-pdf-guide">old guide</a><a href="https://fine.example.com/ok">ok</a></body></html>"""
NICHE_HTML = """<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head><body>blog</body></html>"""
NICHE_FEED = """<?xml version="1.0"?><rss><channel><item><title>New post about PDF tools</title><link>https://niche-blog.example.com/pdf-tools</link><pubDate>Mon, 20 Oct 2026 10:00:00 +0000</pubDate></item></channel></rss>"""


def mock_transport():
    import json

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "aitoolsprimer.com":
            if path == "/sitemap.xml":
                return httpx.Response(200, text="<urlset><url><loc>https://aitoolsprimer.com/pdf</loc></url></urlset>")
            return httpx.Response(200, text=GUIDE_HTML, headers={"content-type": "text/html"})
        if host == "html.duckduckgo.com":
            return httpx.Response(200, text=DDG_HTML, headers={"content-type": "text/html"})
        if host == "bigtech.example.com":
            return httpx.Response(200, text=BIGTECH_HTML, headers={"content-type": "text/html"})
        if host == "dead.example.com":
            return httpx.Response(404, text="gone")
        if host == "fine.example.com":
            return httpx.Response(200, text="ok")
        if host == "niche-blog.example.com":
            if path == "/feed.xml":
                return httpx.Response(200, text=NICHE_FEED)
            return httpx.Response(200, text=NICHE_HTML, headers={"content-type": "text/html"})
        if host == "public.api.bsky.app":
            if "searchActors" in path:
                return httpx.Response(200, json={"actors": [{"handle": "toolsnerd.bsky.social", "displayName": "Tools Nerd", "description": "AI tools reviews"}]})
            if "getAuthorFeed" in path:
                return httpx.Response(200, json={"feed": [{"post": {"uri": "at://did:plc:1/app.bsky.feed.post/abc", "cid": "cid1", "indexedAt": "2026-10-20T10:00:00Z", "record": {"text": "Which PDF editor keeps metadata?"}}}]})
        if host == "www.reddit.com" and path == "/search.json":
            return httpx.Response(200, json={"data": {"children": [{"data": {"permalink": "/r/pdf/comments/1/free_pdf_editor", "title": "Best free PDF editor for a contract?", "selftext": "Need one that does not watermark", "subreddit": "pdf"}}]}})
        if host == "hn.algolia.com":
            return httpx.Response(200, json={"hits": [{"objectID": "41", "title": "Ask HN: free PDF editors without watermarks?", "story_text": ""}]})
        if host == "api.stackexchange.com":
            return httpx.Response(200, json={"items": [{"link": "https://superuser.com/questions/9/pdf-editor", "title": "Free PDF editor that keeps form fields?"}]})
        if host == "api.indexnow.org":
            return httpx.Response(200, text="")
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


@pytest.fixture
def agency(tmp_path, fake_llm):
    from agency.app import Agency
    from agency.settings import Settings, VideoDefaults

    s = Settings(video=VideoDefaults(width=320, height=180, fps=8, max_seconds=240, shorts_seconds=5))
    s.limits.quiet_hours_utc = (25, 25)  # never
    a = Agency(settings=s, dry_run=True, llm=fake_llm, state_dir=tmp_path / "state", assets_dir=tmp_path / "assets", http_transport=mock_transport())
    return a
