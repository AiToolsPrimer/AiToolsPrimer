import os
from pathlib import Path

import pytest

from agency.browser.operator import BrowserOperator, default_executable, load_recipes

FIXTURE = (Path(__file__).parent / "fixtures" / "x_compose.html").resolve()
CHROMIUM = default_executable()


def test_recipes_load():
    r = load_recipes()
    assert {"x", "medium", "substack", "linkedin_articles", "blogger", "dailymotion", "tumblr_browser"} <= set(r)
    assert r["x"].publish["selector"] and r["x"].comment and r["medium"].publish.get("needs_dialog")


@pytest.mark.skipif(not CHROMIUM, reason="no Chromium available")
def test_operator_fills_and_publishes_only_on_click(tmp_path: Path):
    op = BrowserOperator(tmp_path / "profile", tmp_path / "shots", headless=True, executable_path=CHROMIUM, channel=None, dry_run=False, pace_s=0.05)
    try:
        t = op.prepare("x", "publish", {"content_id": 1, "text": "We tested five free PDF editors.", "link": "https://aitoolsprimer.com/pdf", "media": [], "compose_url": FIXTURE.as_uri()})
        assert t.status == "ready", t.log
        assert Path(t.screenshot).exists()
        page = op._pages[t.id]
        assert "five free PDF editors" in page.inner_text('[data-testid="tweetTextarea_0"]')
        assert page.locator("#result a").count() == 0           # nothing published yet
        t = op.publish(t.id)
        assert t.status == "published" and t.url.startswith("https://x.com/aitoolsprimer/status/")
        assert t.id not in op._pages
    finally:
        op.close()


def test_dry_run_operator(tmp_path: Path):
    op = BrowserOperator(tmp_path / "profile", tmp_path / "shots", headless=True, dry_run=True)
    t = op.prepare("x", "publish", {"text": "hi"})
    assert t.status == "ready"
    assert op.publish(t.id).status == "published"
    with pytest.raises(Exception):
        op.prepare("nowhere", "publish", {})


def test_director_dispatches_by_mode(agency):
    # X defaults to browser: approval -> prepared in the browser (dry-run operator) -> waits for the click
    cid = agency.director.produce_post("x", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf")
    row = agency.store.get_content(cid)
    assert row["status"] == "queued"
    d = agency.director.approve(cid)
    row = agency.store.get_content(cid)
    assert d.allowed and row["status"] == "ready_to_click" and row["meta"]["browser_task"]
    d = agency.director.browser_publish(row["meta"]["browser_task"])
    row = agency.store.get_content(cid)
    assert d.allowed and row["status"] == "published" and row["remote_url"].startswith("dry-run://x")
    # intent mode: nothing leaves, a pre-filled link is produced
    agency.prefs.set("mode:x", "intent")
    cid2 = agency.director.produce_post("x", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf")
    agency.director.approve(cid2)
    row2 = agency.store.get_content(cid2)
    assert row2["status"] == "manual" and row2["meta"]["intent_url"].startswith("https://x.com/intent/post?text=")
    # off mode: rejected at the gate
    agency.prefs.set("mode:x", "off")
    cid3 = agency.director.produce_post("x", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf")
    assert agency.store.get_content(cid3)["status"] == "rejected"


def test_browser_actions_count_against_the_daily_cap(agency):
    agency.settings.limits.browser_actions_per_day = 1
    cid = agency.director.produce_post("x", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf")
    agency.director.approve(cid)
    tid = agency.store.get_content(cid)["meta"]["browser_task"]
    assert agency.director.browser_publish(tid).allowed
    cid2 = agency.director.produce_post("x", "free PDF editors", "again", link="https://aitoolsprimer.com/pdf")
    d = agency.director.approve(cid2)          # the cap holds the next one before the browser is even opened
    assert not d.allowed and "daily browser action limit" in d.reason
    assert agency.store.get_content(cid2)["status"] == "queued"


def test_platform_count_and_modes(agency):
    assert len(agency.platforms) == 26
    assert agency.mode_for("medium") == "browser" and agency.mode_for("flipboard") == "intent" and agency.mode_for("quora") == "manual"
    assert callable(agency.platforms["flipboard"].intent_url)  # intent builder exists


def test_podcast_and_indexnow(agency):
    cid = agency.director.produce_article("devto", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf")
    pods = [c for c in agency.store.list_content(limit=50) if c["kind"] == "podcast"]
    assert pods and pods[0]["status"] == "manual"
    feed = Path(pods[0]["meta"]["feed"])
    assert feed.exists() and "<enclosure" in feed.read_text()
    assert agency.indexnow.submit(["https://aitoolsprimer.com/new-guide", "https://elsewhere.com/x"])["submitted"] == 1
    assert agency.strategist.push_new_urls(["https://aitoolsprimer.com/a", "https://aitoolsprimer.com/b"]) == 2
    assert agency.strategist.push_new_urls(["https://aitoolsprimer.com/a"]) == 0


def test_operator_page(agency):
    from fastapi.testclient import TestClient

    from agency.panel.app import create_app

    c = TestClient(create_app(agency))
    assert c.get("/operator").status_code == 200
