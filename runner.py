"""Standalone job runner — chains Grafana fetch → screenshots → PDF → email."""

import argparse
import sys
from datetime import date, datetime
from typing import Any

from app import config_manager, contact_manager, grafana_client, mailer, pdf_builder, screenshot_taker


def _log(msg: str) -> None:
    """Print a timestamped log line to stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run_job(job_id: str) -> None:
    """Execute a single reporter job end-to-end.

    Loads the job from config, captures panel screenshots, builds a PDF, and
    emails it to the configured recipients. Updates last_run / last_status on
    both success and failure.
    """
    # 1. Load job config
    job = config_manager.get_job(job_id)
    if job is None:
        _log(f"Job not found: {job_id!r} — aborting.")
        return

    _log(f"Starting job: {job['name']}")

    # 2. Load Grafana settings
    grafana_settings = config_manager.get_grafana_settings()

    # 3. Resolve recipient IDs → full contact dicts
    recipients = contact_manager.resolve_ids(job.get("recipient_ids", []))

    panels_data: list[dict[str, Any]] = []

    try:
        # 4. Per-dashboard: fetch metadata and screenshots
        for dash_cfg in job.get("dashboards", []):
            dash_uid: str = dash_cfg["uid"]
            requested_panel_ids: list[int] = dash_cfg.get("panels", [])
            folder_path: str = dash_cfg.get("folder_path", "")

            _log(f"Fetching dashboard: {dash_cfg.get('title', dash_uid)}")

            # 4a. Get full dashboard JSON from Grafana
            dashboard_json = grafana_client.get_dashboard(dash_uid)

            # Extract the human-readable title from the API response
            dashboard_title: str = (
                dashboard_json.get("dashboard", {}).get("title")
                or dash_cfg.get("title", dash_uid)
            )

            # 4b. Get panel metadata list
            all_panels = grafana_client.get_panels(dashboard_json)

            # Build a lookup: panel_id → panel title
            panel_title_map: dict[int, str] = {
                p["id"]: p.get("title", f"Panel {p['id']}") for p in all_panels
            }

            # 4c. Filter to only the panel IDs requested in the job
            panel_ids_to_capture = [
                pid for pid in requested_panel_ids if pid in panel_title_map
            ]

            # 4d. Capture screenshots
            screenshots = screenshot_taker.capture_panels(
                dash_uid, panel_ids_to_capture, grafana_settings
            )
            _log(f"Screenshots captured: {len(screenshots)} panels")

            # 4e. Assemble panels_data entries in the order requested
            for panel_id in panel_ids_to_capture:
                panels_data.append({
                    "dashboard_uid": dash_uid,
                    "dashboard_title": dashboard_title,
                    "folder_path": folder_path,
                    "panel_id": panel_id,
                    "panel_title": panel_title_map.get(panel_id, f"Panel {panel_id}"),
                    "screenshot": screenshots.get(panel_id, b""),
                })

        # 5. Build PDF
        pdf_path = pdf_builder.build(job, panels_data)
        _log(f"PDF built: {pdf_path}")

        # 6. Build email subject
        subject = f"{job['name']} – {date.today().strftime('%d %b %Y')}"

        # 7. Send email
        mailer.send(recipients, subject, pdf_path)
        _log(f"Email sent to {len(recipients)} recipient(s)")

        # 8. Update status — success
        now = datetime.now().isoformat(timespec="seconds")
        config_manager.update_job_run_status(job_id, last_run=now, last_status="success")
        _log("Job completed successfully")

    except Exception as exc:
        now = datetime.now().isoformat(timespec="seconds")
        config_manager.update_job_run_status(job_id, last_run=now, last_status="failed")
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
