"""The control panel: the office in real time, the approval queue, content pipelines,
assets, platforms, knowledge, learning, models and logs. Local only, English."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from agency.app import Agency
from agency.models import registry
from agency.settings import LOCKED_TOGGLES

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

NAV = ["office", "queue", "operator", "outreach", "deliverables", "content", "assets", "platforms", "knowledge", "learning", "models", "scout", "logs"]


def create_app(agency: Agency) -> FastAPI:
    app = FastAPI(title="AI Tools Primer Agency", docs_url="/api/docs")
    jobs: dict[str, threading.Thread] = {}

    def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        base = {"request": request, "status": agency.status(), "page": name.split(".")[0], "locked": LOCKED_TOGGLES, "toggle_help": TOGGLE_HELP, "nav": NAV}
        return TEMPLATES.TemplateResponse(request, name, {**base, **ctx})

    def background(name: str, fn) -> bool:
        t = jobs.get(name)
        if t and t.is_alive():
            return False
        t = threading.Thread(target=_safe(agency, name, fn), daemon=True, name=name)
        jobs[name] = t
        t.start()
        return True

    # ------------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def office(request: Request):
        return render(request, "office.html", board=agency.office.board(), queued=agency.store.list_content(status="queued", limit=8), running={n: t.is_alive() for n, t in jobs.items()})

    @app.get("/queue", response_class=HTMLResponse)
    def queue(request: Request):
        return render(request, "queue.html", items=agency.store.list_content(status="queued", limit=200), assets=agency.store)

    @app.get("/operator", response_class=HTMLResponse)
    def operator(request: Request):
        import datetime as dt
        clicks = agency.store.count_recent_actions("*browser*", "browser_publish", dt.timedelta(days=1))
        st = agency.status()
        st["limits_browser"] = agency.settings.limits.browser_actions_per_day
        return TEMPLATES.TemplateResponse(request, "operator.html", {"request": request, "status": st, "page": "operator", "locked": LOCKED_TOGGLES, "toggle_help": TOGGLE_HELP, "nav": NAV, "tasks": agency.operator.tasks(), "clicks_today": clicks})

    @app.get("/shot/{tid}")
    def shot(tid: int):
        t = agency.operator.task(tid)
        if not t or not t.screenshot or not Path(t.screenshot).exists():
            raise HTTPException(404)
        return FileResponse(t.screenshot)

    @app.post("/operator/{tid}/{what}")
    def operator_action(tid: int, what: str):
        if what == "publish":
            d = agency.director.browser_publish(tid)
            agency.office.emit("approve", "operator", f"task {tid}: {d.reason}")
        elif what == "cancel":
            agency.director.browser_cancel(tid)
        elif what == "mark":
            t = agency.operator.task(tid)
            if t:
                t.status = "published"
                cid = t.payload.get("content_id")
                if cid and agency.store.get_content(cid):
                    import datetime as dt
                    agency.store.update_content(cid, status="published", published_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), remote_id=f"browser-{tid}")
                    agency.store.log_action("browser_publish", t.platform, "allow", "published by hand after the operator filled it", cid, {"task": tid})
        return RedirectResponse("/operator", status_code=303)

    @app.get("/outreach", response_class=HTMLResponse)
    def outreach(request: Request):
        return render(request, "outreach.html", sources=agency.store.list_network_sources(), items=agency.store.list_network_items(limit=40), questions=agency.store.list_questions(40),
                      mail=agency.store.list_mail(40), drafts=agency.store.list_mail_drafts(limit=40), pr=agency.store.list_pr_opportunities(limit=60), mail_configured=agency.mail.mailbox is not None)

    @app.post("/network/add")
    def network_add(url: str = Form(...)):
        url = url.strip()
        if url:
            platform = "bluesky" if "bsky.app/profile/" in url else "web"
            feed = agency.network.find_feed(url) if platform == "web" else ""
            sid = agency.store.add_network_source("account" if platform == "bluesky" else "site", url, url, platform, feed_url=feed, relevance=1.0, why="added by you")
            if sid:
                agency.store.set_network_source_status(sid, "following")
        return RedirectResponse("/outreach", status_code=303)

    @app.post("/network/{sid}/{status}")
    def network_status(sid: int, status: str):
        if status in ("following", "dismissed", "suggested"):
            agency.store.set_network_source_status(sid, status)
        return RedirectResponse("/outreach", status_code=303)

    @app.post("/mail/draft/{did}/{status}")
    def mail_draft_status(did: int, status: str):
        if status in ("dismissed", "drafted"):
            agency.store.set_mail_draft_status(did, status)
        return RedirectResponse("/outreach", status_code=303)

    @app.post("/pr/{pid}/{what}")
    def pr_action(pid: int, what: str):
        if what == "pitch":
            background(f"pitch-{pid}", lambda: agency.pr.write_pitch(pid))
        elif what in ("sent", "dismissed", "found"):
            agency.store.set_pr_status(pid, what)
        return RedirectResponse("/outreach", status_code=303)

    @app.get("/content", response_class=HTMLResponse)
    def content(request: Request, status: str | None = None):
        return render(request, "content.html", items=agency.store.list_content(status=status, limit=300), filter=status or "")

    @app.get("/content/{cid}", response_class=HTMLResponse)
    def content_detail(request: Request, cid: int):
        row = agency.store.get_content(cid)
        if not row:
            raise HTTPException(404)
        actions = [a for a in agency.store.list_actions(500) if a.get("content_id") == cid]
        assets = [agency.store.get_asset(a) for a in row.get("assets", [])]
        return render(request, "content_detail.html", c=row, actions=actions, assets=[a for a in assets if a], mode=agency.mode_for(row["platform"]))

    @app.get("/assets", response_class=HTMLResponse)
    def assets(request: Request):
        return render(request, "assets.html", items=agency.store.list_assets(limit=200))

    @app.get("/asset/{aid}")
    def asset_file(aid: int):
        a = agency.store.get_asset(aid)
        if not a or not Path(a["path"]).exists():
            raise HTTPException(404)
        return FileResponse(a["path"])

    @app.get("/platforms", response_class=HTMLResponse)
    def platforms(request: Request):
        return render(request, "platforms.html", platforms=agency.platforms)

    @app.get("/knowledge", response_class=HTMLResponse)
    def knowledge(request: Request, card: str | None = None):
        kb = agency.kb
        checks = agency.store.knowledge_checks()
        cards = [{"key": k, "label": c.label, "last_checked": c.meta.get("last_checked"), "stale": c.stale(), "limits": {kk: v for kk, v in c.meta.items() if kk in ("char_limit", "hashtags_max", "link_policy", "ai_label", "publish")}, "checked": checks.get(k, "")} for k, c in kb.cards.items()]
        return render(request, "knowledge.html", cards=cards, playbooks=list(kb.playbooks), updates=agency.store.list_knowledge_updates(), selected=kb.card(card) if card else (kb.playbooks.get(card) if card else None), selected_key=card)

    @app.get("/learning", response_class=HTMLResponse)
    def learning(request: Request):
        corrections = agency.store.list_corrections(100)
        return render(request, "learning.html", corrections=corrections, count=agency.store.count_corrections(), notes=agency.store.recent_notes(20), metrics=agency.store.metrics_summary(30), rules=agency.learning.current_rules(), training=agency.learning.export_training_set() if agency.store.count_corrections() else {"examples": 0, "ready": False, "needed": 300})

    @app.get("/deliverables", response_class=HTMLResponse)
    def deliverables(request: Request):
        briefing = next((n for n in agency.store.recent_notes(30) if n["source"] == "briefing"), None)
        return render(request, "deliverables.html", items=agency.store.list_deliverables(), briefing=briefing)

    @app.get("/deliverable/{did}/{fmt}")
    def deliverable_file(did: int, fmt: str):
        rows = [d for d in agency.store.list_deliverables(500) if d["id"] == did]
        if not rows:
            raise HTTPException(404)
        path = rows[0]["pdf_path"] if fmt == "pdf" else rows[0]["html_path"]
        if not path or not Path(path).exists():
            raise HTTPException(404)
        return FileResponse(path)

    @app.post("/campaign")
    def campaign(brief: str = Form(...), weeks: int = Form(4)):
        platforms = [n for n, p in agency.platforms.items() if agency.toggles.platform_enabled(n) and agency.mode_for(n) != "off"]
        background("campaign", lambda: agency.deliverables.campaign(brief, platforms, weeks))
        return RedirectResponse("/deliverables", status_code=303)

    @app.get("/models", response_class=HTMLResponse)
    def models(request: Request):
        choice = agency.brain_choice.load()
        return render(request, "models.html", assignments=registry.ASSIGNMENTS, chosen=agency.models, profiles=list(registry.HARDWARE_PROFILES), choice=choice, host_history=agency.host.history[-30:])

    @app.get("/scout", response_class=HTMLResponse)
    def scout(request: Request):
        return render(request, "scout.html", items=agency.store.list_scout())

    @app.get("/logs", response_class=HTMLResponse)
    def logs(request: Request):
        return render(request, "logs.html", actions=agency.store.list_actions(200), blocked=agency.store.list_http_audit(100, blocked_only=True), events=agency.events[-200:])

    # ------------------------------------------------------------------ live
    @app.get("/events")
    def events():
        q = agency.office.subscribe()

        def gen():
            try:
                yield from agency.office.sse(q)
            finally:
                agency.office.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/office")
    def api_office():
        return JSONResponse(agency.office.board())

    # ------------------------------------------------------------------ actions
    @app.post("/toggle")
    def toggle(name: str = Form(...), value: str = Form(...)):
        on = value.lower() in {"1", "true", "on", "yes"}
        if name.startswith("platform:"):
            agency.toggles.set_platform(name.split(":", 1)[1], on)
        else:
            try:
                agency.toggles.set(name, on)
            except PermissionError as e:
                raise HTTPException(403, str(e))
        agency.note(f"switch {name} -> {'on' if on else 'off'}")
        agency.office.emit("switch", "director", f"{name} -> {'on' if on else 'off'}")
        return RedirectResponse("/", status_code=303)

    @app.post("/mode")
    def set_mode(platform: str = Form(...), mode: str = Form(...)):
        p = agency.platforms.get(platform)
        if not p or mode not in p.publish_modes:
            raise HTTPException(400, "unknown platform or mode")
        agency.prefs.set(f"mode:{platform}", mode)
        agency.office.emit("switch", "director", f"{platform} publishing mode -> {mode}")
        return RedirectResponse("/platforms", status_code=303)

    @app.post("/kill")
    def kill():
        agency.toggles.set("master_enabled", False)
        agency.toggles.set("publishing", False)
        agency.note("KILL SWITCH: everything frozen")
        agency.office.emit("kill", "director", "KILL SWITCH: everything frozen")
        return RedirectResponse("/", status_code=303)

    @app.post("/approve/{cid}")
    def approve(cid: int, body: str = Form(None)):
        d = agency.director.approve(cid, edited_body=body if body is not None and body.strip() else None)
        agency.note(f"approve #{cid}: {d.verdict.value} ({d.reason})")
        agency.office.emit("approve", "director", f"#{cid}: {d.verdict.value} ({d.reason})")
        return RedirectResponse("/queue", status_code=303)

    @app.post("/reject/{cid}")
    def reject(cid: int, reason: str = Form("rejected by human")):
        agency.director.reject(cid, reason)
        agency.office.emit("reject", "director", f"#{cid}: {reason}")
        return RedirectResponse("/queue", status_code=303)

    @app.post("/run/{job}")
    def run(job: str, topic: str = Form(""), angle: str = Form(""), seconds: int = Form(0), platform: str = Form("bluesky")):
        fns = {
            "daily": agency.director.daily_cycle,
            "community": agency.director.community_cycle,
            "analyst": agency.director.analyst_cycle,
            "scout": agency.director.scout_cycle,
            "news_watch": agency.news_watch.run,
            "benchmark": agency.benchmark_brains,
            "logins": lambda: agency.operator.open_logins(),
            "network": agency.director.network_cycle,
            "questions": agency.director.questions_cycle,
            "mail": agency.director.mail_cycle,
            "mail_drafts": agency.mail.save_drafts_to_gmail,
            "pr": agency.director.pr_cycle,
            "monthly": agency.monthly_deliverables,
            "plan": lambda: agency.deliverables.monthly_plan(__import__("datetime").date.today().year, __import__("datetime").date.today().month, [n for n, p in agency.platforms.items() if agency.toggles.platform_enabled(n) and agency.mode_for(n) != "off"]),
            "report": lambda: agency.deliverables.monthly_report(__import__("datetime").date.today().year, __import__("datetime").date.today().month),
            "briefing": lambda: agency.director.briefing(voice=agency.toggles.get("make_voiceover")),
            "style": agency.refresh_style,
            "video": lambda: agency.director.produce_video(topic or "a guide from our site", angle or "practical, verified", target_seconds=seconds or None),
            "post": lambda: agency.director.produce_post(platform, topic or "a guide from our site", angle or "practical, verified", with_image=True),
        }
        if job not in fns:
            raise HTTPException(404)
        started = background(job, fns[job])
        agency.note(f"job {job}: {'started' if started else 'already running'}")
        target = "/models" if job == "benchmark" else "/outreach" if job in ("network", "questions", "mail", "mail_drafts", "pr") else "/deliverables" if job in ("monthly", "plan", "report", "briefing") else "/learning" if job == "style" else "/"
        return RedirectResponse(target, status_code=303)

    @app.post("/scout/{sid}/{what}")
    def scout_action(sid: int, what: str):
        if what == "kit":
            background(f"kit-{sid}", lambda: agency.scout.prepare_kit(sid))
        elif what in {"registered", "dismissed", "found"}:
            agency.store.set_scout_status(sid, what)
        return RedirectResponse("/scout", status_code=303)

    @app.post("/knowledge/update/{uid}/{what}")
    def knowledge_update(uid: int, what: str):
        if what == "apply":
            agency.news_watch.apply(uid)
        elif what == "dismiss":
            agency.store.set_knowledge_update_status(uid, "dismissed")
        return RedirectResponse("/knowledge", status_code=303)

    # ------------------------------------------------------------------ json api
    @app.get("/api/status")
    def api_status():
        return JSONResponse(agency.status())

    @app.get("/api/queue")
    def api_queue():
        return JSONResponse(agency.store.list_content(status="queued"))

    @app.post("/api/toggle/{name}/{value}")
    def api_toggle(name: str, value: str):
        try:
            agency.toggles.set(name, value in {"1", "true", "on"})
        except PermissionError as e:
            raise HTTPException(403, str(e))
        return {"ok": True, "toggles": agency.toggles.all()}

    return app


def _safe(agency: Agency, name: str, fn):
    def run():
        try:
            agency.note(f"{name}: running")
            agency.office.emit("job", "director", f"{name}: started")
            out = fn()
            agency.note(f"{name}: done {str(out)[:200] if out is not None else ''}")
            agency.office.emit("job", "director", f"{name}: done")
        except Exception as e:  # noqa: BLE001
            agency.note(f"{name}: ERROR {e}")
            agency.office.emit("error", "director", f"{name}: {e}")
    return run


TOGGLE_HELP = {
    "master_enabled": "Kill switch. Off = every agent stops, nothing runs.",
    "publishing": "Off = everything produced waits in the queue, nothing leaves the Mac.",
    "approval_required": "On = each item needs your click, even with publishing on.",
    "write_posts": "Short posts for social platforms.",
    "write_articles": "Long articles for DEV, Hashnode, WordPress, Medium, Substack.",
    "make_images": "Illustrations, covers, thumbnails, carousels (Qwen-Image-2512).",
    "make_videos": "Videos up to 4 minutes (LTX-2.5 + voice + music).",
    "make_shorts": "Vertical cuts of every video for Shorts, TikTok, Reels.",
    "make_voiceover": "Voiceover with Step-Audio-EditX (Kokoro fallback).",
    "make_music": "Music beds with ACE-Step 1.5.",
    "auto_reply_own_posts": "Answer comments under our own posts (still obeys approval_required).",
    "draft_external_engagement": "Draft replies on other people's posts for you to send by hand (never sent by the agency).",
    "discover_platforms": "The scout searches for new free platforms worth a presence.",
    "prepare_signup_kits": "For good finds, prepare handle, bios, avatar, banner and first posts. You create the account.",
    "collect_metrics": "Read our own posts' numbers through the official APIs.",
    "block_payments": "Hard guarantee: no request can reach a payment, ads or billing endpoint.",
    "block_account_creation": "Hard guarantee: accounts are created by a person, never by the agency.",
    "browser_operator": "Fill posts and comments in the agent's Chrome; you click Publish.",
    "make_podcast": "Read every article into the podcast feed with the local voice.",
    "push_indexnow": "Tell Bing and partners about new pages of the site.",
    "read_mail": "Read the inbox (IMAP, read-only) and draft replies; nothing is sent.",
    "network_watch": "Follow affine sites and accounts, draft comments that wait for your approval.",
    "block_mass_actions": "Hard guarantee: no automated follows or friend requests, no comments on others' content without your click, never in bulk.",
}
