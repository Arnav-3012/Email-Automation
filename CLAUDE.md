# CLAUDE.md — Grafana Reporter
> Instruction file for Claude Code. Read this fully before writing any code.

---

## Project overview

A local automation tool that pulls data from a **Grafana** instance (office LAN),
generates **PDF reports** from selected dashboard panels, and emails them via
**Outlook** to a configured list of named recipients on a schedule.

- Built and tested on **macOS** (developer machine)
- Deployed to **Windows** office PC (production)
- UI runs in the browser via **Streamlit** (`localhost:8501`)
- Scheduling via **APScheduler** (BackgroundScheduler, cross-platform)
- All data stored locally as JSON files — no cloud, no external APIs
- Panel screenshots are taken via **Selenium headless Chrome** — exact Grafana look and feel

---

## Confirmed tech stack

| Purpose | Library | Notes |
|---|---|---|
| UI | `streamlit` | Multi-page app, localhost only |
| Grafana API | `requests` | LAN URL + Bearer token |
| Data processing | `pandas` | Parse /api/ds/query responses |
| Panel screenshots | `selenium` + `webdriver-manager` | Headless Chrome, logs in to Grafana |
| Placeholder images | `Pillow` | White PNG with text when a panel fails |
| PDF generation | `reportlab` | Cover page + per-panel sections |
| Scheduling | `apscheduler` | BackgroundScheduler inside Streamlit |
| Email (Windows) | `pywin32` (win32com) | Uses local Outlook app, no SMTP |
| Email (Mac/dev) | built-in mock | Saves debug HTML to `output/debug/` |

```
pip install streamlit requests pandas selenium webdriver-manager Pillow reportlab apscheduler pywin32
```

---

## Project file structure

```
grafana_reporter/
│
├── CLAUDE.md                  ← this file
├── main.py                    ← streamlit entry point (streamlit run main.py)
├── runner.py                  ← standalone script called by APScheduler
│
├── config.json                ← auto-created on first run
├── contacts.json              ← auto-created on first run
│
├── output/                    ← generated PDFs stored here
│   └── debug/                 ← mock emails saved here (Mac dev mode)
│
├── requirements.txt
│
└── app/
    ├── pages/
    │   ├── 1_Dashboard.py     ← job list, status, run-now
    │   ├── 2_Contacts.py      ← contact book CRUD
    │   ├── 3_Browse_Grafana.py← folder tree → dashboard → panel picker
    │   ├── 4_New_Job.py       ← job builder form
    │   └── 5_Settings.py      ← Grafana URL, API key, credentials, test connection
    │
    ├── grafana_client.py      ← all Grafana REST API calls
    ├── data_fetcher.py        ← executes panel queries via /api/ds/query
    ├── screenshot_taker.py    ← Selenium headless Chrome → panel PNG bytes
    ├── pdf_builder.py         ← reportlab PDF assembly
    ├── mailer.py              ← platform-aware email sender
    ├── scheduler.py           ← APScheduler setup and job management
    ├── config_manager.py      ← read/write config.json
    └── contact_manager.py     ← read/write contacts.json
```

---

## Data schemas

### config.json

```json
{
  "grafana": {
    "url": "http://grafana.office.local:3000",
    "api_key": "eyJ...",
    "username": "admin",
    "password": "secret"
  },
  "jobs": [
    {
      "id": "job_001",
      "name": "Daily Finance Summary",
      "pdf_title": "Finance Summary — {date}",
      "status": "active",
      "dashboards": [
        {
          "uid": "abc123",
          "title": "Revenue Q2",
          "folder_path": "Finance / Q2 Reports",
          "panels": [1, 3, 5]
        }
      ],
      "recipient_ids": ["c001", "c002"],
      "schedule": {
        "frequency": "daily",
        "time": "08:30",
        "days": ["mon", "tue", "wed", "thu", "fri"]
      },
      "last_run": null,
      "last_status": null
    }
  ]
}
```

### contacts.json

```json
{
  "contacts": [
    {
      "id": "c001",
      "name": "Rahul Sharma",
      "email": "rahul@company.com",
      "department": "Finance"
    }
  ]
}
```

---

## Grafana API reference (MySQL datasource)

All requests use header: `Authorization: Bearer {api_key}`

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Connection test |
| `/api/folders` | GET | Top-level folders |
| `/api/folders/{uid}/children` | GET | Sub-folders (Grafana 10+) |
| `/api/search?folderUid={uid}&type=dash-db` | GET | Dashboards inside a folder |
| `/api/dashboards/uid/{uid}` | GET | Full dashboard JSON (contains panel definitions + queries) |
| `/api/ds/query` | POST | Execute panel queries, get raw data back |
| `/api/datasources` | GET | List datasources (to get MySQL datasource UID) |

### /api/ds/query payload (MySQL panel)

```json
{
  "queries": [
    {
      "datasource": { "uid": "mysql-datasource-uid" },
      "rawSql": "SELECT time, value FROM metrics WHERE $__timeFilter(time)",
      "format": "time_series",
      "refId": "A",
      "intervalMs": 60000,
      "maxDataPoints": 500
    }
  ],
  "from": "now-24h",
  "to": "now"
}
```

Response comes back as `results.A.frames` — parse with pandas.

### Extracting panel queries from dashboard JSON

```python
dashboard = response["dashboard"]
for panel in dashboard["panels"]:
    panel_id = panel["id"]
    panel_title = panel["title"]
    panel_type = panel["type"]  # "graph", "table", "stat", "bar", etc.
    targets = panel.get("targets", [])
    datasource_uid = panel.get("datasource", {}).get("uid")
    for target in targets:
        raw_sql = target.get("rawSql", "")
```

---

## Screenshot taker — Selenium approach

- Login to Grafana via username/password (stored in config.json grafana block)
- Panel URL format: `{base_url}/d-solo/{dashboard_uid}?orgId=1&panelId={panel_id}&kiosk&theme=light`
- Reuse a single driver instance across all panels in one job run, close when done
- Wait 3 seconds after navigation for panel to fully render
- Return PNG as bytes via `get_screenshot_as_png()`
- On any error return a plain white PNG with "Panel unavailable" text (via Pillow)

---

## PDF structure (reportlab)

Each PDF report has this structure:

1. **Cover page** — Report title (from job config, `{date}` replaced), generation timestamp, job name, list of dashboards included, list of recipients
2. **Per dashboard section** — Dashboard name, folder path, Grafana URL link
3. **Per panel** — Panel title, screenshot image (PNG from Selenium), data summary below the chart
4. **Footer on every page** — "Generated by Grafana Reporter · {timestamp}" + page number

Use `reportlab.platypus` (PLATYPUS framework) for layout, not canvas directly.

---

## Mailer — platform detection

```python
import platform

def send(to_contacts: list[dict], subject: str, pdf_path: str):
    if platform.system() == "Windows":
        _outlook_send(to_contacts, subject, pdf_path)
    else:
        _mock_send(to_contacts, subject, pdf_path)
```

`_mock_send` writes a `.html` file to `output/debug/` showing exactly what would have been emailed. It also prints a clear `[MOCK EMAIL]` block to the terminal. Never raises an error on Mac.

`_outlook_send` uses `win32com.client.Dispatch("Outlook.Application")`. Outlook must be open and configured on the Windows machine.

---

## Scheduler (APScheduler)

- Use `BackgroundScheduler` from `apscheduler.schedulers.background`
- Start the scheduler once on Streamlit app startup using `st.session_state`
- Load all active jobs from `config.json` on startup
- When a job is added or edited in the UI, call `scheduler.reschedule_job()` or `scheduler.add_job()`
- Each job calls `runner.run_job(job_id)` at trigger time

```python
# scheduler.py pattern
from apscheduler.schedulers.background import BackgroundScheduler

def get_scheduler():
    if "scheduler" not in st.session_state:
        sched = BackgroundScheduler()
        sched.start()
        st.session_state.scheduler = sched
    return st.session_state.scheduler
```

---

## Runner (runner.py)

Standalone module — contains `run_job(job_id: str)` function.
Also callable directly: `python runner.py --job job_001` for manual testing.

Pipeline inside `run_job`:
1. Load job config from `config.json`
2. Resolve recipient IDs → full contact objects from `contacts.json`
3. For each dashboard in job:
   a. `grafana_client.get_dashboard(uid)` → panel metadata
   b. `screenshot_taker.capture_panels(dashboard_uid, panel_ids, grafana_settings)` → dict of panel_id → PNG bytes
4. `pdf_builder.build(job, panels_data)` → saves PDF to `output/`
5. `mailer.send(recipients, subject, pdf_path)`
6. Update `last_run` and `last_status` in `config.json`

---

## Coding conventions

- All functions have type hints and a one-line docstring
- No hardcoded strings — all configurable values come from `config.json`
- Every file that reads/writes JSON wraps it in try/except with a clear error message
- `grafana_client.py` raises a custom `GrafanaConnectionError` if the API call fails
- Streamlit pages import only from `app/` modules — no business logic in page files
- `st.session_state` is used to pass the scheduler and Grafana client across page renders
- Mac/Windows branching happens only in `mailer.py` — nowhere else
- Generated PDFs are named: `{job_name}_{YYYY-MM-DD}.pdf` (spaces → underscores)

---

## Phase build order

Build phases in this exact order. Do not skip ahead.

| Phase | What gets built |
|---|---|
| 1 | `config_manager.py` + `contact_manager.py` + `config.json` / `contacts.json` schemas |
| 2 | `grafana_client.py` — connection test, folder tree, dashboard list, panel metadata |
| 3 | `data_fetcher.py` — `/api/ds/query` for MySQL panels, returns pandas DataFrame |
| 4 | `screenshot_taker.py` — Selenium headless Chrome logs in, screenshots each panel → PNG bytes |
| 5 | `pdf_builder.py` — reportlab assembles full PDF |
| 6 | `mailer.py` — platform-aware sender, mock mode for Mac |
| 7 | `runner.py` — chains phases 2–6, callable standalone |
| 8 | `scheduler.py` — APScheduler BackgroundScheduler, loads jobs from config |
| 9 | `app/pages/5_Settings.py` — Grafana URL + API key + credentials + connection test |
| 10 | `app/pages/2_Contacts.py` — full CRUD contact book |
| 11 | `app/pages/3_Browse_Grafana.py` — folder tree + panel picker |
| 12 | `app/pages/4_New_Job.py` — job builder form, saves to config, registers with scheduler |
| 13 | `app/pages/1_Dashboard.py` — job list, next run time, last status, run-now button |
| 14 | `main.py` — Streamlit entry point, starts scheduler on launch |
| 15 | End-to-end test on Mac (mock email), then verify on Windows (real Outlook send) |

---

## Claude Code prompts (copy-paste these in order)

Use these prompts one phase at a time inside VS Code with Claude Code.
Always say "Phase X done, move to Phase X+1" before pasting the next prompt.

---

### Phase 1
```
Build Phase 1 of the Grafana Reporter project as defined in CLAUDE.md.
Create config_manager.py and contact_manager.py in app/.
Each should have: load(), save(), and for contacts also add_contact(), delete_contact(), get_all().
Auto-create config.json and contacts.json with empty defaults if they don't exist.
Follow the exact schemas in CLAUDE.md. Add type hints and docstrings.
```

### Phase 2
```
Build Phase 2. Create app/grafana_client.py.
Implement: test_connection(), get_folders(), get_subfolders(folder_uid),
get_dashboards_in_folder(folder_uid), get_dashboard(uid), get_panels(dashboard_json).
Use the Grafana API endpoints in CLAUDE.md. Raise GrafanaConnectionError on failure.
Load URL and API key from config_manager. Add type hints and docstrings.
```

### Phase 3
```
Build Phase 3. Create app/data_fetcher.py.
Implement fetch_panel_data(panel_meta, grafana_client, time_from="now-24h", time_to="now").
Extract rawSql and datasource uid from panel metadata.
POST to /api/ds/query with the MySQL payload format in CLAUDE.md.
Parse the response frames into a pandas DataFrame. Return the DataFrame.
Handle empty results gracefully.
```

### Phase 4
```
Build Phase 4. Create app/screenshot_taker.py.
Implement:
- get_driver() — headless Chrome via webdriver-manager, 1280x800, no sandbox
- login(driver, base_url, username, password) — navigates to /login, fills credentials, waits for home redirect
- take_panel_screenshot(driver, base_url, dashboard_uid, panel_id, width=800, height=400) -> bytes
  navigates to d-solo panel URL with kiosk and theme=light, waits 3s, returns PNG bytes
- capture_panels(dashboard_uid, panel_ids, grafana_settings) -> dict[int, bytes]
  creates driver once, logs in, loops panels, closes driver, returns panel_id → PNG bytes dict
- On any panel failure, store a plain white 800x400 PNG with "Panel unavailable" text via Pillow.
Type hints and docstrings on everything.
```

### Phase 5
```
Build Phase 5. Create app/pdf_builder.py using reportlab PLATYPUS.
Implement build(job_config, panels_data, output_dir="output/") -> str (file path).
panels_data is a dict of panel_id -> PNG bytes (from screenshot_taker).
Structure: cover page, per-dashboard section header, per-panel (title + screenshot image).
Footer on every page: "Generated by Grafana Reporter · {timestamp}" + page number.
Replace {date} in job pdf_title with today's date. Filename format: {job_name}_{YYYY-MM-DD}.pdf.
```

### Phase 6
```
Build Phase 6. Create app/mailer.py.
Implement send(to_contacts, subject, pdf_path).
On Windows: use win32com.client Outlook send with PDF attachment.
On Mac/Linux: write a debug HTML file to output/debug/ and print a [MOCK EMAIL] summary.
Platform detection via platform.system(). Never raise on Mac.
```

### Phase 7
```
Build Phase 7. Create runner.py in the project root.
Implement run_job(job_id: str) that chains: config load → contact resolve →
grafana fetch → screenshot capture → PDF build → email send → update last_run in config.
Also add a __main__ block: python runner.py --job job_001 for manual CLI testing.
Log each step to console with a timestamp prefix.
```

### Phase 8
```
Build Phase 8. Create app/scheduler.py.
Use APScheduler BackgroundScheduler. Implement:
- get_scheduler() — creates or retrieves scheduler from st.session_state
- load_jobs_from_config() — reads all active jobs, registers them with scheduler
- add_or_update_job(job_config) — adds or replaces a scheduler job
- remove_job(job_id)
Each job calls runner.run_job(job_id). Handle daily and weekly frequencies.
```

### Phase 9
```
Build Phase 9. Create app/pages/5_Settings.py.
Fields: Grafana Server URL, API Key (password input), Username, Password (password input).
"Save settings" button writes to config.json via config_manager.
"Test connection" button calls grafana_client.test_connection() and shows
success (green) or error (red) with the error message.
Keep it clean and minimal Streamlit layout.
```

### Phase 10
```
Build Phase 10. Create app/pages/2_Contacts.py.
Show all contacts in a table (name, email, department, jobs count placeholder).
Add contact form: name, email, department fields + Add button.
Delete button per row. On change, rewrite contacts.json via contact_manager.
Validate email format before adding. Show a note: "Saved in contacts.json on this PC".
```

### Phase 11
```
Build Phase 11. Create app/pages/3_Browse_Grafana.py.
Left column: render the Grafana folder tree using st.expander for each folder.
Clicking a dashboard stores it in st.session_state["selected_dashboard"].
Right column: show panels for the selected dashboard as checkboxes.
"Add to job" button stores selected dashboard + panel IDs in st.session_state["job_draft"].
Handle GrafanaConnectionError with a clear error message and link to Settings page.
```

### Phase 12
```
Build Phase 12. Create app/pages/4_New_Job.py.
Fields: job name, PDF title (with {date} hint), schedule (frequency + time + days).
Show dashboards already added via Browse Grafana (from st.session_state["job_draft"]).
Recipient picker: multiselect from contacts loaded via contact_manager.
"Save & Schedule" button: writes job to config.json, calls scheduler.add_or_update_job().
Generate a unique job ID (uuid4 short).
```

### Phase 13
```
Build Phase 13. Create app/pages/1_Dashboard.py.
Show 3 metric cards: active jobs, emails sent this week (from last_run logs), success rate.
Show all jobs as a list: name, folder path, schedule summary, recipients count, last run status.
"Run now" button per job calls runner.run_job(job_id) in a thread and shows a spinner.
"Pause / Resume" toggle updates status in config.json and calls scheduler.remove_job / add_job.
```

### Phase 14
```
Build Phase 14. Create main.py as the Streamlit entry point.
On startup: call scheduler.load_jobs_from_config() once using st.session_state to prevent re-runs.
Set page title, icon, and sidebar. Import and wire all pages.
Add a status indicator in the sidebar: "Scheduler running · N jobs active".
Run with: streamlit run main.py
```

### Phase 15
```
Run an end-to-end test on Mac.
Create a test script test_pipeline.py that:
1. Uses a mock Grafana response (hardcoded JSON matching the /api/ds/query format)
2. Calls data_fetcher → screenshot_taker (mock, no real Chrome) → pdf_builder → mailer (mock mode)
3. Verifies: PDF is created in output/, debug email HTML is in output/debug/
4. Prints PASS or FAIL with details for each step.
Do not make real network calls.
```

---

## Known constraints

- Do not use `display:none` or hide content in Streamlit using st.empty hacks for the main flow
- Do not use Windows Task Scheduler — APScheduler only
- Do not use SMTP — Outlook win32com on Windows, mock on Mac
- Do not call any external URLs — all traffic stays on office LAN
- MySQL is the only datasource — `rawSql` field in panel targets is always present

---

## Quick reference — starting the app

```bash
# Install dependencies
pip install streamlit requests pandas selenium webdriver-manager Pillow reportlab apscheduler pywin32

# Run
streamlit run main.py

# Test a job manually
python runner.py --job job_001
```
