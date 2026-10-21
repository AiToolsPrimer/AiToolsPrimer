import email.utils
from email.message import EmailMessage

import pytest

from agency.agents.mail import Mailbox, _parse
from agency.agents.network import _parse_feed


class FakeIMAP:
    """Minimal IMAP4 stand-in with two messages and a Drafts folder."""

    appended = []

    def __init__(self, host):
        self.host = host

    def login(self, u, p):
        return "OK", []

    def select(self, box, readonly=False):
        return "OK", []

    def search(self, charset, criteria):
        return "OK", [b"1 2"]

    def fetch(self, uid, what):
        msgs = {b"1": self._msg("reader@example.com", "Question about PDF editors", "Which one did you like? Thanks"),
                b"2": self._msg("digest@sourceofsources.com", "SOS digest: 2 requests", "Reuters wants experts on free PDF editors, email reporter@reuters.example.com by Oct 25.")}
        return "OK", [(b"1 (BODY[] {}", msgs[uid])]

    @staticmethod
    def _msg(frm, subject, body):
        m = EmailMessage()
        m["From"], m["To"], m["Subject"], m["Date"] = frm, "me@example.com", subject, email.utils.formatdate()
        m.set_content(body)
        return m.as_bytes()

    def append(self, folder, flags, date, raw):
        FakeIMAP.appended.append((folder, raw))
        return "OK", []

    def logout(self):
        return "BYE", []


def test_mailbox_parses_and_saves_drafts_without_sending():
    mb = Mailbox("imap.example.com", "me@example.com", "pw", connect=FakeIMAP)
    msgs = mb.recent(days=3)
    assert len(msgs) == 2 and msgs[0]["from"] == "reader@example.com" and "Which one" in msgs[0]["body"]
    assert mb.save_draft("reader@example.com", "Re: Question", "Thanks!", "me@example.com")
    assert FakeIMAP.appended and b"Thanks!" in FakeIMAP.appended[-1][1]


def test_mail_agent_classifies_and_extracts_journalist_requests(agency):
    agency.mail.mailbox = Mailbox("imap.example.com", "me@example.com", "pw", connect=FakeIMAP)
    agency.mail.from_addr = "me@example.com"
    agency.toggles.set("read_mail", True)
    out = agency.director.mail_cycle()
    assert out["new"] == 2 and out["journalist_requests"] == 1       # the guessed address was dropped, the real one kept
    opps = agency.store.list_pr_opportunities()
    assert len(opps) == 1 and opps[0]["contact"] == "reporter@reuters.example.com" and opps[0]["kind"] == "journalist_request"
    drafts = agency.store.list_mail_drafts()
    assert drafts and drafts[0]["to_addr"] == "reader@example.com"
    assert out["saved_to_gmail_drafts"] == 1
    assert agency.director.mail_cycle()["new"] == 0                  # nothing read twice
    agency.toggles.set("read_mail", False)
    assert "skipped" in agency.director.mail_cycle()


def test_pr_finds_mentions_and_dead_links_on_authoritative_sites_only(agency):
    agency.store.set_authority("bigtech.example.com", 1200)       # authoritative
    agency.store.set_authority("niche-blog.example.com", 900000)   # not
    mentions = agency.pr.unlinked_mentions()
    assert len(mentions) == 1 and mentions[0]["url"].startswith("https://bigtech.example.com")
    broken = agency.pr.broken_links(["https://bigtech.example.com/review", "https://niche-blog.example.com/"], [{"url": "https://aitoolsprimer.com/pdf", "title": "pdf"}])
    assert len(broken) == 1 and broken[0]["dead"].startswith("https://dead.example.com")
    opp = agency.store.list_pr_opportunities(status="found")[0]
    pitch = agency.pr.write_pitch(opp["id"])
    assert pitch and "watermark" in pitch["body"] and agency.store.get_pr_opportunity(opp["id"])["status"] == "pitched"
    assert agency.authority.is_authoritative("https://bigtech.example.com/x") and not agency.authority.is_authoritative("https://unknown.example.org")


def test_network_discovers_follows_and_drafts_comments_for_approval(agency):
    found = agency.network.discover()
    urls = {f["url"] for f in found}
    assert "https://niche-blog.example.com/" in urls and "https://bsky.app/profile/toolsnerd.bsky.social" in urls
    site = next(f for f in found if f["kind"] == "site")
    assert site["feed"] == "https://niche-blog.example.com/feed.xml"
    for f in found:
        agency.store.set_network_source_status(f["id"], "following")
    out = agency.network.watch()
    assert out["new_items"] == 2
    drafts = agency.network.draft_comments()
    assert len(drafts) == 2
    comment = agency.store.get_content(drafts[0]["content_id"])
    assert comment["kind"] == "comment" and comment["status"] == "queued" and "watermark" not in comment["body"] or comment["status"] == "queued"
    # approval = the click; Bluesky goes through the API reply, the web source has no API -> browser/manual
    bsky = next(agency.store.get_content(d["content_id"]) for d in drafts if agency.store.get_content(d["content_id"])["platform"] == "bluesky")
    d = agency.director.approve(bsky["id"])
    assert d.allowed and agency.store.get_content(bsky["id"])["status"] == "published"
    assert agency.store.list_network_items()[0]["status"] in ("commented", "drafted")
    assert agency.network.watch()["new_items"] == 0


def test_external_comments_never_auto_publish(agency):
    agency.toggles.set("publishing", True)
    agency.toggles.set("approval_required", False)
    from agency.safety.policy import Action, ActionKind
    d = agency.policy.evaluate(Action(ActionKind.EXTERNAL_COMMENT, "bluesky", {"content_id": 1}, safety_passed=True))
    assert d.verdict.value == "queue" and "click" in d.reason


def test_questions_become_drafts_or_fact_cards(agency):
    out = agency.director.questions_cycle()
    platforms = {o["platform"] for o in out}
    assert platforms == {"reddit", "hackernews"}
    for o in out:
        row = agency.store.get_content(o["content_id"])
        assert row["status"] == "manual"
        if o["platform"] == "hackernews":
            assert row["body"].startswith("FACT CARD")
        else:
            assert "I run the site" in row["body"]
    assert agency.director.questions_cycle() == []   # dedup


def test_feed_parser():
    items = _parse_feed('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title><link href="https://a.example.com/1"/><updated>2026-10-20</updated></entry></feed>')
    assert items == [{"url": "https://a.example.com/1", "title": "A", "published": "2026-10-20"}]


def test_outreach_page(agency):
    from fastapi.testclient import TestClient

    from agency.panel.app import create_app

    c = TestClient(create_app(agency))
    assert c.get("/outreach").status_code == 200
    r = c.post("/network/add", data={"url": "https://niche-blog.example.com/"}, follow_redirects=False)
    assert r.status_code == 303 and agency.store.list_network_sources(status="following")
