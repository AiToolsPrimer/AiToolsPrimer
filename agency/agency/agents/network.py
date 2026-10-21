"""Network: affine sites and accounts worth following, their new posts, and comments
drafted for your approval.  Nothing is followed or commented automatically."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from agency.agents.authority import Authority
from agency.agents.base import Agent
from agency.safety.payment_guard import GuardedHTTP
from agency.safety.policy import Action, ActionKind, Decision

RSS_LINK = re.compile(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', re.I)
BSKY_PUBLIC = "https://public.api.bsky.app/xrpc"


class NetworkAgent(Agent):
    role = "network and partnerships"
    desk = "network"
    temperature = 0.4

    def __init__(self, llm, store, brand, http: GuardedHTTP, authority: Authority, submit: Callable[[Action, dict[str, Any]], Decision], writer=None, factcheck=None):
        super().__init__(llm, store, brand)
        self.http, self.authority, self.submit, self.writer, self.factcheck = http, authority, submit, writer, factcheck

    # ------------------------------------------------------------------ discovery
    def search(self, query: str, limit: int = 15) -> list[dict[str, str]]:
        try:
            r = self.http.get("https://html.duckduckgo.com/html/", params={"q": query})
        except Exception:  # noqa: BLE001
            return []
        out = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
            if "uddg=" in href:
                href = unquote(parse_qs(urlsplit(href).query).get("uddg", [href])[0])
            out.append({"url": href, "title": html.unescape(title).strip()})
            if len(out) >= limit:
                break
        return out

    def find_feed(self, url: str) -> str:
        try:
            r = self.http.get(url, headers={"Accept": "text/html"})
        except Exception:  # noqa: BLE001
            return ""
        if r.status_code >= 400:
            return ""
        m = RSS_LINK.search(r.text)
        if m:
            return urljoin(url, html.unescape(m.group(1)))
        for cand in ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml"):
            try:
                c = self.http.get(urljoin(url, cand))
                if c.status_code == 200 and ("<rss" in c.text[:2000] or "<feed" in c.text[:2000]):
                    return urljoin(url, cand)
            except Exception:  # noqa: BLE001
                continue
        return ""

    def bluesky_accounts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        try:
            r = self.http.get(f"{BSKY_PUBLIC}/app.bsky.actor.searchActors", params={"q": query, "limit": limit})
            if r.status_code != 200:
                return []
            return [{"handle": a.get("handle"), "name": a.get("displayName", ""), "description": a.get("description", ""), "url": f"https://bsky.app/profile/{a.get('handle')}"} for a in r.json().get("actors", [])]
        except Exception:  # noqa: BLE001
            return []

    def discover(self, max_new: int = 12) -> list[dict[str, Any]]:
        if not self.submit(Action(ActionKind.NETWORK_WATCH, "web"), {}).allowed:
            return []
        with self.report("discovering affine sites and accounts", steps=len(self.brand.pillars) + 1):
            candidates: list[dict[str, Any]] = []
            for i, pillar in enumerate(self.brand.pillars, 1):
                self.progress(pillar[:50], i, len(self.brand.pillars) + 1)
                for r in self.search(f"{pillar} blog OR newsletter OR guide", limit=10):
                    if self.authority.domain(r["url"]) == self.authority.domain(self.brand.site):
                        continue
                    candidates.append({"kind": "site", "name": r["title"][:120], "url": r["url"], "platform": "web", "rank": self.authority.rank(r["url"])})
                for a in self.bluesky_accounts(pillar.split(" ")[0] + " " + pillar.split(" ")[-1], limit=6):
                    candidates.append({"kind": "account", "name": a["name"] or a["handle"], "url": a["url"], "platform": "bluesky", "rank": None, "description": a.get("description", "")})
            self.progress("ranking", len(self.brand.pillars) + 1, len(self.brand.pillars) + 1)
            seen, uniq = set(), []
            for c in candidates:
                key = self.authority.domain(c["url"]) + c["url"].split("/")[-1]
                if key in seen or not c["url"].startswith("http"):
                    continue
                seen.add(key)
                uniq.append(c)
            if not uniq:
                return []
            data = self.ask_json(
                f"Which of these sites and accounts are genuinely relevant to {self.brand.name} ({self.brand.tagline}; pillars: {self.brand.pillars}) and worth following for conversations and partnerships? "
                f"Skip competitors that would not welcome us, link farms, stores and generic news.\nCandidates: {uniq[:60]}\n"
                'Return JSON: {"keep": [{"url": "...", "relevance": 0.0-1.0, "why": "one line"}]}'
            )
            kept = {k["url"]: k for k in (data.get("keep", []) if isinstance(data, dict) else []) if k.get("url")}
            added = []
            for c in uniq:
                k = kept.get(c["url"])
                if not k or float(k.get("relevance", 0)) < 0.5:
                    continue
                feed = self.find_feed(c["url"]) if c["kind"] == "site" else ""
                sid = self.store.add_network_source(c["kind"], c["name"], c["url"], c["platform"], feed_url=feed, domain_rank=c.get("rank"), relevance=float(k.get("relevance", 0)), why=k.get("why", ""))
                if sid:
                    added.append({"id": sid, **c, "feed": feed})
                if len(added) >= max_new:
                    break
            return added

    # ------------------------------------------------------------------ following
    def fetch_new_items(self, source: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if source["platform"] == "bluesky":
            handle = source["url"].rsplit("/", 1)[-1]
            try:
                r = self.http.get(f"{BSKY_PUBLIC}/app.bsky.feed.getAuthorFeed", params={"actor": handle, "limit": limit, "filter": "posts_no_replies"})
                for it in (r.json().get("feed", []) if r.status_code == 200 else []):
                    post = it.get("post", {})
                    rkey = post.get("uri", "").rsplit("/", 1)[-1]
                    items.append({"url": f"https://bsky.app/profile/{handle}/post/{rkey}", "title": post.get("record", {}).get("text", "")[:200], "published": post.get("indexedAt", ""), "remote_id": f"{post.get('uri')}|{post.get('cid')}"})
            except Exception:  # noqa: BLE001
                return []
        elif source.get("feed_url"):
            try:
                r = self.http.get(source["feed_url"])
                if r.status_code == 200:
                    items = _parse_feed(r.text)[:limit]
            except Exception:  # noqa: BLE001
                return []
        new = []
        for it in items:
            iid = self.store.add_network_item(source["id"], it["url"], it.get("title", ""), it.get("published", ""), it.get("remote_id", ""))
            if iid:
                new.append({"id": iid, **it})
        return new

    def watch(self) -> dict[str, Any]:
        if not self.submit(Action(ActionKind.NETWORK_WATCH, "web"), {}).allowed:
            return {"skipped": "network_watch switch is off"}
        sources = self.store.list_network_sources(status="following")
        with self.report(f"reading {len(sources)} followed source(s)", steps=len(sources)):
            total = 0
            for i, src in enumerate(sources, 1):
                self.progress(src["name"][:50], i, len(sources))
                total += len(self.fetch_new_items(src))
            return {"sources": len(sources), "new_items": total}

    # ------------------------------------------------------------------ comments (drafts, approved one by one)
    def draft_comments(self, max_items: int = 10) -> list[dict[str, Any]]:
        if not self.toggles_allow():
            return []
        items = self.store.list_network_items(uncommented=True)[:max_items]
        out = []
        with self.report(f"drafting comments on {len(items)} new post(s)", steps=len(items)):
            for i, it in enumerate(items, 1):
                self.progress(it["title"][:50], i, len(items))
                data = self.ask_json(
                    f"A source we follow published: {it['title']}\nURL: {it['url']}\n"
                    f"Write a genuinely useful comment from {self.brand.name} in one to three sentences: add a fact, a nuance or a question. No link unless one of our guides directly answers and then only its URL. "
                    "If there is nothing useful to add, set skip=true.\n"
                    'Return JSON: {"text": "...", "skip": false, "guide_url": ""}'
                )
                if data.get("skip") or not data.get("text"):
                    self.store.mark_network_item(it["id"], "skipped")
                    continue
                text = str(data["text"]).strip()
                if self.factcheck:
                    facts = self.factcheck.facts_for(data.get("guide_url", "")) if str(data.get("guide_url", "")).startswith("http") else []
                    r = self.factcheck.verify(text, facts, kind="comment")
                    if not r.ok:
                        self.store.mark_network_item(it["id"], "skipped")
                        continue
                    text = r.text
                src = self.store.get_network_source(it["source_id"])
                platform = src["platform"] if src else "web"
                cid = self.store.add_content("comment", platform, topic=it["title"][:80], title=f"comment on {it['title'][:60]}", body=text, status="queued", meta={"target_url": it["url"], "target_remote_id": it.get("remote_id", ""), "network_item": it["id"], "hold_reason": "external comment: waits for your approval"})
                self.store.mark_network_item(it["id"], "drafted", content_id=cid)
                out.append({"content_id": cid, "url": it["url"]})
        return out

    def toggles_allow(self) -> bool:
        return self.submit(Action(ActionKind.NETWORK_WATCH, "web"), {}).allowed


def _parse_feed(xml: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError:
        return out
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for item in root.iter("item"):
        out.append({"url": (item.findtext("link") or "").strip(), "title": (item.findtext("title") or "").strip(), "published": (item.findtext("pubDate") or "").strip()})
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = entry.find("atom:link", ns)
        out.append({"url": (link.get("href") if link is not None else "") or "", "title": (entry.findtext("atom:title", default="", namespaces=ns) or "").strip(), "published": (entry.findtext("atom:updated", default="", namespaces=ns) or "").strip()})
    return [o for o in out if o["url"]]
