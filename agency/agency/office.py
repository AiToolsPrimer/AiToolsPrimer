"""The office: who is doing what, right now.

Every agent reports its activity here (begin / step / end), the model host reports
loads and unloads, the director reports phases.  The dashboard reads the board and
streams the event log live (Server-Sent Events).  Nothing here touches the outside
world; it is the agency's own heartbeat."""
from __future__ import annotations

import datetime as dt
import json
import queue
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

DESKS: dict[str, dict[str, str]] = {
    # key: (display name, role, what it does) — the names are deliberately plain
    "director":   {"name": "Director",    "role": "plans the day, reviews every draft, decides what goes out"},
    "strategist": {"name": "Strategist",  "role": "reads the site and the trends, proposes angles"},
    "writer":     {"name": "Writer",      "role": "posts, threads, articles, scripts, captions, replies"},
    "second":     {"name": "Second pen",  "role": "an independent draft from the other model"},
    "factcheck":  {"name": "Fact checker", "role": "verifies every sentence against the guide"},
    "art":        {"name": "Art director", "role": "images, covers, thumbnails, carousels"},
    "video":      {"name": "Video producer", "role": "scenes, clips, voice, music, subtitles, shorts"},
    "voice":      {"name": "Voice",       "role": "narration and presenter audio"},
    "safety":     {"name": "Safety",      "role": "brand rules, labels, guard model"},
    "community":  {"name": "Community",   "role": "replies under our posts, conversations"},
    "network":    {"name": "Network",     "role": "affine sites and accounts, comments to approve"},
    "scout":      {"name": "Scout",       "role": "new platforms and sign-up kits"},
    "pr":         {"name": "PR",          "role": "journalist requests, mentions, broken links, pitches"},
    "mail":       {"name": "Mail",        "role": "reads the inbox, drafts replies"},
    "analyst":    {"name": "Analyst",     "role": "metrics, lessons, cadence"},
    "operator":   {"name": "Browser operator", "role": "fills posts in Chrome, you click Publish"},
    "models":     {"name": "Model host",  "role": "one model in memory at a time"},
}


@dataclass
class Desk:
    key: str
    status: str = "idle"           # idle | working | waiting | error
    task: str = ""
    step: str = ""
    step_index: int = 0
    step_count: int = 0
    model: str = ""
    started_at: float = 0.0
    last_result: str = ""
    done_today: int = 0
    errors_today: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def view(self) -> dict[str, Any]:
        meta = DESKS.get(self.key, {"name": self.key, "role": ""})
        return {
            "key": self.key, "name": meta["name"], "role": meta["role"], "status": self.status, "task": self.task, "step": self.step,
            "step_index": self.step_index, "step_count": self.step_count, "model": self.model,
            "elapsed_s": round(time.time() - self.started_at) if self.status == "working" and self.started_at else 0,
            "last_result": self.last_result, "done_today": self.done_today, "errors_today": self.errors_today,
            "history": self.history[-8:],
        }


class Office:
    def __init__(self, max_events: int = 2000):
        self._lock = threading.RLock()
        self.desks: dict[str, Desk] = {k: Desk(k) for k in DESKS}
        self.events: list[dict[str, Any]] = []
        self.max_events = max_events
        self._subscribers: list[queue.Queue] = []
        self.resident_model: str = ""
        self.phase: str = ""
        self._day = dt.date.today()

    # ------------------------------------------------------------------ reporting
    def _roll_day(self) -> None:
        if dt.date.today() != self._day:
            self._day = dt.date.today()
            for d in self.desks.values():
                d.done_today = d.errors_today = 0

    def desk(self, key: str) -> Desk:
        with self._lock:
            if key not in self.desks:
                self.desks[key] = Desk(key)
            return self.desks[key]

    def begin(self, key: str, task: str, steps: int = 0, model: str = "") -> None:
        with self._lock:
            self._roll_day()
            d = self.desk(key)
            d.status, d.task, d.step, d.step_index, d.step_count, d.started_at = "working", task, "", 0, steps, time.time()
            d.model = model or self.resident_model
        self.emit("begin", key, task)

    def step(self, key: str, step: str, index: int | None = None, count: int | None = None) -> None:
        with self._lock:
            d = self.desk(key)
            d.step = step
            if index is not None:
                d.step_index = index
            if count is not None:
                d.step_count = count
            d.model = self.resident_model or d.model
        self.emit("step", key, step)

    def end(self, key: str, result: str = "", ok: bool = True) -> None:
        with self._lock:
            d = self.desk(key)
            elapsed = round(time.time() - d.started_at) if d.started_at else 0
            d.status = "idle" if ok else "error"
            d.last_result = result[:300]
            if ok:
                d.done_today += 1
            else:
                d.errors_today += 1
            d.history.append({"at": _now(), "task": d.task, "result": result[:160], "ok": ok, "elapsed_s": elapsed})
            d.history = d.history[-50:]
            d.task, d.step, d.step_index, d.step_count = "", "", 0, 0
        self.emit("end" if ok else "error", key, result)

    def waiting(self, key: str, what: str) -> None:
        with self._lock:
            d = self.desk(key)
            d.status, d.step = "waiting", what
        self.emit("waiting", key, what)

    @contextmanager
    def working(self, key: str, task: str, steps: int = 0) -> Iterator[None]:
        self.begin(key, task, steps)
        try:
            yield
        except Exception as e:  # noqa: BLE001
            self.end(key, f"error: {e}", ok=False)
            raise
        else:
            self.end(key, "done")

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self.emit("phase", "director", phase)

    def model_event(self, e: dict[str, Any]) -> None:
        kind = e.get("kind", "")
        if kind == "model.loaded":
            self.resident_model = e.get("model", "")
            self.desk("models").status, self.desk("models").task = "working", f"{e.get('model')} resident ({e.get('memory_gb')} GB)"
        elif kind == "model.unloaded":
            self.resident_model = ""
            self.desk("models").status, self.desk("models").task = "idle", ""
        elif kind == "job.start":
            self.desk("models").status, self.desk("models").task = "working", f"{e.get('model')} job"
        elif kind in ("job.done", "job.failed"):
            self.desk("models").status, self.desk("models").task = "idle", ""
        self.emit("model", "models", f"{kind}: {e.get('model')}" + (f" ({e.get('reason')})" if e.get("reason") else ""))

    # ------------------------------------------------------------------ events
    def emit(self, kind: str, desk: str, text: str) -> None:
        e = {"at": _now(), "kind": kind, "desk": desk, "name": DESKS.get(desk, {}).get("name", desk), "text": str(text)[:400]}
        with self._lock:
            self.events.append(e)
            self.events = self.events[-self.max_events:]
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(e)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def sse(self, q: queue.Queue, heartbeat: float = 15.0) -> Iterator[str]:
        """Generator for a text/event-stream response."""
        yield "retry: 3000\n\n"
        while True:
            try:
                e = q.get(timeout=heartbeat)
                yield f"data: {json.dumps(e)}\n\n"
            except queue.Empty:
                yield ": keep-alive\n\n"

    # ------------------------------------------------------------------ views
    def board(self) -> dict[str, Any]:
        with self._lock:
            return {"phase": self.phase, "resident_model": self.resident_model, "desks": [d.view() for d in self.desks.values()], "events": self.events[-60:]}


def _now() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")
