"""reportlab PLATYPUS PDF builder for Grafana Reporter."""

import io
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

_PAGE_W, _PAGE_H = A4
_MARGIN = 1.5 * cm                        # ~42 pt — tighter for more image area
_CONTENT_W = _PAGE_W - 2 * _MARGIN        # ~510 pt
_FOOTER_Y = 0.45 * cm
_BOTTOM_MARGIN = _MARGIN + 0.75 * cm      # ~63 pt — room for footer line

# Height available to the image on a full overview page.
# Reserves 16 pt for a single caption line above the image.
_OVERVIEW_CAPTION_H = 16
_OVERVIEW_IMG_H = _PAGE_H - _MARGIN - _BOTTOM_MARGIN - _OVERVIEW_CAPTION_H


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build(
    job_config: dict[str, Any],
    panels_data: list[dict[str, Any]],
    dashboard_screenshots: dict[str, bytes | None] | None = None,
    output_dir: str = "output/",
) -> str:
    """Build a PDF from job config and panel screenshots.

    panels_data items carry keys: dashboard_uid, dashboard_title, folder_path,
    panel_id, panel_title, screenshot (list[bytes]).
    dashboard_screenshots maps uid → full-page PNG bytes (or None).
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    today = date.today()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_path = str(Path(output_dir) / _make_filename(job_config.get("name", "report"), today))

    shots = dashboard_screenshots or {}
    unique_dashboards = len(set(p["dashboard_uid"] for p in panels_data))
    has_overview = any(v for v in shots.values())

    if unique_dashboards == 1 and not has_overview:
        _build_single_page(out_path, job_config, panels_data, today, timestamp)
    else:
        _build_multi_page(out_path, job_config, panels_data, today, timestamp, shots)

    return out_path


# ---------------------------------------------------------------------------
# Filename + title helpers
# ---------------------------------------------------------------------------

def _make_filename(job_name: str, today: date) -> str:
    """Return {job_name}_{YYYY-MM-DD}.pdf with spaces replaced by underscores."""
    return f"{job_name.replace(' ', '_')}_{today.strftime('%Y-%m-%d')}.pdf"


def _resolve_title(job_config: dict[str, Any], today: date) -> str:
    """Replace {date} in pdf_title with today's formatted date."""
    tmpl = job_config.get("pdf_title") or job_config.get("name", "Report")
    return tmpl.replace("{date}", today.strftime("%Y-%m-%d"))


# ---------------------------------------------------------------------------
# Single-page builder — canvas-based, 1 dashboard, no overview shot
# ---------------------------------------------------------------------------

def _build_single_page(
    out_path: str,
    job_config: dict[str, Any],
    panels_data: list[dict[str, Any]],
    today: date,
    timestamp: str,
) -> None:
    """Render all panels on one A4 page, images scaled equally to fill height."""
    c = pdfcanvas.Canvas(out_path, pagesize=A4)

    y = _PAGE_H - _MARGIN

    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(colors.black)
    c.drawString(_MARGIN, y - 17, _resolve_title(job_config, today))
    y -= 23

    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(_MARGIN, y - 9, f"{job_config.get('name', '')}  ·  Generated: {timestamp}")
    y -= 14

    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.setLineWidth(0.5)
    c.line(_MARGIN, y - 3, _PAGE_W - _MARGIN, y - 3)
    y -= 9

    N = len(panels_data)
    title_h = 10
    gap_h = 4
    available_h = y - _BOTTOM_MARGIN
    per_img_h = max((available_h - (title_h + gap_h) * N) / N, 0) if N else 0

    for panel in panels_data:
        png_bytes = (panel.get("screenshot") or [b""])[0]
        c.setFont("Helvetica-Bold", 6.5)
        c.setFillColor(colors.black)
        c.drawString(_MARGIN, y - title_h + 2, panel.get("panel_title", "Panel"))
        y -= title_h

        if png_bytes and per_img_h > 0:
            try:
                pil_img = PILImage.open(io.BytesIO(png_bytes))
                pw, ph = pil_img.size
                scale = min(_CONTENT_W / pw, per_img_h / ph)
                c.drawImage(
                    ImageReader(io.BytesIO(png_bytes)),
                    _MARGIN, y - ph * scale,
                    width=pw * scale, height=ph * scale,
                )
            except Exception:
                pass

        y -= per_img_h + gap_h

    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawString(_MARGIN, _FOOTER_Y, f"Generated by Grafana Reporter · {timestamp}")
    c.drawRightString(_PAGE_W - _MARGIN, _FOOTER_Y, "Page 1")
    c.save()


# ---------------------------------------------------------------------------
# Multi-page builder — PLATYPUS
# ---------------------------------------------------------------------------

def _build_multi_page(
    out_path: str,
    job_config: dict[str, Any],
    panels_data: list[dict[str, Any]],
    today: date,
    timestamp: str,
    dashboard_screenshots: dict[str, bytes | None] | None = None,
) -> None:
    """Render a multi-page report. Each dashboard opens with a full-page overview."""
    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_BOTTOM_MARGIN,
        title=_resolve_title(job_config, today),
        author="Grafana Reporter",
    )

    styles = _make_styles()
    story = _content_pages(panels_data, styles, dashboard_screenshots or {})

    doc.build(
        story,
        onFirstPage=_make_footer(timestamp),
        onLaterPages=_make_footer(timestamp),
    )


# ---------------------------------------------------------------------------
# Paragraph styles
# ---------------------------------------------------------------------------

def _make_styles() -> dict[str, ParagraphStyle]:
    """Build and return all named ParagraphStyles used in the report."""
    base = getSampleStyleSheet()
    return {
        "overview_caption": ParagraphStyle(
            "rpt_overview_caption",
            parent=base["Normal"],
            fontSize=8.5,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#222222"),
            leading=10,
            spaceAfter=4,
        ),
        "section_title": ParagraphStyle(
            "rpt_section_title",
            parent=base["Normal"],
            fontSize=10,
            fontName="Helvetica-Bold",
            textColor=colors.black,
            leading=12,
        ),
        "folder_path": ParagraphStyle(
            "rpt_folder_path",
            parent=base["Normal"],
            fontSize=7,
            textColor=colors.HexColor("#666666"),
            leading=9,
            spaceBefore=2,
            spaceAfter=3,
        ),
        "panel_title": ParagraphStyle(
            "rpt_panel_title",
            parent=base["Normal"],
            fontSize=8.5,
            fontName="Helvetica-Bold",
            textColor=colors.black,
            leading=10,
            spaceBefore=7,
            spaceAfter=2,
        ),
    }


# ---------------------------------------------------------------------------
# Footer callback
# ---------------------------------------------------------------------------

def _make_footer(timestamp: str):
    """Return an onPage callback that draws the footer on every page."""
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(
            _MARGIN, _FOOTER_Y,
            f"Generated by Grafana Reporter · {timestamp}",
        )
        canvas.drawRightString(_PAGE_W - _MARGIN, _FOOTER_Y, f"Page {doc.page}")
        canvas.restoreState()
    return _footer


# ---------------------------------------------------------------------------
# Content pages
# ---------------------------------------------------------------------------

def _content_pages(
    panels_data: list[dict[str, Any]],
    styles: dict[str, ParagraphStyle],
    dashboard_screenshots: dict[str, bytes | None] | None = None,
) -> list:
    """Build the full story: for each dashboard, overview page then panel detail."""
    story: list = []
    shots = dashboard_screenshots or {}

    groups: dict[str, dict[str, Any]] = OrderedDict()
    for panel in panels_data:
        uid = panel["dashboard_uid"]
        if uid not in groups:
            groups[uid] = {
                "title": panel.get("dashboard_title", uid),
                "folder_path": panel.get("folder_path", ""),
                "panels": [],
            }
        groups[uid]["panels"].append(panel)

    first_db = True
    for uid, group in groups.items():
        if not first_db:
            story.append(PageBreak())
        first_db = False

        # Full-page overview
        full_png = shots.get(uid)
        if full_png:
            story.extend(_overview_page(full_png, group["title"], group["folder_path"], styles))

        # Panel detail section
        story.extend(_section_header(group["title"], group["folder_path"], styles))
        for panel in group["panels"]:
            story.append(_panel_block(panel, styles))

    return story


def _overview_page(
    full_png: bytes,
    title: str,
    folder_path: str,
    styles: dict[str, ParagraphStyle],
) -> list:
    """Single-line caption then the full dashboard image filling the page."""
    img_obj = _make_overview_image(full_png)
    if img_obj is None:
        return []

    caption_parts = [title]
    if folder_path:
        caption_parts.append(folder_path)

    return [
        Paragraph("  ·  ".join(caption_parts), styles["overview_caption"]),
        img_obj,
        PageBreak(),
    ]


def _section_header(
    title: str,
    folder_path: str,
    styles: dict[str, ParagraphStyle],
) -> list:
    """Bold section title with a hairline rule underneath."""
    header = Table(
        [[Paragraph(title, styles["section_title"])]],
        colWidths=[_CONTENT_W],
    )
    header.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#aaaaaa")),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    items: list = [header]
    if folder_path:
        items.append(Paragraph(folder_path, styles["folder_path"]))
    items.append(Spacer(1, 0.1 * cm))
    return items


def _panel_block(
    panel: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> KeepTogether:
    """Panel title followed by all screenshot chunks, kept together."""
    elements: list = [Paragraph(panel.get("panel_title", "Panel"), styles["panel_title"])]
    for png_bytes in (panel.get("screenshot") or []):
        img_obj = _make_image(png_bytes)
        elements.append(img_obj)
        elements.append(Spacer(1, 3))
    elements.append(Spacer(1, 0.2 * cm))
    return KeepTogether(elements)


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _make_overview_image(png_bytes: bytes) -> Image | None:
    """Scale PNG to fill the overview page (constrained to content width × overview height)."""
    if not png_bytes:
        return None
    try:
        pil_img = PILImage.open(io.BytesIO(png_bytes))
        pw, ph = pil_img.size
        scale = min(_CONTENT_W / pw, _OVERVIEW_IMG_H / ph)
        return Image(io.BytesIO(png_bytes), width=pw * scale, height=ph * scale)
    except Exception:
        return None


def _make_image(png_bytes: bytes) -> Image | Spacer:
    """Scale PNG to full content width, preserving aspect ratio."""
    if not png_bytes:
        return Spacer(1, 0.1 * cm)
    try:
        pil_img = PILImage.open(io.BytesIO(png_bytes))
        pw, ph = pil_img.size
        img_h = _CONTENT_W * (ph / pw)
        return Image(io.BytesIO(png_bytes), width=_CONTENT_W, height=img_h)
    except Exception:
        return Spacer(1, 0.1 * cm)
