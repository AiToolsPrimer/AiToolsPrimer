import json
import queue

from agency.office import Office


def test_office_tracks_desks_and_events():
    o = Office()
    with o.working("writer", "bluesky post", steps=2):
        o.step("writer", "drafting", 1, 2)
        v = o.desk("writer").view()
        assert v["status"] == "working" and v["step"] == "drafting" and v["step_index"] == 1
    v = o.desk("writer").view()
    assert v["status"] == "idle" and v["done_today"] == 1 and v["history"][-1]["ok"]
    try:
        with o.working("art", "image"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert o.desk("art").view()["status"] == "error" and o.desk("art").errors_today == 1
    kinds = [e["kind"] for e in o.events]
    assert "begin" in kinds and "step" in kinds and "end" in kinds and "error" in kinds


def test_office_model_events_and_sse():
    o = Office()
    q = o.subscribe()
    o.model_event({"kind": "model.loaded", "model": "Qwen3.8-Flash-Next", "memory_gb": 46})
    assert o.resident_model == "Qwen3.8-Flash-Next" and o.board()["resident_model"]
    gen = o.sse(q, heartbeat=0.1)
    assert next(gen).startswith("retry")
    data = next(gen)
    assert data.startswith("data: ") and json.loads(data[6:])["desk"] == "models"
    assert next(gen).startswith(": keep-alive")
    o.unsubscribe(q)
    o.model_event({"kind": "model.unloaded", "model": "Qwen3.8-Flash-Next", "memory_gb": 46})
    assert o.resident_model == ""


def test_agents_report_to_the_office(agency):
    cid = agency.director.produce_post("bluesky", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf", with_image=True)
    board = agency.office.board()
    desks = {d["key"]: d for d in board["desks"]}
    assert desks["writer"]["done_today"] >= 1 and desks["factcheck"]["done_today"] >= 1 and desks["art"]["done_today"] >= 1
    assert desks["director"]["done_today"] >= 1
    names = {e["name"] for e in board["events"]}
    assert "Writer" in names and "Fact checker" in names
    assert agency.store.get_content(cid)["status"] == "queued"


def test_panel_pages_and_live_endpoints(agency):
    from fastapi.testclient import TestClient

    from agency.panel.app import create_app

    agency.director.produce_post("linkedin", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf")
    c = TestClient(create_app(agency))
    for path in ("/", "/queue", "/content", "/content/1", "/assets", "/platforms", "/knowledge", "/knowledge?card=x", "/knowledge?card=virality", "/learning", "/models", "/scout", "/logs", "/api/status", "/api/office"):
        r = c.get(path)
        assert r.status_code == 200, path
    assert c.get("/content/999").status_code == 404
    r = c.post("/mode", data={"platform": "x", "mode": "intent"}, follow_redirects=False)
    assert r.status_code == 303 and agency.mode_for("x") == "intent"
    assert c.post("/mode", data={"platform": "x", "mode": "api"}).status_code == 400
    # the SSE route exists; the stream itself is covered by test_office_model_events_and_sse (a TestClient stream never ends)
    assert any(getattr(r, "path", "") == "/events" for r in c.app.routes)
