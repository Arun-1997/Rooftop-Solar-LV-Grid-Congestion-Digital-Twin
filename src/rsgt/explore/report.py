"""Write the explore outputs: a machine-readable ``insights.json`` and a
self-contained ``report.html`` (figures embedded as base64, no external assets)."""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from .profile import ExploreProfile

_FIGURE_TITLES = {
    "overview": "Study-area overview",
    "construction_years": "Construction decades",
    "footprint_areas": "Footprint area distribution",
    "dsm": "AHN surface elevation (DSM)",
    "object_height": "AHN object height (DSM − DTM)",
}

_SECTION_TITLES = {
    "aoi": "Area of interest",
    "buildings": "BAG buildings",
    "bag3d": "3D BAG",
    "pc6": "PC6 aggregation units",
    "ahn": "AHN elevation",
    "capacity": "Capacity map",
    "provenance": "Provenance",
}

_CSS = """
body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;
  background:#f7f7f8;color:#1b1b1f;line-height:1.5}
.wrap{max-width:1040px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:32px 0 10px;
  border-bottom:1px solid #e3e3e6;padding-bottom:6px}
.sub{color:#6b6b73;margin:0 0 20px}
.headline{background:#eef4fd;border:1px solid #d3e2fb;border-radius:10px;padding:14px 18px;margin:18px 0}
.headline ul{margin:0;padding-left:20px}
.grid{display:flex;flex-wrap:wrap;gap:14px}
figure{margin:0;background:#fff;border:1px solid #e3e3e6;border-radius:10px;padding:10px;flex:1 1 460px}
figure img{width:100%;height:auto;border-radius:6px}
figcaption{font-size:13px;color:#6b6b73;margin-top:6px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e3e3e6;border-radius:10px;overflow:hidden}
td,th{padding:6px 12px;text-align:left;border-bottom:1px solid #efeff1;font-size:14px;vertical-align:top}
th{background:#fafafb;width:36%;font-weight:600;color:#3a3a40}
tr:last-child td,tr:last-child th{border-bottom:0}
.muted{color:#9a9aa2}
code{background:#f0f0f2;padding:1px 5px;border-radius:4px;font-size:13px}
.maplink{display:inline-block;background:#1b5e9b;color:#fff;text-decoration:none;
  padding:9px 16px;border-radius:8px;font-size:14px;font-weight:600}
.maplink:hover{background:#16527f}
"""


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.3f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:,.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    return html.escape(str(v))


def _rows(d: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten a (possibly nested) section dict into label/value rows."""
    rows: list[tuple[str, str]] = []
    for k, v in d.items():
        label = f"{prefix}{k}"
        if isinstance(v, dict):
            rows.extend(_rows(v, prefix=f"{label} · "))
        elif isinstance(v, list):
            rows.append((label, html.escape(", ".join(str(x) for x in v))))
        else:
            rows.append((label, _fmt(v)))
    return rows


def _table(d: dict) -> str:
    body = "\n".join(
        f"<tr><th>{html.escape(lbl)}</th><td>{val}</td></tr>" for lbl, val in _rows(d)
    )
    return f"<table>{body}</table>"


def _img(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def write_insights(profile: ExploreProfile, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_report(
    profile: ExploreProfile,
    figures: dict[str, Path],
    path: Path,
    *,
    map_filename: str | None = None,
) -> Path:
    """Render a standalone HTML report with figures embedded inline.

    ``map_filename`` (e.g. ``"map.html"``) adds a link to the interactive map,
    which is written as a sibling file next to the report.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    headline = ""
    if profile.headline:
        items = "".join(f"<li>{html.escape(line)}</li>" for line in profile.headline)
        headline = f'<div class="headline"><strong>Key findings</strong><ul>{items}</ul></div>'

    map_link = ""
    if map_filename:
        map_link = (
            f'<p><a class="maplink" href="{html.escape(map_filename)}">'
            "Open the interactive map →</a></p>"
        )

    fig_html = ""
    if figures:
        cards = ""
        for key, fpath in figures.items():
            if not Path(fpath).is_file():
                continue
            title = _FIGURE_TITLES.get(key, key)
            cards += (
                f'<figure><img alt="{html.escape(title)}" src="{_img(Path(fpath))}">'
                f"<figcaption>{html.escape(title)}</figcaption></figure>"
            )
        fig_html = f"<h2>Figures</h2><div class='grid'>{cards}</div>"

    sections = ""
    for key in ("aoi", "buildings", "bag3d", "pc6", "ahn", "capacity", "provenance"):
        data = getattr(profile, key)
        if not data:
            continue
        sections += f"<h2>{html.escape(_SECTION_TITLES.get(key, key))}</h2>{_table(data)}"

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>rsgt explore — {html.escape(profile.aoi_name)}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>Data exploration — {html.escape(profile.aoi_name)}</h1>
<p class="sub">P0.5 insight report · generated {html.escape(profile.generated_at)} ·
<span class="muted">from the P0 ingest artefacts</span></p>
{headline}
{map_link}
{fig_html}
{sections}
</div></body></html>
"""
    path.write_text(doc, encoding="utf-8")
    return path
