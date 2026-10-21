import datetime as dt

from agency.memory.store import Store


def test_content_lifecycle(tmp_path):
    s = Store(tmp_path / "a.db")
    cid = s.add_content("post", "bluesky", topic="pdf", title="t", body="b", meta={"link": "x"})
    s.update_content(cid, status="published", remote_id="r1", meta={"link": "x", "dry_run": True})
    row = s.get_content(cid)
    assert row["status"] == "published" and row["meta"]["dry_run"] is True
    assert s.list_content(status="published")[0]["id"] == cid
    assert "pdf" in s.recent_topics()


def test_actions_counting(tmp_path):
    s = Store(tmp_path / "a.db")
    for _ in range(3):
        s.log_action("publish_post", "bluesky", "allow", "ok")
    s.log_action("publish_post", "bluesky", "queue", "held")
    assert s.count_recent_actions("bluesky", "publish_post", dt.timedelta(days=1)) == 3


def test_engagement_dedupe_and_scout(tmp_path):
    s = Store(tmp_path / "a.db")
    assert s.add_engagement("bluesky", 1, "c1", "ann", "hi")
    assert not s.add_engagement("bluesky", 1, "c1", "ann", "hi")
    sid = s.add_scout("Lemmy", "https://lemmy.world", "forum", True, True, 0.8, "r")
    assert s.add_scout("Lemmy", "https://lemmy.world", "forum", True, True, 0.8, "r") is None
    s.set_scout_kit(sid, {"handle": "x"})
    assert s.list_scout(status="kit_ready")[0]["signup_kit"]["handle"] == "x"


def test_recall_with_embeddings(tmp_path):
    s = Store(tmp_path / "a.db", embed=lambda texts: [[1.0, 0.0] if "pdf" in t else [0.0, 1.0] for t in texts])
    s.add_content("post", "x", title="pdf tools", body="five pdf tools")
    s.add_content("post", "x", title="mac tips", body="finder tricks")
    assert s.recall("pdf", k=1)[0]["text"].startswith("pdf tools")
