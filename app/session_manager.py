"""File-backed login session tokens — lets a login survive a browser refresh."""

import json
import threading
import time
import uuid
from pathlib import Path

SESSIONS_FILE = Path(__file__).parent.parent / "sessions.json"
SESSION_EXPIRY_HOURS = 8
_LOCK = threading.Lock()


def create_session(username: str) -> str:
    """Create a new session token for username and persist it. Returns the token."""
    token = str(uuid.uuid4())
    sessions = _load_sessions()
    sessions[token] = {
        "username": username,
        "created_at": time.time(),
        "expires_at": time.time() + (SESSION_EXPIRY_HOURS * 3600),
    }
    _save_sessions(sessions)
    return token


def validate_session(token: str) -> str | None:
    """Return the username for a valid, unexpired token, else None. Never raises."""
    if not token:
        return None
    sessions = _load_sessions()
    session = sessions.get(token)
    if not session:
        return None
    if time.time() > session.get("expires_at", 0):
        delete_session(token)
        return None
    return session.get("username")


def delete_session(token: str) -> None:
    """Remove a session token, if present."""
    if not token:
        return
    sessions = _load_sessions()
    sessions.pop(token, None)
    _save_sessions(sessions)


def cleanup_expired_sessions() -> None:
    """Drop all expired tokens from the sessions file."""
    sessions = _load_sessions()
    now = time.time()
    live = {k: v for k, v in sessions.items() if v.get("expires_at", 0) > now}
    if len(live) != len(sessions):
        _save_sessions(live)


def _load_sessions() -> dict:
    with _LOCK:
        if not SESSIONS_FILE.exists():
            return {}
        try:
            with SESSIONS_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def _save_sessions(sessions: dict) -> None:
    with _LOCK:
        try:
            SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = SESSIONS_FILE.with_name(SESSIONS_FILE.name + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(sessions, f, indent=2)
            tmp_path.replace(SESSIONS_FILE)
        except OSError:
            pass
