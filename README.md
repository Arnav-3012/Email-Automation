# Grafana Reporter

A local automation tool that pulls data from a Grafana instance, generates PDF reports from selected dashboard panels, and emails them to a configured list of recipients on a schedule.

---

## What it does

- Connects to any Grafana instance on your local network using a service account API token
- Lets you browse folders, dashboards, and panels through a web UI and select exactly what goes into each report
- Builds polished PDF reports with cover pages, panel screenshots, and per-panel data tables
- Emails them automatically on a daily or weekly schedule — via Outlook on Windows, or a debug HTML preview on Mac

---

## Tech stack

| Purpose | Library | Platform |
|---|---|---|
| UI | Streamlit | All |
| Grafana API | requests | All |
| Data processing | pandas | All |
| Panel screenshots | Selenium + webdriver-manager (headless Chrome) | All |
| PDF generation | ReportLab (PLATYPUS) | All |
| PDF in-browser preview | pdf2image (+ poppler system package) | All |
| Scheduling | APScheduler (BackgroundScheduler) | All |
| Email — classic Outlook | pywin32 (`win32com`) | **Windows only** |
| Email — SMTP fallback / Mac | smtplib (built-in) | All |

---

## Prerequisites

- Python 3.10+
- Google Chrome installed (for Selenium panel screenshots)
- **Windows — classic Outlook send:** Microsoft Outlook installed and signed in (or configure SMTP instead)
- A running Grafana instance accessible on your network
- A Grafana service account token with at least Viewer permissions

### Platform-specific dependencies

| Package | Platform | Why |
|---|---|---|
| `pywin32` | **Windows only** | Drives the local Outlook app for email sends via `win32com`. Skipped automatically on Mac/Linux. |
| `pdf2image` | All platforms | Converts PDF pages to images for in-browser preview. **Requires poppler** (see below). |

**Installing poppler (required by pdf2image):**

- **Mac:** `brew install poppler`
- **Windows:** Download the [poppler Windows binaries](https://github.com/oschwartz10612/poppler-windows/releases), extract to e.g. `C:\poppler`, and add `C:\poppler\Library\bin` to your system PATH.
- **Linux:** `sudo apt-get install poppler-utils`

> `pywin32` is already marked `; sys_platform == "win32"` in `requirements.txt` so `pip install -r requirements.txt` works on Mac and Linux without errors.

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
    "api_key": "your-service-account-token",
    "username": "your-grafana-username",
    "password": "your-grafana-password"
  }
}
```

- `url` — the base URL of your Grafana instance (no trailing slash)
- `api_key` — a Grafana service account token (Settings → Service Accounts)
- `username` / `password` — used by Selenium to log in and take panel screenshots

You can also configure everything through the **Settings** page in the UI instead of editing the file directly.

---

## Running the app

```bash
streamlit run main.py
```

The UI opens at [http://localhost:8501](http://localhost:8501).

To trigger a job manually from the command line:

```bash
python runner.py --job job_001
```

---

## How to use

1. **Settings** — enter your Grafana URL, API key, and login credentials. Click "Test connection" to verify.
2. **Browse Grafana** — expand folders, click a dashboard, tick the panels you want, then click "Add to job".
3. **New Job** — give the job a name, set the PDF title (use `{date}` as a placeholder), choose a schedule, pick recipients from your contact book, and save.
4. **Dashboard** — see all scheduled jobs, their last run status, and next scheduled time. Use "Run now" to trigger a job immediately.
5. **Contacts** — manage the recipient list (name, email, department).

---

## Email configuration

The app picks an email method automatically based on your `config.json` smtp block:

| Scenario | `force_smtp` | SMTP host | What happens |
|---|---|---|---|
| **Windows — classic Outlook** | `false` | empty | Sends via `win32com` (local Outlook app). Outlook must be open and signed in. |
| **Windows — new Outlook / COM fails** | `true` | set | Skips Outlook, sends directly via SMTP relay. |
| **Mac / Linux** | either | set | Sends via SMTP (Mailtrap for dev, Gmail or internal relay for prod). |

### Fallback behaviour on Windows

If `force_smtp` is `false`, the app tries `win32com` first. If Outlook's COM interface fails for any reason (new Outlook, COM registration issue, Outlook not running), the app automatically retries via SMTP. The fallback is printed to the console — no silent failures.

### SMTP setup options

**Mailtrap (recommended for Mac/dev testing):**
Sign up at [mailtrap.io](https://mailtrap.io) → Inboxes → SMTP credentials. Emails land in a sandbox inbox — nothing reaches real recipients.
```json
"smtp": { "host": "sandbox.smtp.mailtrap.io", "port": 587, "username": "...", "password": "...", "force_smtp": false }
```

**Gmail:**
Enable 2FA on your Google account → Security → App Passwords → generate a 16-character password.
```json
"smtp": { "host": "smtp.gmail.com", "port": 587, "username": "you@gmail.com", "password": "your-16-char-app-password", "force_smtp": false }
```

**Windows — new Outlook / internal SMTP relay:**
Ask IT for your office relay hostname. Internal relays typically use port 25 with no authentication.
```json
"smtp": { "host": "mail.office.local", "port": 25, "username": "", "password": "", "force_smtp": true }
```

**Windows — classic Outlook (no SMTP needed):**
Leave host empty and `force_smtp` false. The app uses Outlook directly.
```json
"smtp": { "host": "", "port": 587, "username": "", "password": "", "force_smtp": false }
```

---

## Scheduling behaviour

APScheduler runs inside the Streamlit process. This means:

- **The app must be running for scheduled jobs to fire.** If the Streamlit process is stopped, no emails are sent.
- On the production Windows PC, keep the terminal (or a startup script) running with `streamlit run main.py`.
- Jobs are persisted in `config.json` — they reload automatically each time the app starts.

---

## Security cautions

- **Never commit `config.json` or `contacts.json`** — they contain your Grafana credentials and email addresses. Both files are in `.gitignore`.
- Use a Grafana **service account token** with the minimum required permissions (Viewer role is enough for reading dashboards).
- The app is designed for **local network use only**. Do not expose port 8501 to the internet.

---

## File structure

```
grafana_reporter/
├── main.py                    # Streamlit entry point
├── runner.py                  # Standalone job runner (used by scheduler + CLI)
├── config.json                # Your local config (gitignored)
├── contacts.json              # Your local contacts (gitignored)
├── config.example.json        # Template — safe to commit
├── contacts.example.json      # Template — safe to commit
├── requirements.txt
│
├── output/                    # Generated PDFs (gitignored)
│   └── debug/                 # Mock email HTML files (Mac dev mode)
│
└── app/
    ├── pages/
    │   ├── 0_Home.py
    │   ├── 1_Dashboard.py     # Job list, run-now, pause/resume
    │   ├── 2_Contacts.py      # Contact book CRUD
    │   ├── 3_Browse_Grafana.py# Folder → dashboard → panel picker
    │   ├── 4_New_Job.py       # Job builder
    │   └── 5_Settings.py      # Grafana connection settings
    │
    ├── grafana_client.py      # Grafana REST API calls
    ├── data_fetcher.py        # Panel query execution (/api/ds/query)
    ├── screenshot_taker.py    # Selenium headless Chrome panel screenshots
    ├── pdf_builder.py         # ReportLab PDF assembly
    ├── mailer.py              # Platform-aware email sender
    ├── scheduler.py           # APScheduler job management
    ├── config_manager.py      # config.json read/write
    └── contact_manager.py     # contacts.json read/write
```

---

## Known limitations

- **App must stay running for scheduled emails** — no background service or system cron is used.
- **Chrome required** — Selenium uses headless Chrome for panel screenshots. If Chrome is not installed or the version mismatches, screenshots will fall back to a plain "Panel unavailable" placeholder image.
- **MySQL datasource only** — the data fetcher assumes panels use raw SQL (`rawSql` field). Other datasource types are not currently supported.
- **Single Outlook profile** — on Windows, `win32com` uses whichever Outlook profile is currently open. Multiple accounts are not handled.
- **LAN only** — the app assumes Grafana is reachable on a private network. No proxy or VPN configuration is built in.
