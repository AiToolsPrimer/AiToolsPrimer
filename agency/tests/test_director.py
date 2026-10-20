from agency.safety.policy import Verdict


def test_daily_cycle_dry_run_fills_queue(agency):
    out = agency.director.daily_cycle()
    rows = agency.store.list_content()
    kinds = {r["kind"] for r in rows}
    assert {"post", "video", "short"} <= kinds
    assert all(r["status"] == "queued" for r in rows), [(r["kind"], r["status"], r["meta"].get("reject_reason")) for r in rows]
    assert out["content_ids"]
    # a post has an image attached and a video has its asset
    post = next(r for r in rows if r["kind"] == "post")
    assert post["assets"] and agency.store.get_asset(post["assets"][0])["kind"] == "image"
    video = next(r for r in rows if r["kind"] == "video")
    assert video["meta"]["seconds"] <= 240


def test_approve_publishes_in_dry_run(agency):
    cid = agency.director.produce_post("bluesky", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf")
    assert agency.store.get_content(cid)["status"] == "queued"
    d = agency.director.approve(cid)
    assert d.allowed
    row = agency.store.get_content(cid)
    assert row["status"] == "published" and row["meta"]["dry_run"] is True


def test_publishing_on_without_approval_publishes_directly(agency):
    agency.toggles.set("publishing", True)
    agency.toggles.set("approval_required", False)
    cid = agency.director.produce_post("mastodon", "free PDF editors", "tested")
    assert agency.store.get_content(cid)["status"] == "published"


def test_safety_rejects_banned_claims(agency):
    agency.toggles.set("publishing", True)
    agency.toggles.set("approval_required", False)
    cid = agency.store.add_content("post", "bluesky", body="This is the #1 tool, guaranteed.", status="draft")
    d = agency.director._gate(cid)
    assert d.verdict is Verdict.DENY
    assert agency.store.get_content(cid)["status"] == "rejected"


def test_safety_rejects_external_links_and_placeholders(agency):
    assert not agency.safety.check("Buy it at https://evil.example.com").ok
    assert not agency.safety.check("It costs [price to verify] per month").ok
    assert not agency.safety.check("It is 45% faster than before").ok
    assert agency.safety.check("It is 45% faster than before", facts_supplied=True).ok
    assert agency.safety.check("Read the guide: https://aitoolsprimer.com/pdf").ok


def test_video_length_up_to_four_minutes(agency):
    ids = agency.director.produce_video("free PDF editors", "tested", target_seconds=240)
    video = next(agency.store.get_content(i) for i in ids if agency.store.get_content(i)["kind"] == "video")
    assert 100 <= video["meta"]["seconds"] <= 240
    shorts = [agency.store.get_content(i) for i in ids if agency.store.get_content(i)["kind"] == "short"]
    assert shorts and all(s["platform"] in {"youtube", "tiktok", "instagram"} for s in shorts)


def test_scout_never_registers_but_prepares_kit(agency, monkeypatch):
    monkeypatch.setattr(agency.scout, "search", lambda q, limit=15: [{"url": "https://lemmy.world/about", "title": "Lemmy"}])
    found = agency.director.scout_cycle()
    assert found and found[0]["name"] == "Lemmy"
    assert agency.store.list_scout()[0]["status"] == "found"
    agency.toggles.set("prepare_signup_kits", True)
    kit = agency.scout.prepare_kit(found[0]["id"])
    assert kit["handle"] == "aitoolsprimer" and "avatar_asset" in kit
    assert agency.store.list_scout(status="kit_ready")
    # no HTTP write ever went to a signup endpoint
    assert all(not a["blocked"] for a in agency.store.list_http_audit())


def test_community_replies_go_through_policy(agency):
    cid = agency.store.add_content("post", "bluesky", body="our post", status="published")
    agency.store.update_content(cid, remote_id="at://x|cid", published_at="2999-01-01T00:00:00+00:00")
    agency.store.add_engagement("bluesky", cid, "c1", "ann", "Where is the guide?")
    agency.store.add_engagement("bluesky", cid, "c2", "bot", "spam spam")
    agency.toggles.set("auto_reply_own_posts", True)
    out = agency.director.community_cycle()
    verdicts = {r.get("verdict") for r in out["responses"] if "verdict" in r}
    assert verdicts == {"queue"}  # approval_required is on by default
    queued = agency.store.list_content(status="queued")
    assert len(queued) == 1 and queued[0]["kind"] == "reply"
    assert agency.store.pending_engagement() and len(agency.store.pending_engagement()) == 1


def test_kill_switch_stops_cycles(agency):
    agency.toggles.set("master_enabled", False)
    assert agency.director.daily_cycle() == {"skipped": "master switch off"}
    assert agency.director.scout_cycle() == []


def test_panel_smoke(agency):
    from fastapi.testclient import TestClient

    from agency.panel.app import create_app

    c = TestClient(create_app(agency))
    for path in ("/", "/queue", "/content", "/assets", "/platforms", "/scout", "/logs", "/models", "/api/status"):
        assert c.get(path).status_code == 200, path
    r = c.post("/toggle", data={"name": "publishing", "value": "1"}, follow_redirects=False)
    assert r.status_code == 303 and agency.toggles.get("publishing")
    assert c.post("/api/toggle/block_payments/0").status_code == 403
    assert c.post("/kill", follow_redirects=False).status_code == 303 and not agency.toggles.get("master_enabled")
