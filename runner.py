"""Standalone job runner — chains Grafana fetch → screenshots → PDF → CSV → email."""

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app import (
    config_manager,
    contact_manager,
    data_fetcher,
    grafana_client,
    mailer,
    pdf_builder,
    screenshot_taker,
)

TABLE_TYPES = {"table", "datagrid", "table-old"}

# Anchored to the project root so it's correct regardless of the cwd the
# process was launched from (e.g. a Task Scheduler entry without a "Start in"
# directory set to this folder).
OUTPUT_DIR = Path(__file__).parent / "output"


def _log(msg: str) -> None:
    """Print a timestamped log line to stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _resolve_title(overrides: dict[str, str], key: str, fallback: str) -> str:
    """Resolve a display name with explicit-override (blank-aware) semantics.

    A *present* key always wins, even if its value is "" — that means the
    user saw the field pre-filled in the job form and deliberately cleared
    it, so an empty header is what they asked for. Only a *missing* key
    (jobs saved before display-name pre-fill existed) falls back to the
    real Grafana title.
    """
    if key in overrides:
        return overrides[key]
    return fallback


def run_job(job_id: str) -> None:
    """Execute a single reporter job end-to-end.

    Chart panels go into a PDF. Table panels are exported as individual CSVs
    with metadata headers. Both are emailed to the configured recipients.
    Updates last_run / last_status on both success and failure.
    """
    job = config_manager.get_job(job_id)
    if not job:
        _log(f"Job {job_id!r} not found — aborting.")
        return

    _log(f"Starting job: {job['name']}")
    grafana_settings = config_manager.get_grafana_settings()
    recipients = contact_manager.resolve_ids(job.get("recipient_ids", []))
    panel_names = job.get("panel_names", {})
    dashboard_names = job.get("dashboard_names", {})

    attachments: list[str] = []
    panels_data: list[dict[str, Any]] = []       # chart panels → PDF
    table_panels_data: list[dict[str, Any]] = [] # table panels → CSV
    dashboard_screenshots: dict[str, bytes | None] = {}  # uid → full-page PNG

    try:
        for dashboard in job.get("dashboards", []):
            uid: str = dashboard["uid"]
            panel_ids: list[int] = dashboard.get("panels", [])
            _log(f"Fetching dashboard: {dashboard.get('title', uid)}")

            dashboard_json = grafana_client.get_dashboard(uid)
            grafana_dashboard_title = (
                dashboard_json.get("dashboard", {}).get("title")
                or dashboard.get("title")
                or uid
            )
            dashboard_title: str = _resolve_title(dashboard_names, uid, grafana_dashboard_title)
            all_panels = grafana_client.get_panels(dashboard_json)
            selected = [p for p in all_panels if p["id"] in panel_ids]
            chart_panels = [p for p in selected if p.get("type") not in TABLE_TYPES]
            table_panels = [p for p in selected if p.get("type") in TABLE_TYPES]

            # Full dashboard overview screenshot
            try:
                dashboard_screenshots[uid] = screenshot_taker.capture_full_dashboard(
                    uid, grafana_settings
                )
                _log(f"Full dashboard captured: {dashboard.get('title', uid)}")
            except Exception as e:
                _log(f"Full dashboard capture failed: {e}")
                dashboard_screenshots[uid] = None

            # Screenshots for chart panels
            if chart_panels:
                chart_ids = [p["id"] for p in chart_panels]
                screenshots = screenshot_taker.capture_panels(uid, chart_ids, grafana_settings)
                for panel in chart_panels:
                    panel_title = _resolve_title(
                        panel_names, f"{uid}_{panel['id']}",
                        panel.get("title", f"Panel {panel['id']}"),
                    )
                    panels_data.append({
                        "dashboard_uid": uid,
                        "dashboard_title": dashboard_title,
                        "folder_path": dashboard.get("folder_path", ""),
                        "panel_id": panel["id"],
                        "panel_title": panel_title,
                        "screenshot": screenshots.get(panel["id"], screenshot_taker._unavailable_png()),
                    })

            # Screenshots for table panels — added to PDF alongside chart panels
            if table_panels:
                table_ids = [p["id"] for p in table_panels]
                table_screenshots = screenshot_taker.capture_panels(uid, table_ids, grafana_settings)
                for panel in table_panels:
                    panel_title = _resolve_title(
                        panel_names, f"{uid}_{panel['id']}",
                        panel.get("title", f"Panel {panel['id']}"),
                    )
                    panels_data.append({
                        "dashboard_uid": uid,
                        "dashboard_title": dashboard_title,
                        "folder_path": dashboard.get("folder_path", ""),
                        "panel_id": panel["id"],
                        "panel_title": panel_title,
                        "screenshot": table_screenshots.get(panel["id"], screenshot_taker._unavailable_png()),
                    })

            # Data fetch for table panels → CSV
            for panel in table_panels:
                try:
                    df = data_fetcher.fetch_panel_data(panel, grafana_client)
                    if df is not None and not df.empty:
                        panel_title = _resolve_title(
                            panel_names, f"{uid}_{panel['id']}", panel["title"]
                        )
                        table_panels_data.append({
                            "panel": {
                                **panel,
                                "title": panel_title,
                            },
                            "dashboard_title": dashboard_title,
                            "folder_path": dashboard.get("folder_path", ""),
                            "dashboard_json": dashboard_json,
                            "df": df,
                        })
                except ValueError as e:
                    # Unsupported datasource — screenshot already captured above
                    _log(f"Table panel '{panel['title']}': datasource not supported for CSV, screenshot included in PDF")
                except Exception as e:
                    _log(f"Table panel {panel['title']} failed: {e}")

        _log(f"Screenshots captured: {len(panels_data)} panel(s) for PDF, {len(table_panels_data)} table panel(s) for CSV")

        # Build PDF (chart panels + table panel screenshots)
        if panels_data:
            pdf_path = pdf_builder.build(job, panels_data, dashboard_screenshots)
            attachments.append(pdf_path)
            _log(f"PDF built: {pdf_path}")

        # Build individual CSV attachments with metadata headers
        if table_panels_data:
            today = date.today().strftime("%Y-%m-%d")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            for item in table_panels_data:
                # The display name can be deliberately blank (user cleared
                # it for "no header label"), but a filename can't be — fall
                # back to the panel id so the CSV still gets a sane name.
                filename_base = item["panel"]["title"] or f"panel_{item['panel']['id']}"
                safe_title = filename_base.replace(" ", "_").replace("/", "-")
                csv_path = str(OUTPUT_DIR / f"{safe_title}_{today}.csv")

                dash_json = item.get("dashboard_json", {})
                dashboard = dash_json.get("dashboard", {})
                field_config = item["panel"].get("fieldConfig", {})
                field_defaults = field_config.get("defaults", {})
                overrides = field_config.get("overrides", [])

                # ── Basic info ──────────────────────────────────────
                metadata = [
                    ["Dashboard:", item["dashboard_title"]],
                    ["Generated:", datetime.now().strftime("%Y-%m-%d %H:%M")],
                ]

                desc = item["panel"].get("description", "")
                if desc:
                    metadata.append(["Description:", desc])

                # ── Report Configuration ─────────────────────────────
                unit = field_defaults.get("unit", "")
                decimals = field_defaults.get("decimals", "")
                field_min = field_defaults.get("min", "")
                field_max = field_defaults.get("max", "")
                display_name = field_defaults.get("displayName", "")
                color_mode = (field_defaults.get("color") or {}).get("mode", "")

                config_rows = []
                if unit:
                    config_rows.append(["Unit:", unit])
                if display_name:
                    config_rows.append(["Display Name:", display_name])
                if decimals != "" and decimals is not None:
                    config_rows.append(["Decimals:", str(decimals)])
                if field_min != "" and field_min is not None:
                    config_rows.append(["Min Value:", str(field_min)])
                if field_max != "" and field_max is not None:
                    config_rows.append(["Max Value:", str(field_max)])
                if color_mode:
                    config_rows.append(["Color Mode:", color_mode])

                if config_rows:
                    metadata.append([])
                    metadata.append(["--- Report Configuration ---", ""])
                    metadata.extend(config_rows)

                # ── Column Formatting ────────────────────────────────
                if overrides:
                    override_rows = []
                    for override in overrides:
                        matcher = override.get("matcher", {})
                        matcher_value = matcher.get("options", "")
                        properties = override.get("properties", [])
                        prop_parts = []
                        for prop in properties:
                            prop_id = prop.get("id", "")
                            prop_value = prop.get("value", "")
                            if prop_id and prop_value != "" and prop_value is not None:
                                readable_id = {
                                    "unit": "Unit",
                                    "decimals": "Decimals",
                                    "displayName": "Display Name",
                                    "custom.width": "Column Width",
                                    "custom.align": "Alignment",
                                    "color": "Color",
                                    "min": "Min",
                                    "max": "Max",
                                    "thresholds": None,
                                }.get(prop_id, prop_id)

                                if readable_id is None:
                                    continue

                                if isinstance(prop_value, dict):
                                    prop_value = str(prop_value)

                                prop_parts.append(f"{readable_id}={prop_value}")

                        if matcher_value and prop_parts:
                            override_rows.append([
                                f"{matcher_value}:",
                                ", ".join(prop_parts)
                            ])

                    if override_rows:
                        metadata.append([])
                        metadata.append(["--- Column Formatting ---", ""])
                        metadata.extend(override_rows)

                # ── Applied Filters (Dashboard Variables) ────────────
                template_list = dashboard.get("templating", {}).get("list", [])
                filter_rows = []
                for var in template_list:
                    var_name = var.get("name", "")
                    current = var.get("current", {})
                    var_value = current.get("text") or current.get("value", "")
                    if var_name and var_value:
                        if isinstance(var_value, list):
                            var_value = ", ".join(str(v) for v in var_value)
                        if str(var_value).lower() not in ("all", "$__all", ""):
                            filter_rows.append([f"{var_name}:", str(var_value)])

                if filter_rows:
                    metadata.append([])
                    metadata.append(["--- Applied Filters ---", ""])
                    metadata.extend(filter_rows)

                # ── Data section ─────────────────────────────────────
                metadata.extend([
                    [],
                    ["--- Report Data ---", ""],
                    [],
                ])

                # ── Write CSV ────────────────────────────────────────
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    for row in metadata:
                        writer.writerow(row)
                    writer.writerow(item["df"].columns.tolist())
                    for _, row in item["df"].iterrows():
                        writer.writerow(row.tolist())

                attachments.append(csv_path)
                _log(f"CSV built: {item['panel']['title']} → {csv_path}")

        # Send email with all attachments
        custom_subject = job.get("email_subject", "").strip()
        subject = (
            custom_subject if custom_subject
            else job["name"] + " – " + date.today().strftime("%d %b %Y")
        )
        custom_message = job.get("email_message", "")
        mailer.send(recipients, subject, attachments, custom_message)
        _log(f"Email sent to {len(recipients)} recipient(s)")

        config_manager.update_job_run_status(
            job_id,
            last_run=datetime.now().isoformat(timespec="seconds"),
            last_status="success",
        )
        _log("Job completed successfully")

    except Exception as exc:
        config_manager.update_job_run_status(
            job_id,
            last_run=datetime.now().isoformat(timespec="seconds"),
            last_status="failed",
        )
        _log(f"Job FAILED: {exc}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a Grafana Reporter job manually.")
    parser.add_argument("--job", required=True, metavar="JOB_ID", help="ID of the job to run")
    args = parser.parse_args()

    try:
        run_job(args.job)
    except Exception:
        sys.exit(1)
