"""APScheduler BackgroundScheduler wiring for Grafana Reporter jobs."""

import importlib
import sys
import uuid
from typing import Any

import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import config_manager


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def get_scheduler() -> BackgroundScheduler:
    """Return the shared BackgroundScheduler, creating and starting it if needed.

    The instance is stored in st.session_state["scheduler"] so Streamlit
    reruns do not create a second scheduler.
    """
    if "scheduler" not in st.session_state:
        sched = BackgroundScheduler(daemon=True)
        sched.start()
        st.session_state["scheduler"] = sched
    return st.session_state["scheduler"]


# ---------------------------------------------------------------------------
# Bulk load
# ---------------------------------------------------------------------------

def load_jobs_from_config() -> None:
    """Register all active jobs from config.json with the scheduler.

    Reads every job whose status is "active" and calls add_or_update_job()
    for each. Logs the count to stdout.
    """
    jobs = config_manager.get_jobs()
    active = [j for j in jobs if j.get("status") == "active"]
    for job in active:
        add_or_update_job(job)
    print(f"[scheduler] Loaded {len(active)} active job(s) from config.", flush=True)


# ---------------------------------------------------------------------------
# Single job management
# ---------------------------------------------------------------------------

def add_or_update_job(job_config: dict[str, Any]) -> None:
    """Add or replace a scheduler job from a job config dict.

    Removes any existing job with the same ID first, then registers a new
    CronTrigger built from the job's schedule block.  Supports frequencies:
    "daily" — runs on the specified days each week at the given time,
    "weekly" — same semantics as daily (days + time),
    "monthly" — runs on the 1st of every month at the given time.
    """
    sched = get_scheduler()
    job_id = job_config.get("id")
    if not job_id:
        # Defense-in-depth: callers should always pass a job with an id by
        # now, but don't let a stray legacy job crash the scheduler either —
        # assign and persist one, same self-heal pattern used elsewhere.
        job_id = str(uuid.uuid4())
        job_config["id"] = job_id
        config_manager.upsert_job(job_config)

    # Remove stale job if present
    if sched.get_job(job_id) is not None:
        sched.remove_job(job_id)

    trigger = _build_trigger(job_config.get("schedule", {}))

    # Import runner lazily so this module does not hard-depend on the project
    # root being on sys.path at import time — it will be when Streamlit runs.
    runner = _import_runner()

    sched.add_job(
        func=runner.run_job,
        trigger=trigger,
        args=[job_id],
        id=job_id,
        name=job_config.get("name", job_id),
        replace_existing=True,
        misfire_grace_time=300,  # allow up to 5 min late if host was asleep
    )


def remove_job(job_id: str) -> None:
    """Remove the job with job_id from the scheduler.

    Silently does nothing if the job is not currently scheduled.
    """
    sched = get_scheduler()
    if sched.get_job(job_id) is not None:
        sched.remove_job(job_id)


# ---------------------------------------------------------------------------
# Status queries
# ---------------------------------------------------------------------------

def get_next_run(job_id: str) -> str:
    """Return the next run time for job_id as "DD Mon YYYY HH:MM".

    Returns "Not scheduled" if the job is not found or has no pending run.
    """
    sched = get_scheduler()
    job = sched.get_job(job_id)
    if job is None or job.next_run_time is None:
        return "Not scheduled"
    return job.next_run_time.strftime("%d %b %Y %H:%M")


def get_all_job_statuses() -> list[dict[str, Any]]:
    """Return a list of {id, name, next_run} for every currently scheduled job."""
    sched = get_scheduler()
    result: list[dict[str, Any]] = []
    for job in sched.get_jobs():
        next_run = (
            job.next_run_time.strftime("%d %b %Y %H:%M")
            if job.next_run_time
            else "Not scheduled"
        )
        result.append({"id": job.id, "name": job.name, "next_run": next_run})
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_trigger(schedule: dict[str, Any]) -> CronTrigger:
    """Construct a CronTrigger from a job schedule dict.

    Expected keys: frequency ("daily" | "weekly" | "monthly"),
    time ("HH:MM"), days (list of abbreviated day names, e.g. ["mon","fri"]).
    Falls back to a daily midnight trigger if the schedule block is malformed.
    """
    frequency: str = schedule.get("frequency", "daily")
    time_str: str = schedule.get("time", "00:00")
    days: list[str] = schedule.get("days", [])

    try:
        hour_str, minute_str = time_str.split(":")
        hour = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError):
        hour, minute = 0, 0

    if frequency == "monthly":
        return CronTrigger(day=1, hour=hour, minute=minute)

    # "daily" and "weekly" both use a day_of_week constraint
    if days:
        day_of_week = ",".join(days)
    else:
        day_of_week = "mon-fri"  # sensible default when no days specified

    return CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute)


def _import_runner() -> Any:
    """Import the runner module from the project root.

    Ensures the project root is on sys.path before importing, which is
    required when the working directory differs from the import path.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    return importlib.import_module("runner")
