"""Render the P0.5 explore figures with matplotlib.

Every figure is best-effort: if an artefact is missing or a plot raises, the
failure is logged and the remaining figures are still produced. ``matplotlib`` is
imported lazily with the non-interactive ``Agg`` backend so the step runs headless
(CI, servers) and the core package imports without the ``viz`` extra.

Returns a ``{figure_key: path}`` map that :mod:`rsgt.explore.report` embeds.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .profile import LoadedData, RasterData

log = logging.getLogger("rsgt.explore")


def _new_ax(figsize=(8, 6)):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    return fig, ax


def _save(fig, path: Path) -> Path:
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def _masked(r: RasterData) -> np.ndarray:
    a = r.array.astype("float64")
    if r.nodata is not None:
        a = np.where(a == r.nodata, np.nan, a)
    return a


def _extent(r: RasterData):
    minx, miny, maxx, maxy = r.bounds
    return [minx, maxx, miny, maxy]


def plot_overview(data: LoadedData, path: Path) -> Path | None:
    """AOI boundary + PC6 outlines + BAG footprints (shaded by construction year)."""
    if data.buildings is None and data.pc6 is None and data.aoi is None:
        return None
    fig, ax = _new_ax(figsize=(8, 8))
    if data.pc6 is not None and len(data.pc6):
        data.pc6.boundary.plot(ax=ax, color="#888", linewidth=0.5, zorder=1)
    if data.buildings is not None and len(data.buildings):
        b = data.buildings
        if "bouwjaar" in b.columns and b["bouwjaar"].notna().any():
            b.plot(ax=ax, column="bouwjaar", cmap="viridis", linewidth=0, zorder=2,
                   legend=True, legend_kwds={"label": "construction year", "shrink": 0.6})
        else:
            b.plot(ax=ax, color="#3b7dd8", linewidth=0, zorder=2)
    if data.aoi is not None and len(data.aoi):
        data.aoi.boundary.plot(ax=ax, color="#d1495b", linewidth=1.6, zorder=3)
    ax.set_title(f"{data.aoi_name}: buildings, PC6 units and AOI")
    ax.set_xlabel("RD New easting (m)")
    ax.set_ylabel("RD New northing (m)")
    ax.set_aspect("equal")
    return _save(fig, path)


def plot_construction_years(data: LoadedData, path: Path) -> Path | None:
    if data.buildings is None or "bouwjaar" not in data.buildings.columns:
        return None
    import pandas as pd

    years = pd.to_numeric(data.buildings["bouwjaar"], errors="coerce").dropna()
    years = years[(years > 1000) & (years < 2100)]
    if years.empty:
        return None
    fig, ax = _new_ax()
    ax.hist(years, bins=range(int(years.min() // 10 * 10), int(years.max() // 10 * 10) + 20, 10),
            color="#3b7dd8", edgecolor="white")
    ax.set_title("BAG buildings by construction decade")
    ax.set_xlabel("construction year")
    ax.set_ylabel("number of buildings")
    return _save(fig, path)


def plot_footprint_areas(data: LoadedData, path: Path) -> Path | None:
    if data.buildings is None or not len(data.buildings):
        return None
    areas = data.buildings.geometry.area
    areas = areas[areas > 0]
    if areas.empty:
        return None
    fig, ax = _new_ax()
    bins = np.logspace(np.log10(areas.min()), np.log10(areas.max()), 40)
    ax.hist(areas, bins=bins, color="#48a999", edgecolor="white")
    ax.set_xscale("log")
    ax.set_title("BAG footprint area distribution")
    ax.set_xlabel("footprint area (m², log scale)")
    ax.set_ylabel("number of buildings")
    return _save(fig, path)


def plot_dsm(data: LoadedData, path: Path) -> Path | None:
    if data.dsm is None:
        return None
    fig, ax = _new_ax()
    im = ax.imshow(_masked(data.dsm), cmap="terrain", extent=_extent(data.dsm), origin="upper")
    fig.colorbar(im, ax=ax, shrink=0.7, label="DSM elevation (m NAP)")
    ax.set_title("AHN DSM (surface elevation)")
    ax.set_xlabel("RD New easting (m)")
    ax.set_ylabel("RD New northing (m)")
    return _save(fig, path)


def plot_object_height(data: LoadedData, path: Path) -> Path | None:
    if data.dsm is None or data.dtm is None or data.dsm.array.shape != data.dtm.array.shape:
        return None
    h = _masked(data.dsm) - _masked(data.dtm)
    fig, ax = _new_ax()
    im = ax.imshow(h, cmap="magma", extent=_extent(data.dsm), origin="upper", vmin=0, vmax=15)
    fig.colorbar(im, ax=ax, shrink=0.7, label="height above ground (m)")
    ax.set_title("AHN object height (DSM − DTM)")
    ax.set_xlabel("RD New easting (m)")
    ax.set_ylabel("RD New northing (m)")
    return _save(fig, path)


_FIGURES = {
    "overview": ("overview.png", plot_overview),
    "construction_years": ("construction_years.png", plot_construction_years),
    "footprint_areas": ("footprint_areas.png", plot_footprint_areas),
    "dsm": ("ahn_dsm.png", plot_dsm),
    "object_height": ("ahn_object_height.png", plot_object_height),
}


def make_figures(data: LoadedData, fig_dir: Path) -> dict[str, Path]:
    """Render every figure that has data; return ``{key: path}`` for those produced."""
    import matplotlib

    matplotlib.use("Agg")  # headless: no display needed
    fig_dir.mkdir(parents=True, exist_ok=True)
    produced: dict[str, Path] = {}
    for key, (filename, fn) in _FIGURES.items():
        try:
            out = fn(data, fig_dir / filename)
        except Exception as exc:  # noqa: BLE001 — a broken figure shouldn't sink the report
            log.warning("explore: figure %r failed (%s)", key, exc)
            continue
        if out is not None:
            produced[key] = out
            log.info("explore: wrote figure %s", out.name)
    return produced
