"""Agency deliverables: the monthly editorial plan, the monthly report and a campaign
presentation.  Narrative comes from the brain; every number comes from the store.
Rendered as HTML (always) and PDF (through Chromium when available)."""
from __future__ import annotations

import calendar
import datetime as dt
import html
import json
import re
from pathlib import Path
from typing import Any, Callable

from agency.agents.base import Agent
from agency.agents.factcheck import NUMBER

CSS = """
body{font:14px/1.5 -apple-system,Helvetica,Arial,sans-serif;color:#111;margin:40px;max-width:900px}h1{font-size:26px;margin:0 0 4px}h2{font-size:17px;margin:26px 0 8px;border-bottom:2px solid #111;padding-bottom:4px}
table{border-collapse:collapse;width:100%;font-size:12.5px}td,th{border:1px solid #ccc;padding:5px 7px;text-align:left;vertical-align:top}th{background:#f2f2f2}.muted{color:#666}.k{display:inline-block;background:#eef;padding:2px 6px;border-radius:4px;margin:2px}
.cover{page-break-after:always}.week{page-break-inside:avoid}
"""


class Deliverables(Agent):
    role = "account director"
    desk = "director"
    temperature = 0.4

    def __init__(self, llm, store, brand, out_dir: Path, kb=None, settings=None, pdf: Callable[[str, Path], bool] | None = None):
        super().__init__(llm, store, brand)
        self.out_dir, self.kb, self.settings = out_dir, kb, settings
        self.pdf = pdf or render_pdf
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ monthly plan
    def monthly_plan(self, year: int, month: int, platforms: list[str]) -> dict[str, Any]:
        first = dt.date(year, month, 1)
        days = calendar.monthrange(year, month)[1]
        cadence = self.kb.playbook("cadence", 3000) if self.kb else ""
        recent = self.store.recent_topics(60)
        lessons = "\n".join(n["text"][:300] for n in self.store.recent_notes(10) if n["source"] == "analyst")
        with self.report(f"editorial plan {first:%B %Y}"):
            data = self.ask_json(
                f"Build the editorial plan for {first:%B %Y} ({days} days) for {self.brand.name}.\nPlatforms in use: {platforms}\nPillars: {self.brand.pillars}\n"
                f"Cadence defaults: {cadence}\nTopics covered recently (do not repeat): {recent[:40]}\nAnalyst lessons: {lessons or '(none yet)'}\n"
                "Give each week a theme tied to the calendar (events, releases, seasons) and the pillars; give every day 1-4 items (kind: post|article|video|carousel|short|pin), each with the platform(s), "
                "a working title (the finding, not the topic), the guide URL it links to (an existing guide URL from the site if you know one, otherwise 'new guide needed: <subject>') and the series it belongs to. "
                "Max one video per week, one article per week day Mon/Wed/Fri. Everything in English.\n"
                'Return JSON: {"month_theme": "...", "weeks": [{"week": 1, "theme": "...", "days": [{"day": 1, "items": [{"kind": "post", "platforms": ["bluesky"], "title": "...", "guide": "...", "series": "..."}]}]}]}'
            )
        plan = {"year": year, "month": month, "generated_at": dt.datetime.now().isoformat(timespec="seconds"), **(data if isinstance(data, dict) else {})}
        plan = _guard_numbers(plan)
        html_doc = self._plan_html(plan, first)
        paths = self._write("plan", f"{year}-{month:02d}", html_doc)
        self.store.add_deliverable("plan", f"{first:%B %Y}", plan, paths)
        return {**plan, **paths}

    def items_for_day(self, day: dt.date) -> list[dict[str, Any]]:
        """What the current monthly plan says for a date (used by the director's daily cycle)."""
        d = self.store.latest_deliverable("plan", f"{day:%B %Y}")
        if not d:
            return []
        for w in d["data"].get("weeks", []):
            for dd in w.get("days", []):
                if int(dd.get("day", 0)) == day.day:
                    return list(dd.get("items", []))
        return []

    # ------------------------------------------------------------------ monthly report
    def monthly_report(self, year: int, month: int) -> dict[str, Any]:
        first = dt.date(year, month, 1)
        published = [c for c in self.store.list_content(status="published", limit=2000) if (c.get("published_at") or "").startswith(f"{year}-{month:02d}")]
        metrics = self.store.metrics_summary(45)
        by_platform: dict[str, int] = {}
        for c in published:
            by_platform[c["platform"]] = by_platform.get(c["platform"], 0) + 1
        corrections = self.store.count_corrections()
        with self.report(f"monthly report {first:%B %Y}"):
            data = self.ask_json(
                f"Write the narrative of the monthly report for {first:%B %Y}. Numbers you may cite are ONLY these: published per platform {by_platform}, total published {len(published)}, top posts {metrics[:15]}, human corrections {corrections}. "
                "Sections: what went out, what worked (with the specific posts), what did not, what we learned, next month's three priorities. Honest, plain English, no hype.\n"
                'Return JSON: {"summary": "...", "worked": ["..."], "did_not": ["..."], "learned": ["..."], "priorities": ["..."]}'
            )
        report = {"year": year, "month": month, "published": len(published), "by_platform": by_platform, "top": metrics[:15], "corrections": corrections, **(data if isinstance(data, dict) else {})}
        allowed = {str(v) for v in by_platform.values()} | {str(len(published)), str(corrections)} | {str(m.get(k)) for m in metrics[:15] for k in ("impressions", "likes", "replies", "shares", "clicks") if m.get(k) is not None}
        report = _guard_numbers(report, allowed)
        html_doc = self._report_html(report, first)
        paths = self._write("report", f"{year}-{month:02d}", html_doc)
        self.store.add_deliverable("report", f"{first:%B %Y}", report, paths)
        return {**report, **paths}

    # ------------------------------------------------------------------ campaign
    def campaign(self, brief: str, platforms: list[str], weeks: int = 4) -> dict[str, Any]:
        with self.report(f"campaign: {brief[:50]}"):
            data = self.ask_json(
                f"Design a {weeks}-week campaign for {self.brand.name} from this brief: {brief}\nPlatforms: {platforms}\nPillars: {self.brand.pillars}\nHouse rules: {self.brand.voice}\n"
                "Deliver: the big idea in one sentence, the audience and the one belief we want to change, three hook options (first lines), the content pieces per platform (kind, title, why), "
                "the assets to produce (images, carousels, videos with length), a week-by-week timeline, how we measure it (which of our own metrics), and the risks. No numbers you cannot know.\n"
                'Return JSON: {"name": "...", "idea": "...", "audience": "...", "belief": "...", "hooks": ["..."], "pieces": [{"platform": "...", "kind": "...", "title": "...", "why": "..."}], '
                '"assets": [{"type": "...", "spec": "..."}], "timeline": [{"week": 1, "focus": "...", "pieces": ["..."]}], "measurement": ["..."], "risks": ["..."]}'
            )
        camp = {"brief": brief, "platforms": platforms, "weeks": weeks, "generated_at": dt.datetime.now().isoformat(timespec="seconds"), **(data if isinstance(data, dict) else {})}
        camp = _guard_numbers(camp, {str(weeks)} | {str(i) for i in range(1, weeks + 1)})
        html_doc = self._campaign_html(camp)
        slug = re.sub(r"[^a-z0-9]+", "-", str(camp.get("name") or brief).lower()).strip("-")[:50] or "campaign"
        paths = self._write("campaign", slug, html_doc)
        self.store.add_deliverable("campaign", camp.get("name") or brief[:80], camp, paths)
        return {**camp, **paths}

    # ------------------------------------------------------------------ rendering
    def _write(self, kind: str, slug: str, html_doc: str) -> dict[str, str]:
        html_path = self.out_dir / f"{kind}-{slug}.html"
        html_path.write_text(html_doc, encoding="utf-8")
        pdf_path = self.out_dir / f"{kind}-{slug}.pdf"
        ok = False
        try:
            ok = self.pdf(html_doc, pdf_path)
        except Exception:  # noqa: BLE001
            ok = False
        return {"html": str(html_path), "pdf": str(pdf_path) if ok else ""}

    def _shell(self, title: str, subtitle: str, body: str) -> str:
        return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style></head><body><h1>{html.escape(title)}</h1><p class='muted'>{html.escape(subtitle)} · {html.escape(self.brand.name)} · generated {dt.date.today().isoformat()} by the in-house AI agency</p>{body}</body></html>"

    def _plan_html(self, plan: dict[str, Any], first: dt.date) -> str:
        parts = [f"<p><b>Theme of the month:</b> {html.escape(str(plan.get('month_theme', '')))}</p>"]
        for w in plan.get("weeks", []):
            rows = "".join(
                f"<tr><td>{html.escape(str(d.get('day')))}</td><td>{html.escape(str(it.get('kind')))}</td><td>{html.escape(', '.join(it.get('platforms', [])))}</td><td>{html.escape(str(it.get('title')))}</td><td>{html.escape(str(it.get('guide', '')))}</td><td>{html.escape(str(it.get('series', '')))}</td></tr>"
                for d in w.get("days", []) for it in d.get("items", [])
            )
            parts.append(f"<div class='week'><h2>Week {html.escape(str(w.get('week')))}: {html.escape(str(w.get('theme', '')))}</h2><table><tr><th>day</th><th>kind</th><th>platforms</th><th>title</th><th>guide</th><th>series</th></tr>{rows}</table></div>")
        return self._shell(f"Editorial plan · {first:%B %Y}", "every item still goes through writing, fact check, safety and your approval", "".join(parts))

    def _report_html(self, r: dict[str, Any], first: dt.date) -> str:
        bp = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(r.get("by_platform", {}).items(), key=lambda kv: -kv[1]))
        top = "".join(f"<tr><td>{html.escape(str(m.get('platform')))}</td><td>{html.escape(str(m.get('kind')))}</td><td>{html.escape(str(m.get('title') or '')[:70])}</td><td>{m.get('impressions') or ''}</td><td>{m.get('likes') or ''}</td><td>{m.get('replies') or ''}</td><td>{m.get('shares') or ''}</td></tr>" for m in r.get("top", []))
        lists = "".join(f"<h2>{html.escape(t)}</h2><ul>{''.join('<li>' + html.escape(str(x)) + '</li>' for x in r.get(k, []))}</ul>" for t, k in (("What worked", "worked"), ("What did not", "did_not"), ("What we learned", "learned"), ("Next month's priorities", "priorities")))
        body = f"<p>{html.escape(str(r.get('summary', '')))}</p><h2>Published: {r.get('published', 0)} pieces</h2><table><tr><th>platform</th><th>pieces</th></tr>{bp}</table><h2>Top content (our own metrics)</h2><table><tr><th>platform</th><th>kind</th><th>title</th><th>impr.</th><th>likes</th><th>replies</th><th>shares</th></tr>{top}</table>{lists}<p class='muted'>Human corrections saved this far: {r.get('corrections', 0)}</p>"
        return self._shell(f"Monthly report · {first:%B %Y}", "numbers come from the platforms' official APIs; narrative by the director", body)

    def _campaign_html(self, c: dict[str, Any]) -> str:
        hooks = "".join(f"<li>{html.escape(str(h))}</li>" for h in c.get("hooks", []))
        pieces = "".join(f"<tr><td>{html.escape(str(p.get('platform')))}</td><td>{html.escape(str(p.get('kind')))}</td><td>{html.escape(str(p.get('title')))}</td><td>{html.escape(str(p.get('why', '')))}</td></tr>" for p in c.get("pieces", []))
        assets = "".join(f"<tr><td>{html.escape(str(a.get('type')))}</td><td>{html.escape(str(a.get('spec', '')))}</td></tr>" for a in c.get("assets", []))
        timeline = "".join(f"<tr><td>{html.escape(str(t.get('week')))}</td><td>{html.escape(str(t.get('focus', '')))}</td><td>{html.escape(', '.join(str(x) for x in t.get('pieces', [])))}</td></tr>" for t in c.get("timeline", []))
        body = (
            f"<div class='cover'><p><b>Brief:</b> {html.escape(str(c.get('brief', '')))}</p><h2>The idea</h2><p>{html.escape(str(c.get('idea', '')))}</p><p><b>Audience:</b> {html.escape(str(c.get('audience', '')))}<br><b>Belief to change:</b> {html.escape(str(c.get('belief', '')))}</p><h2>Hooks</h2><ol>{hooks}</ol></div>"
            f"<h2>Pieces</h2><table><tr><th>platform</th><th>kind</th><th>title</th><th>why</th></tr>{pieces}</table><h2>Assets</h2><table><tr><th>type</th><th>spec</th></tr>{assets}</table>"
            f"<h2>Timeline</h2><table><tr><th>week</th><th>focus</th><th>pieces</th></tr>{timeline}</table><h2>Measurement</h2><ul>{''.join('<li>' + html.escape(str(m)) + '</li>' for m in c.get('measurement', []))}</ul><h2>Risks</h2><ul>{''.join('<li>' + html.escape(str(r)) + '</li>' for r in c.get('risks', []))}</ul>"
        )
        return self._shell(f"Campaign · {c.get('name', 'untitled')}", f"{c.get('weeks', 4)} weeks · {', '.join(c.get('platforms', []))}", body)


def _guard_numbers(obj: Any, allowed: set[str] | None = None) -> Any:
    """Strip sentences that carry numbers the data does not justify (narrative fields only)."""
    allowed = allowed or set()

    def clean_text(text: str) -> str:
        out = []
        for sent in re.split(r"(?<=[.!?])\s+", text):
            nums = [n.replace(",", "").replace("$", "").rstrip("%") for n in NUMBER.findall(sent)]
            nums = [n for n in nums if not re.fullmatch(r"(19|20)\d\d", n) and not (n.isdigit() and int(n) <= 12)]
            if nums and not all(n in allowed for n in nums):
                continue
            out.append(sent)
        return " ".join(out)

    def walk(x: Any, key: str = "") -> Any:
        if isinstance(x, dict):
            return {k: walk(v, k) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v, key) for v in x]
        if isinstance(x, str) and key in ("summary", "idea", "worked", "did_not", "learned", "priorities", "why", "focus", "measurement", "risks", "belief", "audience"):
            return clean_text(x)
        return x

    return walk(obj)


def render_pdf(html_doc: str, out: Path) -> bool:
    """HTML → PDF through Chromium (Playwright). Returns False when no browser is available."""
    try:
        from playwright.sync_api import sync_playwright

        from agency.browser.operator import default_executable
    except ImportError:
        return False
    exe = default_executable()
    try:
        with sync_playwright() as p:
            kw: dict[str, Any] = {"headless": True}
            if exe:
                kw["executable_path"] = exe
            else:
                kw["channel"] = "chrome"
            try:
                b = p.chromium.launch(**kw)
            except Exception:  # noqa: BLE001
                b = p.chromium.launch(headless=True)
            page = b.new_page()
            page.set_content(html_doc, wait_until="load")
            page.pdf(path=str(out), format="A4", print_background=True, margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"})
            b.close()
        return out.exists()
    except Exception:  # noqa: BLE001
        return False
