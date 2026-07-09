"""User accounts, login verification, and audit logging for the Streamlit UI."""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import bcrypt
import streamlit as st

# Anchored to the project root (mirrors config_manager.py) so this works
# regardless of the cwd Streamlit was launched from.
USERS_FILE = Path(__file__).parent.parent / "app_users.json"
AUDIT_FILE = Path(__file__).parent.parent / "audit_log.json"

# Guards every load-modify-save sequence against app_users.json (create_user,
# delete_user, reset_password, etc. all read-modify-write the same file).
_USERS_LOCK = threading.Lock()
# Guards audit_log.json's read-modify-write append in log_event().
_AUDIT_LOCK = threading.Lock()

_MIN_PASSWORD_LEN = 8
_MAX_PASSWORD_LEN = 72  # bcrypt's hard limit — longer raises ValueError


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Return a bcrypt hash for the given password."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hash_str: str) -> bool:
    """Check a plaintext password against a bcrypt hash. Never raises."""
    try:
        return bcrypt.checkpw(password.encode(), hash_str.encode())
    except Exception:
        return False


def validate_password(password: str) -> str:
    """Return an error message if password fails policy, or '' if it's fine."""
    if len(password) < _MIN_PASSWORD_LEN:
        return f"Password must be at least {_MIN_PASSWORD_LEN} characters"
    if len(password.encode()) > _MAX_PASSWORD_LEN:
        return f"Password must be at most {_MAX_PASSWORD_LEN} characters"
    return ""


# ---------------------------------------------------------------------------
# Users file
# ---------------------------------------------------------------------------

def load_users() -> dict[str, Any]:
    """Load app_users.json, returning an empty user list if it doesn't exist."""
    if USERS_FILE.exists():
        with USERS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": []}


def save_users(users: dict[str, Any]) -> None:
    """Write the given users dict to app_users.json.

    Writes to a temp file and atomically renames it into place so a
    concurrent load_users() never observes a half-written file.
    """
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = USERS_FILE.with_name(USERS_FILE.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    tmp_path.replace(USERS_FILE)


def has_users() -> bool:
    """True if at least one user account exists.

    Covers both first-run cases: the file is missing entirely, or it exists
    but its "users" list is empty (e.g. left over from a wiped/reset setup).
    Either way the setup wizard should show instead of the login form.
    """
    return len(load_users().get("users", [])) > 0


def verify_login(username: str, password: str) -> bool:
    """Check credentials and, on success, stamp last_login. Returns success bool."""
    with _USERS_LOCK:
        users = load_users()
        user = next((u for u in users["users"] if u["username"] == username), None)
        if user and verify_password(password, user["password_hash"]):
            user["last_login"] = datetime.now().isoformat() + "Z"
            save_users(users)
            return True
        return False


def initialize_users(username: str, password: str) -> None:
    """Create the first (admin) account during the setup wizard."""
    users = {
        "users": [
            {
                "username": username,
                "password_hash": hash_password(password),
                "role": "admin",
                "created_at": datetime.now().isoformat() + "Z",
                "last_login": datetime.now().isoformat() + "Z",
            }
        ]
    }
    with _USERS_LOCK:
        save_users(users)
    log_event("system_init", username, "initial_admin_setup")


def create_user(username: str, password: str, role: str = "user") -> bool:
    """Add a new user. Returns False if the username is already taken."""
    with _USERS_LOCK:
        users = load_users()
        if any(u["username"] == username for u in users["users"]):
            return False
        users["users"].append({
            "username": username,
            "password_hash": hash_password(password),
            "role": role,
            "created_at": datetime.now().isoformat() + "Z",
            "last_login": None,
        })
        save_users(users)
        return True


def reset_password(username: str, new_password: str) -> bool:
    """Admin-initiated password reset — does not require the old password."""
    with _USERS_LOCK:
        users = load_users()
        user = next((u for u in users["users"] if u["username"] == username), None)
        if not user:
            return False
        user["password_hash"] = hash_password(new_password)
        save_users(users)
        return True


def change_password(username: str, old_password: str, new_password: str) -> bool:
    """Self-service password change — requires the current password to match."""
    if not verify_login(username, old_password):
        return False
    return reset_password(username, new_password)


def delete_user(username: str) -> bool:
    """Remove a user. Refuses to delete the last remaining admin account.

    Also orphans any jobs created by the deleted user: marks them with
    creator_deleted=True and sets their status to 'paused'.
    """
    with _USERS_LOCK:
        users = load_users()
        target = next((u for u in users["users"] if u["username"] == username), None)
        if not target:
            return False
        if target.get("role") == "admin":
            remaining_admins = sum(
                1 for u in users["users"] if u.get("role") == "admin" and u["username"] != username
            )
            if remaining_admins == 0:
                return False  # would lock everyone out
        users["users"] = [u for u in users["users"] if u["username"] != username]
        save_users(users)

    # Orphan jobs whose creator is the deleted user
    _orphan_jobs_for_deleted_user(username)

    return True


def _orphan_jobs_for_deleted_user(username: str) -> None:
    """Mark all jobs owned by a deleted user as orphaned and pause them."""
    from app import config_manager
    with config_manager.LOCK:
        config = config_manager.load()
        changed = False
        for job in config.get("jobs", []):
            if job.get("created_by") == username:
                job["creator_deleted"] = True
                job["status"] = "paused"
                changed = True
        if changed:
            config_manager.save(config)
    if changed:
        log_event("jobs_orphaned", "system", f"creator={username}")


def list_users() -> list[dict[str, Any]]:
    """Return all user records."""
    return load_users().get("users", [])


def get_user(username: str) -> dict[str, Any] | None:
    """Return a single user record, or None if not found."""
    return next((u for u in load_users()["users"] if u["username"] == username), None)


# ---------------------------------------------------------------------------
# Per-user Grafana credentials
# ---------------------------------------------------------------------------

def get_grafana_credentials(username: str) -> dict[str, str]:
    """Return {grafana_username, grafana_password} for the given app user.

    Falls back to the global config.json credentials if the user's personal
    ones are blank or not set. The fallback is transparent to callers.
    """
    from app import config_manager
    user = get_user(username)
    if user:
        personal_u = user.get("grafana_username", "").strip()
        personal_p = user.get("grafana_password", "").strip()
        if personal_u:
            return {"grafana_username": personal_u, "grafana_password": personal_p}

    # Fall back to global config.json
    global_settings = config_manager.get_grafana_settings()
    return {
        "grafana_username": global_settings.get("username", ""),
        "grafana_password": global_settings.get("password", ""),
    }


def save_grafana_credentials(username: str, grafana_username: str, grafana_password: str) -> bool:
    """Save personal Grafana credentials for the given app user.

    Returns False if the user is not found.
    """
    with _USERS_LOCK:
        users = load_users()
        user = next((u for u in users["users"] if u["username"] == username), None)
        if not user:
            return False
        user["grafana_username"] = grafana_username.strip()
        user["grafana_password"] = grafana_password.strip()
        save_users(users)
    log_event("grafana_credentials_updated", username, "personal")
    return True


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def log_event(event_type: str, username: str, details: str = "") -> None:
    """Append an entry to audit_log.json."""
    with _AUDIT_LOCK:
        audit: list[dict[str, Any]] = []
        if AUDIT_FILE.exists():
            with AUDIT_FILE.open("r", encoding="utf-8") as f:
                audit = json.load(f).get("events", [])

        audit.append({
            "timestamp": datetime.now().isoformat() + "Z",
            "event_type": event_type,
            "username": username,
            "details": details,
        })

        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = AUDIT_FILE.with_name(AUDIT_FILE.name + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump({"events": audit}, f, indent=2)
        tmp_path.replace(AUDIT_FILE)


def get_audit_log(limit: int = 100) -> list[dict[str, Any]]:
    """Return the most recent audit events, newest last."""
    if AUDIT_FILE.exists():
        with AUDIT_FILE.open("r", encoding="utf-8") as f:
            return json.load(f).get("events", [])[-limit:]
    return []


# ---------------------------------------------------------------------------
# Streamlit page guard
# ---------------------------------------------------------------------------
#
# Every page under pages/ runs as its own independent script (Streamlit
# multipage apps execute only the selected page, not main.py first), so the
# login gate in main.py alone does NOT protect direct navigation to other
# pages via the sidebar. Each page must call require_auth() as its very
# first Streamlit command — it owns st.set_page_config() so pages must not
# call it themselves.

def require_auth(page_title: str, page_icon: str = "📈", layout: str = "wide") -> None:
    """Gate a page behind login. Stops execution if not authenticated.

    Must be the first Streamlit call in the page (it calls set_page_config).
    On success, also renders the standard logout sidebar before returning.
    """
    if not st.session_state.get("authenticated", False):
        # A page refresh re-executes only this page's script (not main.py),
        # so a valid session token must be honoured here too, or logins
        # would only survive a refresh while sitting on the home page.
        try:
            from app.session_manager import validate_session

            _token = st.query_params.get("session", "")
            _username = validate_session(_token) if _token else None
        except Exception:
            _username = None

        if _username:
            st.session_state.authenticated = True
            st.session_state.current_user = _username
        else:
            st.set_page_config(page_title="Login Required", page_icon="🔒", layout="centered")
            st.title("🔒 Login Required")
            st.warning("Please log in from the home page to continue.")
            try:
                st.page_link("main.py", label="Go to Login", icon="🔐")
            except Exception:
                st.caption("Use the sidebar to navigate to the home page.")
            st.stop()

    st.set_page_config(page_title=page_title, page_icon=page_icon, layout=layout)
    render_user_sidebar()


def render_user_sidebar() -> None:
    """Draw the logout button and current-user caption in the sidebar."""
    username = st.session_state.get("current_user")
    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Logout", use_container_width=True, key="_auth_logout_btn"):
        log_event("logout", username)
        try:
            from app.session_manager import delete_session

            _token = st.query_params.get("session", "")
            if _token:
                delete_session(_token)
            st.query_params.clear()
        except Exception:
            pass
        st.session_state.authenticated = False
        st.session_state.current_user = None
        st.rerun()
    st.sidebar.caption(f"👤 {username}")
