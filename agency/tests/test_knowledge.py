from pathlib import Path

from agency.knowledge.base import Constraints, KnowledgeBase, check_constraints, fix_for_platform
from agency.settings import ROOT

KB = KnowledgeBase(ROOT / "knowledge")


def test_every_platform_has_a_card_with_limits_and_sources():
    expected = {"x", "bluesky", "mastodon", "threads", "linkedin", "facebook", "instagram", "tiktok", "youtube", "pinterest", "telegram", "reddit", "medium", "substack", "devto", "hashnode", "tumblr", "wordpress", "vimeo", "dailymotion", "podcast", "flipboard", "quora", "hackernews", "stackexchange"}
    assert expected <= set(KB.cards)
    for key, card in KB.cards.items():
        assert card.meta.get("last_checked"), key
        assert card.meta.get("sources"), key
        assert "## Updates" in card.body, key
    assert {"virality", "compliance", "formats", "cadence"} <= set(KB.playbooks)


def test_constraints_from_cards():
    c = KB.constraints("instagram")
    assert c.char_limit == 2200 and c.hashtags_max == 5 and c.link_policy == "not-clickable"
    assert KB.constraints("linkedin").link_policy == "in-first-comment"
    assert KB.constraints("x").char_limit == 280
    assert KB.constraints("nowhere").char_limit == 0


def test_check_and_fix():
    c = KB.constraints("linkedin")
    text = "We tested five tools. Full table: https://aitoolsprimer.com/pdf #ai #tools #pdf #free"
    assert any("first comment" in p for p in check_constraints(text, "linkedin", c))
    fixed, first_comment = fix_for_platform(text, c)
    assert "https://" not in fixed and first_comment == "https://aitoolsprimer.com/pdf"
    assert len([t for t in fixed.split() if t.startswith("#")]) == 3
    assert check_constraints(fixed, "linkedin", c) == []
    long = "word " * 100
    fixed, _ = fix_for_platform(long, KB.constraints("x"))
    assert len(fixed) <= 280
    assert check_constraints("AI people in this image", "tiktok", Constraints(ai_label="required", ai_label_text="AI-generated"), is_ai_generated_media=True)


def test_brief_contains_limits_and_playbook_text():
    b = KB.brief("tiktok")
    assert "Hard limits" in b and "watch time" in b.lower()
    assert "hook" in KB.playbook("virality").lower()


def test_apply_update_and_stale(tmp_path: Path):
    import shutil
    root = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge", root)
    kb = KnowledgeBase(root)
    kb.apply_update("x", "Character limit for Premium is 25,000", source="https://example.com")
    kb.set_meta("x", "hashtags_max", "2")
    card = kb.card("x")
    assert "Character limit for Premium" in card.section("Updates") and card.meta["hashtags_max"] == 2
    assert not card.stale(1)


def test_news_watch_creates_proposals(agency, monkeypatch):
    nw = agency.news_watch
    monkeypatch.setattr(nw, "search", lambda q, limit=8: [{"url": "https://example.com/x-limits", "title": "X raises limit", "snippet": "Premium posts now 25k"}])
    monkeypatch.setattr(nw, "ask_json", lambda *a, **k: {"changes": [{"summary": "Premium character limit raised to 25,000", "field": "none", "new_value": "", "source": "https://example.com/x-limits", "confidence": 0.7}]})
    out = nw.check_card("x")
    assert out and agency.store.list_knowledge_updates()[0]["platform"] == "x"
    # applying writes a dated note into the card (on a copy, so the repo stays clean)
    import shutil
    root = agency.state_dir / "knowledge"
    shutil.copytree(ROOT / "knowledge", root)
    nw.kb = KnowledgeBase(root)
    nw.apply(out[0]["id"])
    assert "25,000" in nw.kb.card("x").section("Updates")
    assert agency.store.list_knowledge_updates(status="applied")


def test_director_moves_links_to_first_comment_and_keeps_writing_in_english(agency):
    cid = agency.store.add_content("post", "linkedin", body="We tested five tools. Full table: https://aitoolsprimer.com/pdf", status="draft", meta={"link": "https://aitoolsprimer.com/pdf"})
    agency.director._gate(cid)
    row = agency.store.get_content(cid)
    assert "https://" not in row["body"] and row["meta"]["first_comment"] == "https://aitoolsprimer.com/pdf"
    assert row["status"] == "queued"
