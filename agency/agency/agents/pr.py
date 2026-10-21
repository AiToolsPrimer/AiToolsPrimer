"""PR: backlinks only from sites that matter.

Sources of opportunities: journalist requests (from the mail digests), unlinked mentions
of the brand on authoritative sites, broken outbound links on authoritative pages in our
niche that one of our guides could replace.  Every opportunity ends as a pitch in the
queue; you send it.  Nothing is ever posted to a forum, a directory or a comment box."""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from agency.agents.authority import Authority
from agency.agents.base import Agent
from agency.agents.factcheck import html_to_text
from agency.safety.payment_guard import GuardedHTTP

LINK_RE = re.compile(r'<a[^>]+href="(https?://[^"#]+)"', re.I)


class PRAgent(Agent):
    role = "PR and backlinks"
    desk = "pr"
    temperature = 0.4

    def __init__(self, llm, store, brand, http: GuardedHTTP, authority: Authority, factcheck=None):
        super().__init__(llm, store, brand)
        self.http, self.authority, self.factcheck = http, authority, factcheck

    # ------------------------------------------------------------------ search helpers
    def search(self, query: str, limit: int = 20) -> list[dict[str, str]]:
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

    def _own(self, url: str) -> bool:
        return self.authority.domain(url) == self.authority.domain(self.brand.site)

    # ------------------------------------------------------------------ unlinked mentions
    def unlinked_mentions(self, max_pages: int = 15) -> list[dict[str, Any]]:
        found = []
        with self.report("looking for unlinked mentions", steps=max_pages):
            results = [r for r in self.search(f'"{self.brand.name}" -site:{self.authority.domain(self.brand.site)}', limit=40) if not self._own(r["url"])]
            for i, r in enumerate(results[:max_pages], 1):
                self.progress(r["url"][:60], i, max_pages)
                if not self.authority.is_authoritative(r["url"]):
                    continue
                try:
                    page = self.http.get(r["url"], headers={"Accept": "text/html"})
                except Exception:  # noqa: BLE001
                    continue
                if page.status_code >= 400 or self.brand.name.lower() not in page.text.lower():
                    continue
                if self.authority.domain(self.brand.site) in page.text.lower():
                    continue   # already linked
                pid = self.store.add_pr_opportunity("unlinked_mention", r["url"], contact="", summary=f"Mentions {self.brand.name} without a link (rank {self.authority.rank(r['url'])})", detail=r["title"], fit=0.8, extra={"domain_rank": self.authority.rank(r["url"])})
                if pid:
                    found.append({"id": pid, "url": r["url"]})
        return found

    # ------------------------------------------------------------------ broken links
    def broken_links(self, pages: list[str], guides: list[dict[str, str]], max_links_per_page: int = 40) -> list[dict[str, Any]]:
        found = []
        with self.report("checking authoritative pages for dead links", steps=len(pages)):
            for i, url in enumerate(pages, 1):
                self.progress(url[:60], i, len(pages))
                if not self.authority.is_authoritative(url):
                    continue
                try:
                    page = self.http.get(url, headers={"Accept": "text/html"})
                except Exception:  # noqa: BLE001
                    continue
                if page.status_code >= 400:
                    continue
                links = [l for l in dict.fromkeys(LINK_RE.findall(page.text)) if self.authority.domain(l) != self.authority.domain(url)][:max_links_per_page]
                dead = []
                for link in links:
                    if self._is_dead(link):
                        dead.append(link)
                if not dead:
                    continue
                match = self.ask_json(
                    f"A page on an authoritative site ({url}) links to these dead URLs: {dead}\nOur guides: {guides[:80]}\n"
                    "For each dead link, name the one guide of ours that is a genuine replacement (same subject), or none. Be honest: no fit means none.\n"
                    'Return JSON: {"matches": [{"dead": "...", "guide_url": "...", "why": "one line"}]}'
                )
                for mt in (match.get("matches", []) if isinstance(match, dict) else []):
                    if mt.get("guide_url") and mt["guide_url"] != "none":
                        pid = self.store.add_pr_opportunity("broken_link", url, contact="", summary=f"Dead link {mt['dead'][:60]} could point to {mt['guide_url']}", detail=mt.get("why", ""), fit=0.7, extra={"dead": mt["dead"], "guide_url": mt["guide_url"], "domain_rank": self.authority.rank(url)})
                        if pid:
                            found.append({"id": pid, "page": url, "dead": mt["dead"], "guide": mt["guide_url"]})
        return found

    def _is_dead(self, url: str) -> bool:
        if re.search(r"(amazon|ebay|apple\.com/shop|play\.google)", url):
            return False   # never pitch product/store links
        try:
            r = self.http.request("HEAD", url, timeout=15)
            if r.status_code in (404, 410):
                return True
            if r.status_code >= 400 and r.status_code != 405:
                r = self.http.get(url, timeout=15)
                return r.status_code in (404, 410)
        except Exception:  # noqa: BLE001
            return False
        return False

    # ------------------------------------------------------------------ pitches
    def write_pitch(self, opportunity_id: int) -> dict[str, Any] | None:
        opp = self.store.get_pr_opportunity(opportunity_id)
        if not opp:
            return None
        with self.report(f"pitch for {opp['kind']} #{opportunity_id}"):
            facts = ""
            guide = (opp.get("extra") or {}).get("guide_url") or (opp.get("extra") or {}).get("guide_hint") or ""
            if self.factcheck and guide.startswith("http"):
                facts = self.factcheck.facts_text(self.factcheck.facts_for(guide))
            data = self.ask_json(
                f"Write a pitch email for this opportunity.\nKind: {opp['kind']}\nSource: {opp['source']}\nSummary: {opp['summary']}\nDetail: {opp['detail']}\nDeadline: {opp.get('deadline','')}\n"
                f"Guide to offer: {guide or '(choose from our pillars)'}\nVerified facts you may cite (only these): {facts or '(none: no numbers)'}\n"
                f"Sender: the editor of {self.brand.name} ({self.brand.site}). Rules: under 150 words, specific, no flattery, one concrete offer (a quote, a data point, a corrected link), "
                "no attachments, no follow-up threats, honest about who we are. Subject line under 60 characters.\n"
                'Return JSON: {"subject": "...", "body": "...", "to": "the address if known else empty"}'
            )
            subject, body = str(data.get("subject", "")).strip(), str(data.get("body", "")).strip()
            if self.factcheck:
                r = self.factcheck.verify(body, self.factcheck.facts_for(guide) if guide.startswith("http") else [], kind="pitch email")
                body = r.text
            self.store.set_pr_pitch(opportunity_id, subject, body)
            return {"subject": subject, "body": body}
