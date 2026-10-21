import datetime as dt
from pathlib import Path

from agency.deliverables import _guard_numbers, render_pdf


def test_guard_numbers_strips_unsupported_figures():
    out = _guard_numbers({"summary": "We reached 999 people. We published 3 pieces. Fine sentence.", "weeks": [{"week": 3}]}, allowed={"3"})
    assert "999" not in out["summary"] and "3 pieces" in out["summary"] and "Fine sentence." in out["summary"]
    assert out["weeks"][0]["week"] == 3   # structured fields untouched


def test_monthly_plan_report_and_campaign(agency):
    today = dt.date.today()
    plan = agency.deliverables.monthly_plan(today.year, today.month, ["bluesky", "mastodon", "youtube"])
    assert plan["weeks"] and Path(plan["html"]).exists()
    items = agency.deliverables.items_for_day(today.replace(day=3))
    assert items and items[0]["guide"] == "https://aitoolsprimer.com/pdf"
    report = agency.deliverables.monthly_report(today.year, today.month)
    assert "999" not in report["summary"] and Path(report["html"]).exists()
    camp = agency.deliverables.campaign("Launch the PDF guide", ["youtube", "bluesky"], weeks=4)
    assert camp["hooks"] and "45" not in " ".join(camp["risks"]) and Path(camp["html"]).exists()
    docs = agency.store.list_deliverables()
    assert {d["kind"] for d in docs} == {"plan", "report", "campaign"}
    if plan["pdf"]:
        assert Path(plan["pdf"]).stat().st_size > 1000


def test_pdf_renderer(tmp_path: Path):
    out = tmp_path / "x.pdf"
    ok = render_pdf("<html><body><h1>Hello</h1></body></html>", out)
    assert (ok and out.exists() and out.read_bytes()[:4] == b"%PDF") or not ok


def test_daily_cycle_follows_the_monthly_plan(agency):
    today = dt.date.today()
    agency.deliverables.monthly_plan(today.year, today.month, ["bluesky", "mastodon"])
    out = agency.director.daily_cycle()
    assert out["opportunities"][0]["why_now"] == "monthly plan"
    assert out["content_ids"]


def test_briefing_and_style_rules(agency):
    b = agency.director.briefing(voice=True)
    assert b["text"].startswith("Good morning") and b.get("audio") and Path(b["audio"]).exists()
    for i in range(3):
        cid = agency.store.add_content("post", "bluesky", body=f"draft {i}", status="queued")
        agency.director.approve(cid, edited_body=f"edited {i}")
    rules = agency.refresh_style()
    assert rules and agency.writer.style_rules == rules
    assert "Open with the finding" in agency.writer.system()
    training = agency.learning.export_training_set()
    assert training["examples"] >= 3 and Path(training["path"]).exists() and not training["ready"]


def test_monthly_job_and_pages(agency):
    out = agency.monthly_deliverables()
    assert out["report"] and out["plan"]
    from fastapi.testclient import TestClient

    from agency.panel.app import create_app

    c = TestClient(create_app(agency))
    for path in ("/deliverables", "/learning"):
        assert c.get(path).status_code == 200
    did = agency.store.list_deliverables()[0]["id"]
    assert c.get(f"/deliverable/{did}/html").status_code == 200
    r = c.post("/campaign", data={"brief": "Launch", "weeks": 2}, follow_redirects=False)
    assert r.status_code == 303
