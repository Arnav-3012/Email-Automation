# Recovery Guide

Quick fixes for the most common ways this app can get stuck. All paths below are relative to the project root (the folder containing `main.py`).

---

## A user forgot their password

Users cannot reset their own password without the old one. An **admin** must do it for them:

1. Log in as an admin account.
2. Go to **Settings → User Management**.
3. Click **🔄 Reset** next to the user's name, enter a new password, and confirm.

The user can then log in with the new password and change it themselves from **Settings → Change Password**.

---

## The admin forgot their password (and no other admin exists)

There is no "forgot password" link — this app is designed for local network use only. To recover:

1. Stop the app (close the terminal running `streamlit run main.py`).
2. Delete `app_users.json` from the project root.
3. Restart the app: `streamlit run main.py`.
4. Since no user accounts now exist, the **setup wizard** appears automatically — create a new admin account.

**This wipes all existing user accounts** (not jobs, contacts, or config — those live in separate files). Any jobs previously owned by deleted users will show as "legacy job, no owner" on the Dashboard and can be reassigned to the new admin from there.

---

## `app_users.json` is corrupted (app won't start / login page is blank or errors)

If the file has invalid JSON (e.g. from a crash mid-write, or manual editing gone wrong):

1. Stop the app.
2. Delete `app_users.json`.
3. Restart the app — the setup wizard will run again to create a fresh admin account.

Same data-loss note as above applies: only user accounts are lost, not jobs/contacts/config.

If you want to avoid losing accounts, first try opening `app_users.json` in a text editor and checking for an obvious syntax error (a missing comma or brace) before deleting it — a corrupted file is often just one bad edit away from working again.

---

## Permission denied errors (can't read/write config.json, contacts.json, app_users.json, audit_log.json, or output/)

This usually means the folder or file is read-only, or owned by a different OS user than the one running Streamlit:

1. Confirm the account running `streamlit run main.py` has write access to the project folder.
2. On Windows: right-click the project folder → Properties → Security, and confirm the current user has Modify permission.
3. On Linux/Mac: `chmod -R u+rw .` from the project root (adjust ownership with `chown` if needed).
4. If a file was created by a different user/process (e.g. copied from another machine), delete and let the app recreate it, or fix ownership directly.

---

## Lost or corrupted `audit_log.json`

This file only stores the login/account-management history — it does not affect any app functionality (auth, jobs, screenshots, email all work without it).

1. Stop the app.
2. Delete `audit_log.json`.
3. Restart — the app recreates it automatically as soon as the next auditable event happens (login, logout, password change, user create/delete).

---

## `ImportError: No module named 'bcrypt'` (or similar for other dependencies)

The virtual environment doesn't have the required packages installed:

```bash
pip install -r requirements.txt
```

If you're not using a virtual environment, activate one first (see the Installation section in `README.md`) — installing packages globally is not recommended and can conflict with other Python projects.

On Windows, if `pywin32` fails to import even after installing, run its post-install script:

```bash
python Scripts/pywin32_postinstall.py -install
```

---

## Emergency contact guidance

If none of the above resolves the issue:

1. Check the terminal output where `streamlit run main.py` is running — errors are printed there with a traceback.
2. If debug logging is available, enable it from **Settings → Debug Logging** (admin only) and reproduce the issue — this prints detailed request/response info to the console.
3. Capture the exact error message and the last ~20 lines of console output before contacting whoever manages this deployment (typically the person who set up `config.json`/SMTP/Grafana credentials).
4. Do not share `config.json`, `contacts.json`, `app_users.json`, or `audit_log.json` contents when asking for help — they contain credentials, recipient emails, and password hashes. Redact before sharing.
