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

NAV = ["office", "queue", "content", "assets", "platforms", "knowledge", "learning", "models", "scout", "logs"]


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
        return render(request, "learning.html", corrections=corrections, count=agency.store.count_corrections(), notes=agency.store.recent_notes(20), metrics=agency.store.metrics_summary(30))

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
            "video": lambda: agency.director.produce_video(topic or "a guide from our site", angle or "practical, verified", target_seconds=seconds or None),
            "post": lambda: agency.director.produce_post(platform, topic or "a guide from our site", angle or "practical, verified", with_image=True),
        }
        if job not in fns:
            raise HTTPException(404)
        started = background(job, fns[job])
        agency.note(f"job {job}: {'started' if started else 'already running'}")
        return RedirectResponse("/" if job not in ("benchmark",) else "/models", status_code=303)

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
    "block_mass_actions": "Hard guarantee: no automated follows, friend requests or comments on others' content.",
}
