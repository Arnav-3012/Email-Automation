"""Read and write config.json — Grafana connection settings and job definitions."""

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

_DEFAULT_CONFIG: dict[str, Any] = {
    "grafana": {
        "url": "",
        "api_key": "",
        "username": "",
        "password": ""
    },
    "smtp": {
        "host": "",
        "port": 587,
        "username": "",
        "password": "",
        "force_smtp": False
    },
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
    """Write the given config dict to config.json."""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except OSError as e:
        raise RuntimeError(f"Failed to write {CONFIG_PATH}: {e}") from e


def get_grafana_settings() -> dict[str, str]:
    """Return grafana connection settings: url, api_key, username, password."""
    stored = load().get("grafana", {})
    return {
        "url": stored.get("url", ""),
        "api_key": stored.get("api_key", ""),
        "username": stored.get("username", ""),
        "password": stored.get("password", ""),
    }


def update_grafana_settings(
    url: str, api_key: str, username: str = "", password: str = ""
) -> None:
    """Persist Grafana connection settings (URL, API key, login credentials) to config.json."""
    config = load()
    config["grafana"] = {
        "url": url,
        "api_key": api_key,
        "username": username,
        "password": password,
    }
    save(config)


def get_smtp_settings() -> dict[str, Any]:
    """Return SMTP settings: host, port (int), username, password, force_smtp (bool)."""
    stored = load().get("smtp", {})
    return {
        "host": stored.get("host", ""),
        "port": int(stored.get("port", 587)),
        "username": stored.get("username", ""),
        "password": stored.get("password", ""),
        "force_smtp": bool(stored.get("force_smtp", False)),
    }


def update_smtp_settings(
    host: str,
    port: int = 587,
    username: str = "",
    password: str = "",
    force_smtp: bool = False,
) -> None:
    """Persist SMTP connection settings to config.json."""
    config = load()
    config["smtp"] = {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "force_smtp": force_smtp,
    }
    save(config)


def get_jobs() -> list[dict[str, Any]]:
    """Return all job definitions from config."""
    return load().get("jobs", [])


def get_job(job_id: str) -> dict[str, Any] | None:
    """Return a single job by ID, or None if not found."""
    return next((j for j in get_jobs() if j["id"] == job_id), None)


def upsert_job(job: dict[str, Any]) -> None:
    """Add a new job or replace an existing one (matched by id) in config.json."""
    config = load()
    jobs = config.get("jobs", [])
    idx = next((i for i, j in enumerate(jobs) if j["id"] == job["id"]), None)
    if idx is None:
        jobs.append(job)
    else:
        jobs[idx] = job
    config["jobs"] = jobs
    save(config)


def delete_job(job_id: str) -> None:
    """Remove the job with the given ID from config.json."""
    config = load()
    config["jobs"] = [j for j in config.get("jobs", []) if j["id"] != job_id]
    save(config)


def update_job_run_status(job_id: str, last_run: str, last_status: str) -> None:
    """Update last_run timestamp and last_status for a job after execution."""
    config = load()
    for job in config.get("jobs", []):
        if job["id"] == job_id:
            job["last_run"] = last_run
            job["last_status"] = last_status
            break
    save(config)
