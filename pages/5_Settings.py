"""Settings page — Grafana connection, SMTP configuration, and per-user Grafana credentials."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import config_manager
from app.auth_manager import (
    change_password,
    create_user,
    delete_user,
    get_grafana_credentials,
    get_user,
    list_users,
    log_event,
    reset_password,
    require_auth,
    save_grafana_credentials,
    validate_password,
)
from app.grafana_client import GrafanaConnectionError, test_connection
from app.ui_helpers import show_logo

show_logo()
require_auth(page_title="Settings", page_icon="⚙️")
st.title("⚙️ Settings")

grafana = config_manager.get_grafana_settings()
smtp = config_manager.get_smtp_settings()

current_user: str = st.session_state.current_user
current_user_record = get_user(current_user)
is_admin = (current_user_record or {}).get("role") == "admin"

# ---------------------------------------------------------------------------
# My Grafana Credentials (every logged-in user)
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("🔑 My Grafana Credentials")
    st.info(
        "Set your personal Grafana login here. These are used when you browse dashboards "
        "and when your jobs run — so your Grafana permission level (Admin, Editor, Viewer) "
        "controls what data is fetched. If left blank, the global fallback credentials "
        "configured by your system administrator are used automatically."
    )

    _user_record = get_user(current_user)
    _personal_u = (_user_record or {}).get("grafana_username", "") if _user_record else ""
    _personal_p = (_user_record or {}).get("grafana_password", "") if _user_record else ""

    my_grafana_username = st.text_input("My Grafana Username", value=_personal_u, key="my_grafana_u")
    my_grafana_password = st.text_input(
        "My Grafana Password", value=_personal_p, type="password", key="my_grafana_p"
    )

    col_save_mine, col_test_mine = st.columns(2, gap="small")

    with col_save_mine:
        if st.button("💾 Save My Credentials", use_container_width=True, type="primary"):
            save_grafana_credentials(current_user, my_grafana_username, my_grafana_password)
            st.success("Saved.")

    with col_test_mine:
        if st.button("🔌 Test My Connection", use_container_width=True):
            save_grafana_credentials(current_user, my_grafana_username, my_grafana_password)
            creds = get_grafana_credentials(current_user)
            if not creds.get("grafana_username"):
                st.warning(
                    "No credentials set (personal or global fallback). "
                    "Please set credentials before testing."
                )
            else:
                try:
                    test_connection(credentials=creds)
                    effective = (
                        "personal credentials"
                        if my_grafana_username.strip()
                        else "global fallback credentials"
                    )
                    st.success(f"✅ Connected — using {effective}.")
                except GrafanaConnectionError as e:
                    st.error(str(e))

# ---------------------------------------------------------------------------
# Grafana Server Settings (global — admin only)
# SECURITY: Global fallback username/password are NOT shown in the UI.
# They must be set directly in config.json by the system administrator.
# Only the server URL, CA certificate, and SSL settings are editable here.
# ---------------------------------------------------------------------------

if is_admin:
    with st.container(border=True):
        st.subheader("🌐 Grafana Server Settings (Global)")
        st.info(
            "The Grafana Server URL and SSL settings apply to everyone on this instance."
        )
        st.caption(
            "🔒 Default/fallback Grafana credentials are configured directly in **config.json** "
            "by your system administrator and are not editable through this UI. "
            "Each user should set their own personal Grafana credentials above."
        )

        grafana_url = st.text_input("Grafana Server URL", value=grafana["url"])
        st.caption("CA Certificate and SSL settings are global server-trust settings, not per-user.")

        col_save, col_test = st.columns(2, gap="small")

        with col_save:
            if st.button("💾 Save Server Settings", use_container_width=True, type="primary"):
                config_manager.update_grafana_settings(
                    url=grafana_url,
                    username=grafana.get("username", ""),
                    password=grafana.get("password", ""),
                )
                st.success("Saved.")

        with col_test:
            if st.button("🔌 Test Global Connection", use_container_width=True):
                config_manager.update_grafana_settings(
                    url=grafana_url,
                    username=grafana.get("username", ""),
                    password=grafana.get("password", ""),
                )
                try:
                    test_connection()
                    st.success("✅ Connected — Grafana reachable.")
                except GrafanaConnectionError as e:
                    st.error(str(e))

# ---------------------------------------------------------------------------
# SMTP Settings (admin only)
# ---------------------------------------------------------------------------

if is_admin:
    with st.container(border=True):
        st.subheader("📧 SMTP Settings")
        st.info("Only used on Mac for testing. Ignored on Windows — Outlook is used instead.")

        smtp_host = st.text_input("SMTP Host", value=smtp["host"])

        smtp_port_col, smtp_tls_col = st.columns(2)
        with smtp_port_col:
            smtp_port = st.number_input("Port", value=smtp["port"], min_value=1, max_value=65535, step=1)
        with smtp_tls_col:
            tls_options = ["starttls", "ssl", "none"]
            tls_idx = tls_options.index(smtp["tls_mode"]) if smtp["tls_mode"] in tls_options else 0
            smtp_tls_mode = st.selectbox(
                "TLS Mode",
                options=tls_options,
                index=tls_idx,
                format_func=lambda x: {
                    "starttls": "STARTTLS (works with any port, requires auth)",
                    "ssl": "SSL/TLS (works with any port, requires auth)",
                    "none": "None (open relay, no auth required)",
                }[x],
            )

        smtp_username = st.text_input("SMTP Username", value=smtp["username"])
        smtp_password = st.text_input("SMTP Password", value=smtp["password"], type="password")

        if st.button("💾 Save SMTP Settings", type="primary"):
            config_manager.update_smtp_settings(
                host=smtp_host,
                port=int(smtp_port),
                username=smtp_username,
                password=smtp_password,
                tls_mode=smtp_tls_mode,
            )
            st.success("Saved.")

# ---------------------------------------------------------------------------
# Debug Logging (admin only)
# ---------------------------------------------------------------------------

if is_admin:
    with st.container(border=True):
        st.subheader("🐛 Debug Logging")
        st.info(
            "When enabled, all Grafana API calls (URL, org_id, status code) and "
            "internal decisions are printed to the terminal and Python logger at DEBUG level. "
            "Disable this for normal production use — enable only when troubleshooting."
        )
        debug_currently_on = config_manager.get_debug_mode()
        debug_toggle = st.toggle(
            "Enable debug logging",
            value=debug_currently_on,
            key="debug_mode_toggle",
        )
        if debug_toggle != debug_currently_on:
            config_manager.set_debug_mode(debug_toggle)
            st.success(f"Debug logging {'enabled' if debug_toggle else 'disabled'}.")
            st.rerun()

# ---------------------------------------------------------------------------
# Change Password (all users)
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("🔑 Change Password")

    with st.form("change_password_form"):
        current_pwd = st.text_input("Current Password", type="password")
        new_pwd = st.text_input("New Password", type="password")
        confirm_pwd = st.text_input("Confirm Password", type="password")
        submit_pwd = st.form_submit_button("Change Password", type="primary", use_container_width=True)

        if submit_pwd:
            password_error = validate_password(new_pwd)
            if not current_pwd or not new_pwd:
                st.error("All fields required")
            elif new_pwd != confirm_pwd:
                st.error("New passwords don't match")
            elif password_error:
                st.error(password_error)
            elif change_password(st.session_state.current_user, current_pwd, new_pwd):
                log_event("password_changed", st.session_state.current_user, "self")
                st.success("✅ Password changed")
            else:
                st.error("❌ Current password incorrect")

# ---------------------------------------------------------------------------
# User Management (admin only)
# ---------------------------------------------------------------------------

if is_admin:
    with st.container(border=True):
        st.subheader("👥 User Management")

        st.markdown("**Current Users:**")
        for user in list_users():
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                role_badge = "🔑 admin" if user["role"] == "admin" else "👤 user"
                st.write(f"{user['username']} — {role_badge}")
            with col2:
                if st.button("🔄 Reset", key=f"reset_{user['username']}", use_container_width=True):
                    st.session_state[f"show_reset_{user['username']}"] = True
            with col3:
                if user["username"] != st.session_state.current_user:
                    if st.button("🗑️ Delete", key=f"delete_{user['username']}", use_container_width=True):
                        if delete_user(user["username"]):
                            log_event("user_deleted", st.session_state.current_user, user["username"])
                            st.success(f"✅ {user['username']} deleted")
                            st.rerun()
                        else:
                            st.error("❌ Cannot delete the last remaining admin account")

        # Reset password forms shown inline
        for user in list_users():
            if st.session_state.get(f"show_reset_{user['username']}", False):
                st.markdown(f"**Reset password for {user['username']}:**")
                with st.form(f"reset_form_{user['username']}"):
                    new_pwd_admin = st.text_input(
                        "New Password", type="password", key=f"new_pwd_{user['username']}"
                    )
                    confirm_admin = st.text_input(
                        "Confirm", type="password", key=f"confirm_{user['username']}"
                    )
                    if st.form_submit_button("Set Password", type="primary"):
                        reset_error = validate_password(new_pwd_admin)
                        if new_pwd_admin != confirm_admin:
                            st.error("Passwords don't match")
                        elif reset_error:
                            st.error(reset_error)
                        else:
                            reset_password(user["username"], new_pwd_admin)
                            log_event(
                                "password_reset", st.session_state.current_user, user["username"]
                            )
                            st.success("✅ Password updated")
                            st.session_state[f"show_reset_{user['username']}"] = False
                            st.rerun()

        st.divider()

        st.markdown("**Create New User:**")
        with st.form("create_user_form"):
            new_username = st.text_input("Username")
            new_password = st.text_input("Password", type="password")
            new_role = st.selectbox("Role", ["user", "admin"])
            if st.form_submit_button("➕ Create User", type="primary"):
                create_error = validate_password(new_password)
                if not new_username or not new_password:
                    st.error("Username and password required")
                elif create_error:
                    st.error(create_error)
                elif create_user(new_username, new_password, new_role):
                    log_event("user_created", st.session_state.current_user, new_username)
                    st.success(f"✅ User {new_username} created")
                    st.rerun()
                else:
                    st.error("Username already exists")
