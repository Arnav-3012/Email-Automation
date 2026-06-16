"""User accounts, login verification, and audit logging for the Streamlit UI."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import bcrypt
import streamlit as st

# Anchored to the project root (mirrors config_manager.py) so this works
# regardless of the cwd Streamlit was launched from.
USERS_FILE = Path(__file__).parent.parent / "app_users.json"
AUDIT_FILE = Path(__file__).parent.parent / "audit_log.json"

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
    """Write the given users dict to app_users.json."""
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with USERS_FILE.open("w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def users_file_exists() -> bool:
    """True once at least one admin account has been created."""
    return USERS_FILE.exists()


def verify_login(username: str, password: str) -> bool:
    """Check credentials and, on success, stamp last_login. Returns success bool."""
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
    save_users(users)
    log_event("system_init", username, "initial_admin_setup")


def create_user(username: str, password: str, role: str = "user") -> bool:
    """Add a new user. Returns False if the username is already taken."""
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
    """Remove a user. Refuses to delete the last remaining admin account."""
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
    return True


def list_users() -> list[dict[str, Any]]:
    """Return all user records."""
    return load_users().get("users", [])


def get_user(username: str) -> dict[str, Any] | None:
    """Return a single user record, or None if not found."""
    return next((u for u in load_users()["users"] if u["username"] == username), None)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def log_event(event_type: str, username: str, details: str = "") -> None:
    """Append an entry to audit_log.json."""
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
    with AUDIT_FILE.open("w", encoding="utf-8") as f:
        json.dump({"events": audit}, f, indent=2)


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
        st.session_state.authenticated = False
        st.session_state.current_user = None
        st.rerun()
    st.sidebar.caption(f"👤 {username}")
