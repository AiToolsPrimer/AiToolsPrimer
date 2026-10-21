"""Command line: agency init | doctor | run | cycle | video | post | queue | approve | toggle"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from agency.settings import CONFIG_DIR, ROOT, STATE_DIR


def cmd_init(args: argparse.Namespace) -> int:
    CONFIG_DIR.mkdir(exist_ok=True)
    STATE_DIR.mkdir(exist_ok=True)
    target = CONFIG_DIR / "agency.yaml"
    if not target.exists():
        shutil.copy(CONFIG_DIR / "agency.example.yaml", target)
        print(f"wrote {target}")
    env = ROOT / ".env"
    if not env.exists():
        shutil.copy(ROOT / ".env.example", env)
        print(f"wrote {env} (fill in the platforms you use)")
    print("next: agency doctor")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    import httpx

    from agency.app import Agency
    from agency.models import registry

    a = Agency(dry_run=True)
    s = a.settings
    ok = True

    def row(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"  [{'ok' if good else '!!'}] {label}{(': ' + detail) if detail else ''}")

    print("Tools")
    for tool in (s.runtimes.ffmpeg, s.runtimes.ffprobe, s.runtimes.lms_cli, "llama-server", "mflux-generate-qwen", "parakeet-mlx"):
        row(tool, shutil.which(tool) is not None, "" if shutil.which(tool) else "not on PATH")
    print("Servers")
    for name, url in (("LM Studio", s.runtimes.lmstudio_url + "/v1/models"), ("ComfyUI", s.runtimes.comfyui_url + "/system_stats"), ("ACE-Step", s.runtimes.acestep_url)):
        try:
            r = httpx.get(url, timeout=3)
            row(name, r.status_code < 500, url)
        except httpx.HTTPError:
            row(name, False, f"{url} not reachable")
    print("Models for profile", s.hardware.profile, "(one model at a time)")
    for task, m in a.models.items():
        print(f"  - {task:14s} {m.name:24s} {m.memory_gb:5.1f} GB  {m.precision:28s} {m.runtime:14s} {m.license}")
    heaviest = max(m.memory_gb for m in a.models.values())
    row("memory plan", heaviest <= s.hardware.gpu_budget_gb, f"heaviest single model {heaviest} GB vs GPU budget {s.hardware.gpu_budget_gb} GB (raise with: sudo sysctl iogpu.wired_limit_mb=57344)")
    chosen = a.brain_choice.chosen_name()
    row("brain choice", chosen is not None, f"{chosen} (benchmarked on this Mac)" if chosen else "not benchmarked yet: run `agency doctor --benchmark` (loads each brain candidate once, a few minutes)")
    if getattr(args, "benchmark", False):
        print("Benchmarking brain candidates (one at a time)...")
        live = Agency(dry_run=False)
        out = live.benchmark_brains()
        for r in out["results"]:
            print(f"  - {r['model']:24s} {'ok' if r.get('ok') else 'FAILED'}  {r.get('tokens_per_s', '-')} tok/s  {r.get('error', '')[:120]}")
        print(f"  chosen brain: {out['chosen']}")
    print("Workflows")
    for wf in ("image.json", "image-edit.json", "video.json", "avatar.json"):
        p = ROOT / "workflows" / wf
        print(f"  [{'ok' if p.exists() else '--'}] {wf}{'' if p.exists() else ' (optional: CLI template or dry run used instead)'}")
    print("Platforms")
    for n, p in a.platforms.items():
        print(f"  [{'ok' if p.configured() else '--'}] {n:10s} {'connected' if p.configured() else 'missing ' + ', '.join(p.missing_env())}")
    print("Hard guarantees: payments blocked, account creation blocked, mass actions blocked")
    print(f"Mode: {'DRY RUN (set dry_run: false in agency.yaml to go live)' if s.dry_run else 'LIVE'}")
    return 0 if ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    import uvicorn

    from agency.app import Agency
    from agency.panel.app import create_app
    from agency.scheduler.runner import build

    a = Agency(dry_run=args.dry_run or None)
    app = create_app(a)
    sched = build(a)
    if not args.no_schedule:
        sched.start()
        a.note("scheduler started")
    a.note(f"panel at http://{a.settings.panel_host}:{a.settings.panel_port}")
    uvicorn.run(app, host=a.settings.panel_host, port=a.settings.panel_port, log_level="warning")
    return 0


def cmd_cycle(args: argparse.Namespace) -> int:
    from agency.app import Agency

    a = Agency(dry_run=True if args.dry_run else None)
    out = a.director.daily_cycle()
    print(json.dumps({k: v for k, v in out.items() if k != "opportunities"}, indent=2, default=str))
    return 0


def cmd_video(args: argparse.Namespace) -> int:
    from agency.app import Agency

    a = Agency(dry_run=True if args.dry_run else None)
    ids = a.director.produce_video(args.topic, args.angle, link=args.link, target_seconds=args.seconds)
    for cid in ids:
        row = a.store.get_content(cid)
        print(f"#{cid} {row['kind']} {row['platform']} -> {row['status']}")
    return 0


def cmd_post(args: argparse.Namespace) -> int:
    from agency.app import Agency

    a = Agency(dry_run=True if args.dry_run else None)
    cid = a.director.produce_post(args.platform, args.topic, args.angle, link=args.link, with_image=args.image)
    row = a.store.get_content(cid)
    print(f"#{cid} {row['platform']} -> {row['status']}\n\n{row['body']}")
    return 0


def cmd_chrome_login(args: argparse.Namespace) -> int:
    """Open the agent's own Chrome on the login pages so you can sign in once (cookies stay in state/chrome-profile)."""
    from agency.app import Agency

    a = Agency(dry_run=True)
    a.operator.dry_run = False
    a.operator.headless = False
    opened = a.operator.open_logins(args.platforms or None)
    print("Opened:", ", ".join(opened) or "nothing (no recipes matched)")
    print("Log in on each tab, then press Enter here to close the browser. Your logins are kept for the operator.")
    try:
        input()
    finally:
        a.operator.close()
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    from agency.app import Agency

    a = Agency(dry_run=True)
    for c in a.store.list_content(status="queued"):
        print(f"#{c['id']:4d} {c['kind']:8s} {c['platform']:10s} {(c['title'] or c['body'])[:70]}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    from agency.app import Agency

    a = Agency()
    d = a.director.approve(args.id)
    print(d.verdict.value, d.reason)
    return 0 if d.allowed else 1


def cmd_toggle(args: argparse.Namespace) -> int:
    from agency.settings import Toggles

    t = Toggles()
    if args.name == "list":
        for k, v in t.all().items():
            print(f"{k:28s} {'on' if v else 'off'}")
        return 0
    t.set(args.name, args.value.lower() in {"on", "1", "true"})
    print(f"{args.name} -> {t.get(args.name)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="agency", description="Local, token-free AI marketing agency")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create config/agency.yaml and .env").set_defaults(fn=cmd_init)
    p = sub.add_parser("doctor", help="check tools, servers, models and platforms")
    p.add_argument("--benchmark", action="store_true", help="load each brain candidate once and pick the strongest that runs well")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("run", help="start the control panel and the scheduler")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-schedule", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("cycle", help="run one daily cycle now")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_cycle)
    p = sub.add_parser("video", help="produce one video (and its shorts)")
    p.add_argument("--topic", required=True)
    p.add_argument("--angle", default="practical, verified, plain English")
    p.add_argument("--link", default="")
    p.add_argument("--seconds", type=int, default=180)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_video)
    p = sub.add_parser("post", help="write one post")
    p.add_argument("--platform", default="bluesky")
    p.add_argument("--topic", required=True)
    p.add_argument("--angle", default="practical, verified")
    p.add_argument("--link", default="")
    p.add_argument("--image", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_post)
    sub.add_parser("queue", help="list items waiting for approval").set_defaults(fn=cmd_queue)
    p = sub.add_parser("chrome-login", help="open the agent's Chrome on the platforms' login pages (log in once)")
    p.add_argument("platforms", nargs="*", help="recipe names, e.g. x medium substack")
    p.set_defaults(fn=cmd_chrome_login)
    p = sub.add_parser("approve", help="approve and publish a queued item")
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("toggle", help="flip a switch: agency toggle publishing on | agency toggle list")
    p.add_argument("name")
    p.add_argument("value", nargs="?", default="on")
    p.set_defaults(fn=cmd_toggle)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
