import datetime as dt

import pytest

from agency.safety.policy import Action, ActionKind, PolicyEngine, Verdict
from agency.settings import Limits, Toggles


@pytest.fixture
def toggles(tmp_path):
    return Toggles(tmp_path / "t.json")


def engine(toggles, counts=None, hour=12):
    now = lambda: dt.datetime(2026, 1, 1, hour, 0, tzinfo=dt.timezone.utc)
    return PolicyEngine(toggles, Limits(), count_recent=lambda p, k, w: (counts or {}).get(p, 0), now=now)


def test_defaults_queue_everything(toggles):
    d = engine(toggles).evaluate(Action(ActionKind.PUBLISH_POST, "bluesky", safety_passed=True))
    assert d.verdict is Verdict.QUEUE and "publishing switch" in d.reason


def test_publish_flows_when_switches_on(toggles):
    toggles.set("publishing", True)
    toggles.set("approval_required", False)
    d = engine(toggles).evaluate(Action(ActionKind.PUBLISH_POST, "bluesky", safety_passed=True))
    assert d.allowed


def test_unsafe_or_unchecked_denied(toggles):
    toggles.set("publishing", True)
    toggles.set("approval_required", False)
    e = engine(toggles)
    assert e.evaluate(Action(ActionKind.PUBLISH_POST, "bluesky", safety_passed=False)).verdict is Verdict.DENY
    assert e.evaluate(Action(ActionKind.PUBLISH_POST, "bluesky")).verdict is Verdict.DENY


def test_hard_guarantees(toggles):
    toggles.set("publishing", True)
    toggles.set("approval_required", False)
    e = engine(toggles)
    for kind in (ActionKind.CREATE_ACCOUNT, ActionKind.FRIEND_REQUEST, ActionKind.MASS_COMMENT, ActionKind.PAYMENT):
        assert e.evaluate(Action(kind, "x", safety_passed=True)).verdict is Verdict.DENY
    assert e.evaluate(Action(ActionKind.PUBLISH_POST, "x", safety_passed=True, cost_estimate=0.01)).verdict is Verdict.DENY
    with pytest.raises(PermissionError):
        toggles.set("block_payments", False)


def test_master_kill(toggles):
    toggles.set("master_enabled", False)
    assert engine(toggles).evaluate(Action(ActionKind.SCOUT_SEARCH, "web")).verdict is Verdict.DENY


def test_platform_switch_and_quiet_hours(toggles):
    toggles.set("publishing", True)
    toggles.set("approval_required", False)
    toggles.set_platform("x", False)
    e = engine(toggles)
    assert e.evaluate(Action(ActionKind.PUBLISH_POST, "x", safety_passed=True)).verdict is Verdict.DENY
    assert engine(toggles, hour=3).evaluate(Action(ActionKind.PUBLISH_POST, "bluesky", safety_passed=True)).verdict is Verdict.QUEUE


def test_rate_limit(toggles):
    toggles.set("publishing", True)
    toggles.set("approval_required", False)
    d = engine(toggles, counts={"bluesky": 4}).evaluate(Action(ActionKind.PUBLISH_POST, "bluesky", safety_passed=True))
    assert d.verdict is Verdict.QUEUE and "daily limit" in d.reason


def test_toggle_for_capability(toggles):
    toggles.set("discover_platforms", False)
    assert engine(toggles).evaluate(Action(ActionKind.SCOUT_SEARCH, "web")).verdict is Verdict.DENY
    toggles.set("prepare_signup_kits", False)
    assert engine(toggles).evaluate(Action(ActionKind.SIGNUP_KIT, "lemmy")).verdict is Verdict.DENY
    toggles.set("prepare_signup_kits", True)
    assert engine(toggles).evaluate(Action(ActionKind.SIGNUP_KIT, "lemmy")).allowed


def test_toggles_persist(tmp_path):
    t = Toggles(tmp_path / "t.json")
    t.set("publishing", True)
    assert Toggles(tmp_path / "t.json").get("publishing") is True
