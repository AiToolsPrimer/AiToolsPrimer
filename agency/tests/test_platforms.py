from pathlib import Path

from agency.platforms import build_all
from agency.platforms.base import PublishItem
from agency.safety.payment_guard import GuardedHTTP
from agency.settings import Settings


def test_dry_run_everywhere_and_limits():
    ps = build_all(Settings(), GuardedHTTP(), dry_run=True)
    assert len(ps) == 17
    for name, p in ps.items():
        if name == "x":
            continue
        kind = sorted(p.kinds)[0]
        r = p.publish(PublishItem(kind=kind, text="x" * 5000, title="t", media=[Path("/nonexistent.mp4")]))
        assert r.ok and r.dry_run, name
    assert not ps["bluesky"].publish(PublishItem(kind="video")).ok


def test_missing_credentials_reported_live():
    ps = build_all(Settings(), GuardedHTTP(), dry_run=False)
    r = ps["bluesky"].publish(PublishItem(kind="post", text="hi"))
    assert not r.ok and "BLUESKY_HANDLE" in r.error


def test_fit_keeps_whole_words():
    ps = build_all(Settings(), GuardedHTTP(), dry_run=True)
    item = ps["x"].fit(PublishItem(kind="post", text="word " * 100))
    assert len(item.text) <= 280 and item.text.endswith("…") and "wor…" not in item.text


def test_x_is_never_published_through_the_paid_api():
    from agency.platforms.x import X
    ps = build_all(Settings(), GuardedHTTP(), dry_run=False)
    r = ps["x"].publish(PublishItem(kind="post", text="hello", link="https://aitoolsprimer.com/pdf"))
    assert not r.ok and "paid" in r.error
    assert X.intent_url(PublishItem(kind="post", text="hello", link="https://aitoolsprimer.com/pdf")).startswith("https://x.com/intent/post?text=hello%20https")
    assert Settings().mode_for("x") == "browser" and Settings().mode_for("bluesky") == "api"


def test_medium_is_manual():
    ps = build_all(Settings(), GuardedHTTP(), dry_run=False)
    assert not ps["medium"].configured()
