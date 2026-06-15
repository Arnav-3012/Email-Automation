"""reportlab PLATYPUS PDF builder for Grafana Reporter."""

import io
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
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
_MARGIN = 2.0 * cm
_CONTENT_W = _PAGE_W - 2 * _MARGIN   # ~481 pt
_FOOTER_Y = 0.6 * cm                  # y position of footer text baseline
_BOTTOM_MARGIN = _MARGIN + 1.0 * cm   # bottom margin (room for footer)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build(
    job_config: dict[str, Any],
    panels_data: list[dict[str, Any]],
    output_dir: str = "output/",
) -> str:
    """Build a PDF report from the job config and panel screenshots.

    panels_data is a list of dicts with keys: dashboard_uid, dashboard_title,
    folder_path, panel_id, panel_title, screenshot (PNG bytes).
    Routes to single-page canvas builder when all panels share one dashboard,
    otherwise builds a full multi-page PLATYPUS document.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    today = date.today()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_path = str(Path(output_dir) / _make_filename(job_config.get("name", "report"), today))

    unique_dashboards = len(set(p["dashboard_uid"] for p in panels_data))

    if unique_dashboards == 1:
        _build_single_page(out_path, job_config, panels_data, today, timestamp)
    else:
        _build_multi_page(out_path, job_config, panels_data, today, timestamp)

    return out_path


# ---------------------------------------------------------------------------
# Filename + title helpers
# ---------------------------------------------------------------------------

def _make_filename(job_name: str, today: date) -> str:
    """Return {job_name}_{YYYY-MM-DD}.pdf with spaces replaced by underscores."""
    return f"{job_name.replace(' ', '_')}_{today.strftime('%Y-%m-%d')}.pdf"


def _resolve_title(job_config: dict[str, Any], today: date) -> str:
    """Replace the {date} placeholder in pdf_title with today's date string."""
    tmpl = job_config.get("pdf_title") or job_config.get("name", "Report")
    return tmpl.replace("{date}", today.strftime("%Y-%m-%d"))


# ---------------------------------------------------------------------------
# Single-page builder — canvas-based for guaranteed single-page output
# ---------------------------------------------------------------------------

def _build_single_page(
    out_path: str,
    job_config: dict[str, Any],
    panels_data: list[dict[str, Any]],
    today: date,
    timestamp: str,
) -> None:
    """Render all panels on one A4 page, scaling images equally to fit."""
    c = pdfcanvas.Canvas(out_path, pagesize=A4)

    # Compact header
    y = _PAGE_H - _MARGIN

    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(colors.black)
    c.drawString(_MARGIN, y - 22, _resolve_title(job_config, today))
    y -= 28

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.black)
    meta = f"{job_config.get('name', '')}  ·  Generated: {timestamp}"
    c.drawString(_MARGIN, y - 11, meta)
    y -= 17

    # Thin rule below header
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.line(_MARGIN, y - 4, _PAGE_W - _MARGIN, y - 4)
    y -= 12

    # Calculate image pool: remaining height minus per-panel title rows and gaps
    N = len(panels_data)
    panel_title_h = 13   # pt per panel title line
    gap_h = 5            # pt gap below each panel image
    total_overhead = (panel_title_h + gap_h) * N
    available_h = y - _BOTTOM_MARGIN
    per_img_h = max((available_h - total_overhead) / N, 0) if N > 0 else 0

    # Draw each panel — screenshot is list[bytes]; use first chunk for single-page layout
    for panel in panels_data:
        panel_title = panel.get("panel_title", "Panel")
        screenshot = panel.get("screenshot") or []
        png_bytes = screenshot[0] if screenshot else b""

        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(colors.black)
        c.drawString(_MARGIN, y - panel_title_h + 3, panel_title)
        y -= panel_title_h

        if png_bytes and per_img_h > 0:
            try:
                pil_img = PILImage.open(io.BytesIO(png_bytes))
                pw, ph = pil_img.size
                scale = min(_CONTENT_W / pw, per_img_h / ph)
                img_w = pw * scale
                img_h = ph * scale
                c.drawImage(
                    ImageReader(io.BytesIO(png_bytes)),
                    _MARGIN, y - img_h,
                    width=img_w, height=img_h,
                )
            except Exception:
                pass

        y -= per_img_h + gap_h

    # Footer
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.black)
    c.drawString(_MARGIN, _FOOTER_Y, f"Generated by Grafana Reporter · {timestamp}")
    c.drawRightString(_PAGE_W - _MARGIN, _FOOTER_Y, "Page 1")

    c.save()


# ---------------------------------------------------------------------------
# Multi-page builder — PLATYPUS, black and white
# ---------------------------------------------------------------------------

def _build_multi_page(
    out_path: str,
    job_config: dict[str, Any],
    panels_data: list[dict[str, Any]],
    today: date,
    timestamp: str,
) -> None:
    """Render a full multi-page report with cover page and per-dashboard sections."""
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
    story: list = []
    story.extend(_cover_page(job_config, panels_data, styles, today, timestamp))
    story.extend(_content_pages(panels_data, styles))

    doc.build(
        story,
        onFirstPage=_make_footer(timestamp),
        onLaterPages=_make_footer(timestamp),
    )


# ---------------------------------------------------------------------------
# Paragraph styles — black and white
# ---------------------------------------------------------------------------

def _make_styles() -> dict[str, ParagraphStyle]:
    """Build and return all named ParagraphStyles used in the report."""
    base = getSampleStyleSheet()
    return {
        "report_title": ParagraphStyle(
            "rpt_report_title",
            parent=base["Normal"],
            fontSize=22,
            leading=28,
            fontName="Helvetica-Bold",
            textColor=colors.black,
            alignment=TA_LEFT,
            spaceAfter=14,
        ),
        "cover_meta": ParagraphStyle(
            "rpt_cover_meta",
            parent=base["Normal"],
            fontSize=10,
            textColor=colors.black,
            spaceAfter=4,
        ),
        "cover_label": ParagraphStyle(
            "rpt_cover_label",
            parent=base["Normal"],
            fontSize=8,
            fontName="Helvetica-Bold",
            textColor=colors.black,
            spaceBefore=16,
            spaceAfter=4,
        ),
        "cover_item": ParagraphStyle(
            "rpt_cover_item",
            parent=base["Normal"],
            fontSize=10,
            textColor=colors.black,
            leftIndent=12,
            spaceAfter=4,
        ),
        "section_title": ParagraphStyle(
            "rpt_section_title",
            parent=base["Normal"],
            fontSize=13,
            fontName="Helvetica-Bold",
            textColor=colors.black,
        ),
        "folder_path": ParagraphStyle(
            "rpt_folder_path",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.black,
            spaceBefore=3,
            spaceAfter=6,
        ),
        "panel_title": ParagraphStyle(
            "rpt_panel_title",
            parent=base["Normal"],
            fontSize=11,
            fontName="Helvetica-Bold",
            textColor=colors.black,
            spaceBefore=10,
            spaceAfter=4,
        ),
    }


# ---------------------------------------------------------------------------
# Footer callback
# ---------------------------------------------------------------------------

def _make_footer(timestamp: str):
    """Return an onPage callback that draws the footer on every page."""
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.black)
        canvas.drawString(
            _MARGIN, _FOOTER_Y,
            f"Generated by Grafana Reporter · {timestamp}",
        )
        canvas.drawRightString(_PAGE_W - _MARGIN, _FOOTER_Y, f"Page {doc.page}")
        canvas.restoreState()
    return _footer


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------

def _cover_page(
    job_config: dict[str, Any],
    panels_data: list[dict[str, Any]],
    styles: dict[str, ParagraphStyle],
    today: date,
    timestamp: str,
) -> list:
    """Build the cover page story elements, ending with a PageBreak."""
    story: list = []

    story.append(Spacer(1, 2.5 * cm))
    story.append(Paragraph(_resolve_title(job_config, today), styles["report_title"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(f"Job: {job_config.get('name', '')}", styles["cover_meta"]))
    story.append(Paragraph(f"Generated: {timestamp}", styles["cover_meta"]))
    story.append(Spacer(1, 1.0 * cm))
    story.append(Paragraph("DASHBOARDS INCLUDED", styles["cover_label"]))

    seen: set[str] = set()
    for panel in panels_data:
        uid = panel.get("dashboard_uid", "")
        if uid in seen:
            continue
        seen.add(uid)
        dtitle = panel.get("dashboard_title", uid)
        fpath = panel.get("folder_path", "")
        suffix = f"  ({fpath})" if fpath else ""
        story.append(Paragraph(f"•  {dtitle}{suffix}", styles["cover_item"]))

    story.append(PageBreak())
    return story


# ---------------------------------------------------------------------------
# Content pages
# ---------------------------------------------------------------------------

def _content_pages(
    panels_data: list[dict[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> list:
    """Build all dashboard section headers and panel blocks after the cover page."""
    story: list = []

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

    first = True
    for uid, group in groups.items():
        if not first:
            story.append(PageBreak())
        first = False

        story.extend(_section_header(group["title"], group["folder_path"], styles))

        for panel in group["panels"]:
            story.append(_panel_block(panel, styles))

    return story


def _section_header(
    title: str,
    folder_path: str,
    styles: dict[str, ParagraphStyle],
) -> list:
    """Return a bold black section header with a thin rule underneath."""
    header = Table(
        [[Paragraph(title, styles["section_title"])]],
        colWidths=[_CONTENT_W],
    )
    header.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.75, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    items: list = [header]
    if folder_path:
        items.append(Paragraph(folder_path, styles["folder_path"]))
    items.append(Spacer(1, 0.2 * cm))
    return items


def _panel_block(
    panel: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> KeepTogether:
    """Return a KeepTogether block containing the panel title and all screenshot chunks."""
    elements: list = [Paragraph(panel.get("panel_title", "Panel"), styles["panel_title"])]
    for png_bytes in (panel.get("screenshot") or []):
        img_obj = _make_image(png_bytes)
        elements.append(img_obj)
        elements.append(Spacer(1, 6))
    elements.append(Spacer(1, 0.4 * cm))
    return KeepTogether(elements)


def _make_image(png_bytes: bytes) -> Image | Spacer:
    """Convert PNG bytes to a full-content-width reportlab Image, preserving aspect ratio."""
    if not png_bytes:
        return Spacer(1, 0.1 * cm)
    try:
        pil_img = PILImage.open(io.BytesIO(png_bytes))
        pw, ph = pil_img.size
        img_h = _CONTENT_W * (ph / pw)
        return Image(io.BytesIO(png_bytes), width=_CONTENT_W, height=img_h)
    except Exception:
        return Spacer(1, 0.1 * cm)
