"""The browser operator.

For platforms without a usable API (or with a paid one), the operator opens the agent's
own Chrome profile (where *you* logged in once), fills the post or comment following a
recipe, takes a screenshot, and stops.  It clicks Publish only after your approval in
the dashboard.  One action at a time, at a human pace, never through a CAPTCHA, never
creating accounts.  Recipes are data (``recipes/*.yaml``): when a platform changes its
page, the operator leaves what it managed to fill and asks you for the last click.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RECIPES_DIR = Path(__file__).parent / "recipes"


class OperatorError(RuntimeError):
    pass


@dataclass
class Recipe:
    platform: str
    label: str
    kinds: list[str]
    login_url: str
    compose_url: str
    steps: list[dict[str, Any]]
    publish: dict[str, Any]
    comment: dict[str, Any] | None = None
    result_url_pattern: str = ""
    notes: str = ""

    @classmethod
    def load(cls, path: Path) -> "Recipe":
        d = yaml.safe_load(path.read_text()) or {}
        return cls(platform=d["platform"], label=d.get("label", d["platform"]), kinds=list(d.get("kinds", [])), login_url=d.get("login_url", ""), compose_url=d.get("compose_url", ""), steps=list(d.get("steps", [])), publish=dict(d.get("publish", {})), comment=d.get("comment"), result_url_pattern=d.get("result_url_pattern", ""), notes=d.get("notes", ""))


def load_recipes(directory: Path = RECIPES_DIR) -> dict[str, Recipe]:
    return {r.platform: r for r in (Recipe.load(p) for p in sorted(directory.glob("*.yaml")))}


@dataclass
class BrowserTask:
    id: int
    platform: str
    kind: str                     # publish | comment
    payload: dict[str, Any]
    status: str = "preparing"     # preparing | ready | needs_your_click | published | failed | cancelled
    screenshot: str = ""
    url: str = ""
    error: str = ""
    log: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: dt.datetime.now().isoformat(timespec="seconds"))


class BrowserOperator:
    def __init__(self, profile_dir: Path, screenshots_dir: Path, *, headless: bool = False, executable_path: str | None = None, channel: str | None = "chrome", dry_run: bool = False, pace_s: float = 0.6, recipes: dict[str, Recipe] | None = None, on_event=None):
        self.profile_dir, self.screenshots_dir = profile_dir, screenshots_dir
        self.headless, self.executable_path, self.channel, self.dry_run, self.pace_s = headless, executable_path, channel, dry_run, pace_s
        self.recipes = recipes or load_recipes()
        self.on_event = on_event or (lambda kind, text: None)
        self._pw = None
        self._ctx = None
        self._pages: dict[int, Any] = {}
        self._tasks: dict[int, BrowserTask] = {}
        self._next = 1
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ browser lifecycle
    def _context(self):
        if self._ctx is not None:
            return self._ctx
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        kw: dict[str, Any] = {"headless": self.headless, "viewport": {"width": 1280, "height": 900}, "args": ["--disable-blink-features=AutomationControlled"]}
        if self.executable_path:
            kw["executable_path"] = self.executable_path
        elif self.channel:
            kw["channel"] = self.channel
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(str(self.profile_dir), **kw)
        except Exception as e:  # noqa: BLE001
            if "channel" in kw:
                kw.pop("channel")
                self._ctx = self._pw.chromium.launch_persistent_context(str(self.profile_dir), **kw)
            else:
                raise OperatorError(f"could not start the browser: {e}") from e
        return self._ctx

    def close(self) -> None:
        with self._lock:
            for p in self._pages.values():
                try:
                    p.close()
                except Exception:  # noqa: BLE001
                    pass
            self._pages.clear()
            if self._ctx is not None:
                self._ctx.close()
                self._ctx = None
            if self._pw is not None:
                self._pw.stop()
                self._pw = None

    def open_logins(self, platforms: list[str] | None = None) -> list[str]:
        """Open the login page of each platform in the agent's Chrome so you can sign in once."""
        ctx = self._context()
        opened = []
        for key, r in self.recipes.items():
            if platforms and key not in platforms:
                continue
            if r.login_url:
                ctx.new_page().goto(r.login_url)
                opened.append(r.login_url)
        return opened

    # ------------------------------------------------------------------ tasks
    def tasks(self) -> list[BrowserTask]:
        with self._lock:
            return sorted(self._tasks.values(), key=lambda t: t.id, reverse=True)

    def task(self, tid: int) -> BrowserTask | None:
        return self._tasks.get(tid)

    def prepare(self, platform: str, kind: str, payload: dict[str, Any]) -> BrowserTask:
        """Fill the page and stop before Publish. ``payload``: text, title, body, media (paths), post_url (comments), variables."""
        recipe = self.recipes.get(platform)
        if not recipe:
            raise OperatorError(f"no browser recipe for {platform}")
        with self._lock:
            t = BrowserTask(self._next, platform, kind, payload)
            self._next += 1
            self._tasks[t.id] = t
        self.on_event("operator", f"preparing {kind} on {recipe.label}")
        if self.dry_run:
            t.status, t.screenshot = "ready", ""
            t.log.append("dry run: page not opened")
            return t
        try:
            ctx = self._context()
            page = ctx.new_page()
            self._pages[t.id] = page
            if kind == "comment":
                if not recipe.comment:
                    raise OperatorError(f"{recipe.label}: comments are not supported by the recipe")
                page.goto(payload["post_url"], wait_until="domcontentloaded")
                steps = recipe.comment.get("steps", [])
            else:
                page.goto(self._compose_url(recipe, payload), wait_until="domcontentloaded")
                steps = recipe.steps
            filled_all = self._run_steps(page, steps, payload, t)
            t.screenshot = self._shot(page, t, "ready")
            t.status = "ready" if filled_all else "needs_your_click"
        except Exception as e:  # noqa: BLE001
            t.status, t.error = "failed", str(e)[:300]
            t.log.append(f"failed: {e}")
            try:
                t.screenshot = self._shot(self._pages[t.id], t, "failed")
            except Exception:  # noqa: BLE001
                pass
        return t

    def publish(self, tid: int) -> BrowserTask:
        """Click Publish on a prepared task (only ever called after a human approval)."""
        t = self._tasks.get(tid)
        if not t:
            raise OperatorError("no such task")
        if t.status not in ("ready", "needs_your_click"):
            raise OperatorError(f"task is {t.status}")
        recipe = self.recipes[t.platform]
        self.on_event("operator", f"publishing on {recipe.label} (approved)")
        if self.dry_run:
            t.status, t.url = "published", f"dry-run://{t.platform}"
            return t
        page = self._pages.get(tid)
        if page is None:
            t.status, t.error = "failed", "page is gone (browser restarted?)"
            return t
        pub = (recipe.comment or {}).get("publish") if t.kind == "comment" else recipe.publish
        try:
            sel = (pub or {}).get("selector", "")
            if sel:
                page.locator(sel).first.click(timeout=15000)
                time.sleep(self.pace_s * 3)
            if (pub or {}).get("needs_dialog"):
                t.status = "needs_your_click"
                t.log.append("the platform opened its publish dialog: finish it in the browser window")
                t.screenshot = self._shot(page, t, "dialog")
                return t
            t.url = self._find_result_url(page, recipe)
            t.status = "published"
            t.screenshot = self._shot(page, t, "published")
        except Exception as e:  # noqa: BLE001
            t.status, t.error = "needs_your_click", str(e)[:300]
            t.log.append(f"publish click failed, left the page open for you: {e}")
        finally:
            if t.status == "published":
                self._close_page(tid)
        return t

    def cancel(self, tid: int) -> None:
        t = self._tasks.get(tid)
        if t:
            t.status = "cancelled"
            self._close_page(tid)

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _compose_url(recipe: Recipe, payload: dict[str, Any]) -> str:
        url = payload.get("compose_url") or recipe.compose_url
        for k, v in (payload.get("variables") or {}).items():
            url = url.replace("{" + k + "}", str(v))
        return url

    def _run_steps(self, page, steps: list[dict[str, Any]], payload: dict[str, Any], t: BrowserTask) -> bool:
        ok = True
        for st in steps:
            action = st.get("action")
            sel = st.get("selector", "")
            value = self._value(st.get("value"), payload)
            try:
                if action == "wait":
                    page.locator(sel).first.wait_for(timeout=20000)
                elif action == "fill":
                    page.locator(sel).first.fill(value or "", timeout=15000)
                elif action == "fill_editor":
                    loc = page.locator(sel).first
                    loc.click(timeout=15000)
                    page.keyboard.type(value or "", delay=8)
                elif action == "type":
                    loc = page.locator(sel).first
                    loc.click(timeout=15000)
                    page.keyboard.type(value or "", delay=8)
                elif action == "type_markdown":
                    if sel:
                        page.locator(sel).first.click(timeout=15000)
                    for para in (value or "").split("\n\n"):
                        page.keyboard.type(para.strip("\n"), delay=4)
                        page.keyboard.press("Enter")
                        page.keyboard.press("Enter")
                elif action == "press":
                    page.keyboard.press(st.get("key", "Enter"))
                elif action == "upload":
                    files = [str(p) for p in (payload.get("media") or []) if Path(str(p)).exists()]
                    if files:
                        page.locator(sel).first.set_input_files(files[:4], timeout=15000)
                elif action == "click":
                    page.locator(sel).first.click(timeout=15000)
                t.log.append(f"{action} ok")
                time.sleep(self.pace_s)
            except Exception as e:  # noqa: BLE001
                t.log.append(f"{action} {sel[:40]} failed: {str(e)[:120]}")
                if not st.get("optional"):
                    ok = False
        return ok

    @staticmethod
    def _value(key: str | None, payload: dict[str, Any]) -> str | None:
        if key is None:
            return None
        if key == "text":
            text = payload.get("text", "")
            link = payload.get("link", "")
            return text if (not link or link in text) else f"{text}\n{link}"
        return payload.get(key, "") if key != "media" else None

    def _shot(self, page, t: BrowserTask, tag: str) -> str:
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        path = self.screenshots_dir / f"task-{t.id}-{tag}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path)

    def _find_result_url(self, page, recipe: Recipe) -> str:
        if not recipe.result_url_pattern:
            return page.url
        deadline = time.time() + 10
        pat = re.compile(recipe.result_url_pattern)
        while time.time() < deadline:
            if pat.search(page.url):
                return page.url
            for a in page.locator("a[href]").all()[:200]:
                href = a.get_attribute("href") or ""
                if pat.search(href):
                    return href if href.startswith("http") else page.url
            time.sleep(0.5)
        return page.url

    def _close_page(self, tid: int) -> None:
        p = self._pages.pop(tid, None)
        if p is not None:
            try:
                p.close()
            except Exception:  # noqa: BLE001
                pass


def default_executable() -> str | None:
    """Playwright's own Chromium when Chrome is not installed (tests, Linux)."""
    env = os.environ.get("AGENCY_CHROMIUM")
    if env and Path(env).exists():
        return env
    for cand in ("/opt/pw-browsers/chromium",):
        if Path(cand).exists():
            return cand
    return None
