# Grafana Reporter

A local automation tool that pulls data from a Grafana instance, generates PDF reports (and CSV exports for table panels) from selected dashboard panels, and emails them to a configured list of recipients on a schedule — behind a login.

---

## What it does

- Connects to any Grafana instance on your network using Basic Auth (username/password), with multi-organisation support
- Lets you browse organisations → folders → subfolders → dashboards → panels through a web UI and select exactly what goes into each report
- Builds polished, multi-page PDF reports: a full-dashboard overview screenshot, then each selected panel with a clean title and screenshot — packed multiple-per-page when there's room, given its own page when there isn't
- Exports table-type panels as individual CSVs with a metadata header (applied filters, column formatting, units) instead of just a screenshot
- Emails everything automatically on a daily, weekly, or monthly schedule — via Outlook on Windows, or SMTP everywhere (with automatic Outlook → SMTP fallback)
- Gates the whole UI behind a login system with bcrypt-hashed passwords, role-based admin user management, and an audit log

---

## Tech stack

| Purpose | Library | Platform |
|---|---|---|
| UI | Streamlit | All |
| Authentication | bcrypt (password hashing) | All |
| Grafana API | requests | All |
| Data processing | pandas | All |
| Panel/dashboard screenshots | Selenium + webdriver-manager (headless Chrome, falling back to Edge, falling back to `mss` screen capture) | All |
| PDF generation | ReportLab (PLATYPUS) | All |
| PDF in-browser preview | pdf2image (+ poppler system package) | All |
| Scheduling | APScheduler (BackgroundScheduler) | All |
| Email — classic Outlook | pywin32 (`win32com`) | **Windows only** |
| Email — SMTP | smtplib (built-in) | All |

---

## Prerequisites

- Python 3.10+
- Google Chrome installed (preferred for screenshots). If Chrome isn't available, the app automatically falls back to Edge, then to a raw screen capture (`mss`) of whatever browser opens the panel URL — see [Screenshot capture & fallback chain](#screenshot-capture--fallback-chain).
- **Windows — classic Outlook send:** Microsoft Outlook installed and signed in (or configure SMTP instead — see [Email configuration](#email-configuration))
- A running Grafana instance accessible on your network
- A Grafana **user account** with at least Viewer permissions on the orgs/dashboards you want to report on (this app authenticates with Basic Auth, not an API token — see [Configuration](#configuration))

### Platform-specific dependencies

| Package | Platform | Why |
|---|---|---|
| `pywin32` | **Windows only** | Drives the local Outlook app for email sends via `win32com`. Skipped automatically on Mac/Linux (`; sys_platform == "win32"` in `requirements.txt`). |
| `pdf2image` | All platforms | Converts PDF pages to images for in-browser preview. **Requires poppler** (see below). |
| `mss` | All platforms | Last-resort screenshot fallback if both Chrome and Edge Selenium fail to launch. |
| `bcrypt` | All platforms | Hashes and verifies user account passwords for the login system. |

**Installing poppler (required by pdf2image):**

- **Mac:** `brew install poppler`
- **Windows:** Download the [poppler Windows binaries](https://github.com/oschwartz10612/poppler-windows/releases), extract to e.g. `C:\poppler`, and add `C:\poppler\Library\bin` to your system PATH.
- **Linux:** `sudo apt-get install poppler-utils`

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/your-username/grafana-reporter.git
cd grafana-reporter

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Mac / Linux
.venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

> **Windows note:** `pywin32` requires a post-install step if installed from pip directly:
> ```
> python Scripts/pywin32_postinstall.py -install
> ```
> This is handled automatically in most virtual environment setups.

---

## Running the app

```bash
streamlit run main.py
```

The UI opens at [http://localhost:8501](http://localhost:8501).

> **Run this from the project root.** All persisted files (`config.json`, `contacts.json`, `app_users.json`, `audit_log.json`, the `output/` folder) resolve to paths anchored to the project directory regardless of the shell's current working directory, so this is not strictly required for correctness — but it's the supported, tested way to launch it.

To trigger a job manually from the command line (bypasses the scheduler and the login gate — useful for testing):

```bash
python runner.py --job job_001
```

---

## First-time setup & authentication

The app is gated behind a login. On the very first launch — before `app_users.json` exists — Streamlit shows a one-time **setup wizard** instead of the login form:

1. Choose a username and password (8–72 characters; bcrypt has a hard 72-character limit).
2. Submitting creates the first account with the `admin` role and logs you in immediately.
3. From then on, every launch shows a normal login form.

### How the gate works

- Every page (`main.py` and everything in `pages/`) independently calls `app.auth_manager.require_auth()` as its very first Streamlit call. This matters because Streamlit's multipage sidebar lets a user navigate directly to any page's URL — only gating `main.py` would leave every other page open to anyone who skips the home page.
- Session state (`authenticated`, `current_user`) persists for the life of the browser session; logging out or closing the browser/tab clears it.
- A "🚪 Logout" button and the current username appear in the sidebar on every page once logged in.

### Account management (Settings page)

- **Change Password** — any logged-in user can change their own password (requires the current password).
- **User Management** (admin only) — create new users (role `user` or `admin`), reset another user's password without knowing their old one, or delete a user.
- **Last-admin protection** — the app refuses to delete the only remaining admin account, to prevent a total lockout with no recovery path.

### Audit log

Every login attempt (success and failure), logout, password change/reset, and user create/delete is appended to `audit_log.json` with a timestamp, event type, acting username, and details. There's no UI viewer for it yet — inspect the file directly if you need to review activity.

### Files this creates

| File | Contents | Gitignored? |
|---|---|---|
| `app_users.json` | Usernames, bcrypt password hashes, roles, timestamps | Yes |
| `audit_log.json` | Append-only event log | Yes |

`app_users.example.json` is committed as a schema reference — copy it for documentation purposes only, it is **not** read by the app (the app creates `app_users.json` itself via the setup wizard).

### Known limitations of the auth system

- **No brute-force protection.** Failed logins are audit-logged but not rate-limited or locked out after N attempts.
- **No concurrent-write locking** on `app_users.json` / `audit_log.json`. Fine for the single-PC, low-concurrency use case this app targets; would need attention if multiple people hit it simultaneously.

---

## Configuration

Copy the example config and fill in your values:

```bash
cp config.example.json config.json
cp contacts.example.json contacts.json
```

Edit `config.json`:

```json
{
  "grafana": {
    "url": "http://your-grafana-url:3000",
    "username": "your-grafana-username",
    "password": "your-grafana-password",
    "org_id": 1
  },
  "smtp": {
    "host": "",
    "port": 587,
    "username": "",
    "password": "",
    "force_smtp": false,
    "tls_mode": "starttls"
  },
  "jobs": []
}
```

- `url` — the base URL of your Grafana instance (no trailing slash)
- `username` / `password` — Basic Auth credentials used for **every** Grafana API call (browsing folders, fetching panel data, screenshots) — there is no separate API-token field
- `org_id` — which Grafana organisation to operate in. Switch organisations from the Browse Grafana page instead of editing this by hand; it updates here automatically.
- `smtp.tls_mode` — one of `"starttls"`, `"ssl"`, `"none"` — see [Email configuration](#email-configuration)

You can also configure everything through the **Settings** page in the UI instead of editing the file directly. Note: `config.example.json` as committed currently lists a stale `api_key` field and is missing `org_id`/`tls_mode` — it does not match the real schema above; treat the schema in this README, not that file, as the source of truth until it's updated.

---

## How to use

1. **Settings** — enter your Grafana URL and login credentials, then "Test Connection" to verify (this also logs the detected Grafana version to the console). Configure SMTP here too, and manage your account / other users in the same page.
2. **Browse Grafana** — pick an organisation (if you have access to more than one), then cascade through folder → subfolder → dashboard → panels. Tick the panels you want and "Add to Job".
3. **New Job** — name the job, set a PDF title (`{date}` is replaced with today's date), pick a schedule (daily/weekly/monthly), choose recipients, optionally set a custom email subject/message and rename individual panels as they'll appear in the PDF/CSV, then "Save & Schedule". Existing jobs can be reopened here via "Edit" from the Dashboard page.
4. **Dashboard** — see active/total job counts and today's success count, plus every job's schedule summary and last-run status. Per job: **Run now** (runs in a background thread immediately), **Pause/Resume**, **Edit**, **Delete**.
5. **Contacts** — manage the recipient list (name, email, department); validated and reusable across jobs.

---

## Email configuration

The app picks an email method automatically based on `config.json`'s `smtp` block:

| Scenario | `force_smtp` | SMTP host | What happens |
|---|---|---|---|
| **Windows — classic Outlook** | `false` | empty | Sends via `win32com` (local Outlook app). Outlook must be open and signed in. |
| **Windows — new Outlook / COM fails** | `true` | set | Skips Outlook, sends directly via SMTP. |
| **Mac / Linux** | n/a | set | Always sends via SMTP — there is no Outlook path and no mock/debug mode on non-Windows platforms; a working SMTP host is required to send mail at all. |

### Fallback behaviour on Windows

If `force_smtp` is `false`, the app tries `win32com` first. If Outlook's COM interface fails for any reason (new Outlook, COM registration issue, Outlook not running), the app automatically retries via SMTP, printing the fallback reason to the console — no silent failures.

### SMTP setup options

`tls_mode` must be set explicitly to one of `starttls`, `ssl`, or `none` — there is no auto-detect; sending raises a clear error telling you to pick one in Settings if it's left unset.

**Gmail:**
Enable 2FA on your Google account → Security → App Passwords → generate a 16-character password.
```json
"smtp": { "host": "smtp.gmail.com", "port": 587, "username": "you@gmail.com", "password": "your-16-char-app-password", "force_smtp": false, "tls_mode": "starttls" }
```

**Internal SMTP relay (no Outlook, or non-Windows):**
Ask IT for your office relay hostname. Internal relays typically use port 25 with no authentication.
```json
"smtp": { "host": "mail.office.local", "port": 25, "username": "", "password": "", "force_smtp": true, "tls_mode": "none" }
```

**Windows — classic Outlook (no SMTP needed):**
Leave host empty and `force_smtp` false. The app uses Outlook directly.
```json
"smtp": { "host": "", "port": 587, "username": "", "password": "", "force_smtp": false, "tls_mode": "starttls" }
```

---

## Grafana version compatibility

This app targets Grafana 9.1+ through current versions and includes a few specific compatibility shims:

- **Version detection** — every successful "Test Connection" logs `[grafana_client] Connected — Grafana version: X.Y.Z` to the console, via `/api/health`.
- **Org-switching fallback** — multi-org requests normally use the `X-Grafana-Org-Id` header. If a request comes back `401`/`403` (seen on some older 9.x builds that reject the header), the client automatically retries once with `?orgId=` as a query parameter before giving up. This only fires for non-default orgs (`org_id != 1`); it cannot detect the rarer case of an old server silently ignoring the header and serving the wrong org's data without erroring.
- **Folder children** — tries `GET /api/folders/{uid}/children` (Grafana 10+) first; on a `404` it falls back to `GET /api/search?folderUid=...&type=dash-folder` (Grafana 8/9), normalising the result shape so the rest of the app doesn't need to know which path was used.
- **Datasource references are UID-based throughout** — `/api/datasources/uid/{uid}`-style access only, no numeric datasource IDs anywhere in the codebase. This matters because Grafana 9+ deprecated numeric datasource IDs and newer versions disable those endpoints by default.

---

## Screenshot capture & fallback chain

Panel and full-dashboard screenshots are captured in this order, each tier attempted only if the previous one fails to even launch:

1. **Chrome** (headless, via Selenium + webdriver-manager)
2. **Edge** (headless, via Selenium)
3. **`mss`** raw screen capture — opens the panel URL in the system's default browser and grabs the whole screen. This is a last resort: it requires a visible desktop session (won't work over most headless/remote setups) and is far less precise than the Selenium paths.

Within the Selenium paths, tall panels are split into 2000px-high chunks so nothing gets clipped, and every captured image (full panels, tall-panel chunks, and full-dashboard overviews) is automatically trimmed of excess background whitespace before being handed to the PDF builder — this alone typically shrinks report length noticeably without cropping any chart content. If a panel fails to capture at all, a plain "Panel unavailable" placeholder image is used instead so report generation never fully aborts over one bad panel.

---

## PDF report layout

- Each dashboard included in a job opens with a full-page screenshot overview, followed by a section listing each selected panel with its title and screenshot.
- **Smart packing:** multiple panels share a page when there's still at least ~1/3 of a page of comfortable room left after the previous one; otherwise the next panel starts a fresh page rather than being squeezed into a sliver of space.
- Any panel image — including a maximum-height 2000px screenshot chunk — is automatically capped to fit within a single page's height, so an unusually tall panel (e.g. a long table render) gets its own page instead of crashing the build.
- Table-type panels (`table`, `datagrid`, `table-old`) are *also* exported as individual CSVs with a metadata header block (dashboard name, generation time, applied dashboard variable filters, column units/formatting) — their screenshot still goes in the PDF, but the CSV is the more useful artifact for that data.
- A single dashboard with no full-page overview shot (e.g. when overview capture fails) is rendered through a different, simpler one-page-only path that shrinks all of that dashboard's panels to fit on exactly one page — this is a separate, older code path from the smart-packing one above and does not paginate.

---

## Scheduling behaviour

APScheduler runs inside the Streamlit process. This means:

- **The app must be running for scheduled jobs to fire.** If the Streamlit process is stopped, no emails are sent.
- On the production Windows PC, keep the terminal (or a startup script) running with `streamlit run main.py`.
- Jobs are persisted in `config.json` — they reload automatically each time the app starts, but only those with `status: "active"`.
- Supported frequencies: `daily` and `weekly` (both run on a configurable set of weekdays at a configurable time), and `monthly` (runs on the 1st of every month at a configurable time).

---

## Security cautions

- **Never commit `config.json`, `contacts.json`, `app_users.json`, or `audit_log.json`** — they contain Grafana/SMTP credentials, recipient email addresses, password hashes, and login activity respectively. All four are listed in `.gitignore` (the `.gitignore` lists each filename explicitly — there is **no** blanket `*.json` rule, so any new sensitive JSON file must be added to it explicitly or it will be tracked by git).
- Use a Grafana account with the minimum required permissions for the dashboards being reported on (Viewer is enough for reading dashboards and running queries).
- Passwords are hashed with bcrypt (never stored or logged in plaintext); the password policy is 8–72 characters, enforced everywhere a password is set (setup wizard, self-service change, admin reset, new user creation).
- The login system has no brute-force lockout — see [First-time setup & authentication](#first-time-setup--authentication).
- The app is designed for **local network use only**. Do not expose port 8501 to the internet — the login system is a basic access gate, not a hardened internet-facing auth stack (no HTTPS, no MFA, no rate limiting, no session expiry beyond browser-session lifetime).

---

## File structure

```
grafana_reporter/
├── main.py                    # Streamlit entry point — setup wizard, login gate, home page
├── runner.py                  # Standalone job runner (used by scheduler + CLI)
├── config.json                # Your local config (gitignored)
├── contacts.json              # Your local contacts (gitignored)
├── app_users.json             # User accounts + bcrypt password hashes (gitignored)
├── audit_log.json             # Login/account-management event log (gitignored)
├── config.example.json        # Template — safe to commit (currently stale, see Configuration)
├── contacts.example.json      # Template — safe to commit
├── app_users.example.json     # Schema reference only — not read by the app
├── requirements.txt
│
├── output/                    # Generated PDFs and CSVs (gitignored)
│
├── pages/                      # Streamlit auto-discovers these as separate pages/sidebar entries
│   ├── 1_Dashboard.py          # Job list, run-now, pause/resume, edit, delete
│   ├── 2_Contacts.py           # Contact book CRUD
│   ├── 3_Browse_Grafana.py     # Org → folder → subfolder → dashboard → panel picker
│   ├── 4_New_Job.py            # Job builder / editor
│   └── 5_Settings.py           # Grafana + SMTP settings, change password, user management
│
└── app/
    ├── auth_manager.py        # User accounts, login/session gate, audit log
    ├── grafana_client.py      # Grafana REST API calls
    ├── data_fetcher.py        # Panel query execution (/api/ds/query → pandas)
    ├── screenshot_taker.py    # Chrome → Edge → mss screenshot fallback chain, whitespace trim
    ├── pdf_builder.py         # ReportLab PDF assembly, smart page packing
    ├── mailer.py               # Platform-aware email sender (Outlook / SMTP)
    ├── scheduler.py            # APScheduler job management
    ├── config_manager.py      # config.json read/write
    └── contact_manager.py     # contacts.json read/write
```

Every module that persists a file anchors its path to the project root via `Path(__file__).parent[.parent]` rather than a relative string — this is intentional and load-bearing: it means the app behaves identically regardless of the working directory the process was launched from (a shortcut, a Task Scheduler entry, a different shell), with one exception noted under [Known limitations](#known-limitations) below.

---

## Known limitations

- **App must stay running for scheduled emails** — no background service or system cron is used.
- **Chrome/Edge required for accurate screenshots** — the `mss` fallback works without either, but requires a visible desktop session and is much less precise (whole-screen capture rather than a cropped element render).
- **MySQL/TestData datasources only** for CSV export — `data_fetcher.py` only knows how to build queries for SQL-style (`rawSql`) panels and Grafana's built-in TestData datasource. Other datasource types will still get a PDF screenshot but no CSV export, and `fetch_panel_data` raises a caught `ValueError` for them.
- **Single Outlook profile** — on Windows, `win32com` uses whichever Outlook profile is currently open. Multiple accounts are not handled.
- **LAN only** — the app assumes Grafana is reachable on a private network. No proxy or VPN configuration is built in.
- **No brute-force protection on login**, and **no file-locking** around concurrent writes to the JSON data files — both acceptable for the single-PC, low-concurrency use case this targets, but worth knowing before relying on this for anything higher-stakes.
- **One pre-existing relative path**: `app/pdf_builder.py`'s single-dashboard-no-overview rendering path and the rest of the codebase are anchored to the project root, but this has not been re-verified after every recent change — if you see a report or CSV land in an unexpected `output/` folder, check the cwd the process was actually launched from first.
- **`config.example.json` is currently out of sync** with the real config schema (lists a non-existent `api_key` field, missing `org_id` and `tls_mode`) — use the schema documented in [Configuration](#configuration) above, not that file, until it's updated.
