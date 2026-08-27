"""
scheduler.py — Background Scheduler for LMS Notifications
==========================================================
Runs two jobs automatically:
  1. Daily 8:00 AM  → Deadline reminders (2 days before + last day)
  2. Every Sunday 9:00 AM → Weekly digest

Install:
    pip install APScheduler

Add in your app.py (inside create_app or at bottom before app.run):
    from scheduler import start_scheduler
    start_scheduler(notify)   # pass your notify instance
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
_scheduler = None


def start_scheduler(notify_instance):
    """
    Call this once when Flask starts.

    In app.py, at the bottom just before app.run():
        from scheduler import start_scheduler
        start_scheduler(notify)
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        return  # Already running — don't start twice (Flask debug mode restarts)

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Daily at 8:00 AM — deadline reminders
    _scheduler.add_job(
        func=notify_instance.deadline_reminder,
        trigger=CronTrigger(hour=8, minute=0),
        id="deadline_reminder",
        replace_existing=True,
        misfire_grace_time=3600  # run even if server was down, within 1hr
    )

    # Every Sunday at 9:00 AM — weekly digest
    _scheduler.add_job(
        func=notify_instance.weekly_digest,
        trigger=CronTrigger(day_of_week="sun", hour=9, minute=0),
        id="weekly_digest",
        replace_existing=True,
        misfire_grace_time=3600
    )

    _scheduler.start()
    logger.info("Scheduler started: deadline_reminder (daily 8AM), weekly_digest (Sunday 9AM)")
