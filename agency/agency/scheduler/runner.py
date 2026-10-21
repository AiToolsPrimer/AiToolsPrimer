"""APScheduler jobs: daily plan, community checks, analyst, scout, and the publish queue."""
from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agency.app import Agency

log = logging.getLogger("agency.scheduler")


def _hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def release_due(agency: Agency) -> int:
    """Content approved with a scheduled time is published when the time comes."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%H:%M")
    n = 0
    for row in agency.store.list_content(status="approved"):
        when = row.get("scheduled_for")
        if not when or when <= now:
            d = agency.director.approve(row["id"])
            n += int(d.allowed)
    return n


def build(agency: Agency) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")
    d = agency.settings.director
    h, m = _hhmm(d.daily_cycle_utc)
    sched.add_job(agency.director.daily_cycle, CronTrigger(hour=h, minute=m), id="daily", max_instances=1, coalesce=True)
    sched.add_job(agency.director.community_cycle, IntervalTrigger(minutes=d.community_every_minutes), id="community", max_instances=1, coalesce=True)
    h, m = _hhmm(d.analyst_daily_utc)
    sched.add_job(agency.director.analyst_cycle, CronTrigger(hour=h, minute=m), id="analyst", max_instances=1, coalesce=True)
    day, hm = d.scout_weekly.split()
    h, m = _hhmm(hm)
    sched.add_job(agency.director.scout_cycle, CronTrigger(day_of_week=day, hour=h, minute=m), id="scout", max_instances=1, coalesce=True)
    sched.add_job(lambda: release_due(agency), IntervalTrigger(minutes=5), id="release", max_instances=1, coalesce=True)
    sched.add_job(agency.news_watch.run, CronTrigger(day_of_week="sun", hour=6, minute=0), id="news_watch", max_instances=1, coalesce=True)
    return sched
