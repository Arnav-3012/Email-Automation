"""Read and write config.json — Grafana connection settings and job definitions."""

import json
import threading
import uuid
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

# Guards every load-modify-save sequence in this module (and in
# auth_manager._orphan_jobs_for_deleted_user, which mutates config.json
# directly) so two concurrent writers can't lose one another's changes.
LOCK = threading.Lock()

_DEFAULT_CONFIG: dict[str, Any] = {
    "grafana": {
        "url": "",
        "username": "",
        "password": "",
        "org_id": 1
    },
    "smtp": {
        "host": "",
        "port": 587,
        "username": "",
        "password": "",
        "force_smtp": False,
        "tls_mode": "starttls"
    },
    "debug_mode": False,
    "jobs": []
}


def load() -> dict[str, Any]:
    """Load config.json, creating it with defaults if it does not exist."""
    if not CONFIG_PATH.exists():
        save(_DEFAULT_CONFIG)
        return _DEFAULT_CONFIG.copy()
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"Failed to read {CONFIG_PATH}: {e}") from e


def save(config: dict[str, Any]) -> None:
    """Write the given config dict to config.json.

    Writes to a temp file and atomically renames it into place so a
    concurrent load() never observes a half-written file.
    """
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        tmp_path.replace(CONFIG_PATH)
    except OSError as e:
        raise RuntimeError(f"Failed to write {CONFIG_PATH}: {e}") from e


def get_grafana_settings() -> dict[str, Any]:
    """Return grafana connection settings: url, username, password, org_id."""
    stored = load().get("grafana", {})
    return {
        "url": stored.get("url", ""),
        "username": stored.get("username", ""),
        "password": stored.get("password", ""),
        "org_id": int(stored.get("org_id", 1)),
    }


def update_grafana_settings(
    url: str, username: str = "", password: str = "", org_id: int = 1
) -> None:
    """Persist Grafana connection settings (URL and admin credentials) to config.json."""
    with LOCK:
        config = load()
        config["grafana"] = {
            "url": url,
            "username": username,
            "password": password,
            "org_id": org_id,
        }
        save(config)


def get_smtp_settings() -> dict[str, Any]:
    """Return SMTP settings: host, port (int), username, password, force_smtp (bool), tls_mode (str)."""
    stored = load().get("smtp", {})
    return {
        "host": stored.get("host", ""),
        "port": int(stored.get("port", 587)),
        "username": stored.get("username", ""),
        "password": stored.get("password", ""),
        "force_smtp": bool(stored.get("force_smtp", False)),
        "tls_mode": stored.get("tls_mode", "starttls"),
    }


def update_smtp_settings(
    host: str,
    port: int = 587,
    username: str = "",
    password: str = "",
    force_smtp: bool = False,
    tls_mode: str = "starttls",
) -> None:
    """Persist SMTP connection settings to config.json."""
    with LOCK:
        config = load()
        config["smtp"] = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "force_smtp": force_smtp,
            "tls_mode": tls_mode,
        }
        save(config)


def get_debug_mode() -> bool:
    """Return True if debug logging is enabled in config."""
    return bool(load().get("debug_mode", False))


def set_debug_mode(enabled: bool) -> None:
    """Persist debug_mode flag to config.json."""
    with LOCK:
        config = load()
        config["debug_mode"] = enabled
        save(config)


def get_jobs() -> list[dict[str, Any]]:
    """Return all job definitions from config."""
    return load().get("jobs", [])


def get_job(job_id: str) -> dict[str, Any] | None:
    """Return a single job by ID, or None if not found."""
    return next((j for j in get_jobs() if j.get("id") == job_id), None)


def upsert_job(job: dict[str, Any]) -> None:
    """Add a new job or replace an existing one (matched by id) in config.json."""
    # Safety net: jobs should always carry an id by the time they reach here,
    # but guard against callers (or hand-edited config.json) that omit it —
    # without this, the id-matching lookup below would raise KeyError.
    if not job.get("id"):
        job["id"] = str(uuid.uuid4())
    job.setdefault("email_subject", "")
    job.setdefault("email_message", "")
    job.setdefault("panel_names", {})
    job.setdefault("dashboard_names", {})
    job.setdefault("time_range", {"from": "now-24h", "to": "now"})
    # "" (not None) so older callers/tests that don't pass created_by still
    # get a string back from get("created_by", "") rather than needing a
    # None-check everywhere ownership is compared.
    job.setdefault("created_by", "")
    with LOCK:
        config = load()
        jobs = config.get("jobs", [])
        idx = next((i for i, j in enumerate(jobs) if j.get("id") == job["id"]), None)
        if idx is None:
            jobs.append(job)
        else:
            jobs[idx] = job
        config["jobs"] = jobs
        save(config)


def delete_job(job_id: str) -> None:
    """Remove the job with the given ID from config.json."""
    with LOCK:
        config = load()
        config["jobs"] = [j for j in config.get("jobs", []) if j.get("id") != job_id]
        save(config)


def migrate_jobs_add_missing_ids() -> int:
    """One-time-per-startup migration: give every job missing an "id" a fresh uuid4.

    Jobs predating the id field (or added by hand-editing config.json) would
    otherwise crash every id-matching lookup in this module. Returns the
    number of jobs that were assigned a new id.
    """
    with LOCK:
        config = load()
        changed = 0
        for job in config.get("jobs", []):
            if not job.get("id"):
                job["id"] = str(uuid.uuid4())
                changed += 1
        if changed:
            save(config)
        return changed


# ---------------------------------------------------------------------------
# Job ownership / access control
# ---------------------------------------------------------------------------
#
# Jobs created before this feature existed have no "created_by" field. They
# are treated as unowned: admins still see and manage them (admins see every
# job regardless of owner), but a regular user will never see an unowned job
# until an admin explicitly assigns it to someone via set_job_owner().

def get_jobs_for_user(username: str, role: str) -> list[dict[str, Any]]:
    """Return the jobs this user is allowed to see.

    Admins see every job. Regular users see only jobs whose "created_by"
    matches their username — this also means legacy jobs with no
    "created_by" are invisible to regular users until reassigned.
    """
    jobs = get_jobs()
    if role == "admin":
        return jobs
    return [j for j in jobs if j.get("created_by") == username]


def can_manage_job(job: dict[str, Any], username: str, role: str) -> bool:
    """Return True if this user may run/pause/edit/delete the given job.

    Admins can manage any job. Regular users can only manage jobs they
    created (an empty/missing "created_by" never matches a real username,
    so legacy/orphaned jobs are correctly excluded).
    """
    if role == "admin":
        return True
    return bool(username) and job.get("created_by") == username


def set_job_owner(job_id: str, username: str) -> bool:
    """Admin action: assign/reassign which user owns a job.

    Used to claim legacy jobs that predate this feature, or to reassign a
    job left behind by a deleted user. Clears creator_deleted flag and
    resumes the job if it was paused due to orphaning.
    Returns False if job_id is not found.
    """
    with LOCK:
        config = load()
        jobs = config.get("jobs", [])
        job = next((j for j in jobs if j.get("id") == job_id), None)
        if job is None:
            return False
        was_orphaned = job.get("creator_deleted", False)
        job["created_by"] = username
        job.pop("creator_deleted", None)
        # Re-activate jobs that were paused solely because their creator was deleted.
        if was_orphaned and job.get("status") == "paused":
            job["status"] = "active"
        save(config)
        return True


def update_job_run_status(job_id: str, last_run: str, last_status: str) -> None:
    """Update last_run timestamp and last_status for a job after execution."""
    with LOCK:
        config = load()
        for job in config.get("jobs", []):
            if job.get("id") == job_id:
                job["last_run"] = last_run
                job["last_status"] = last_status
                break
        save(config)
