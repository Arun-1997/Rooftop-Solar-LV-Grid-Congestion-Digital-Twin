"""Stage P0.5 orchestrator: profile the P0 artefacts and emit figures + a report.

This runs *between* P0 (ingest) and P1 (roof-plane extraction). It reads only what
P0 already wrote — it never hits the network — and writes everything under
``<processed>/explore/``:

* ``insights.json`` — the structured :class:`~rsgt.explore.profile.ExploreProfile`.
* ``report.html``   — a standalone visual report (figures embedded inline).
* ``figures/*.png`` — the individual figures, also referenced by the report.
* ``map.html``      — an interactive Leaflet map (buildings/PC6/AOI/capacity).
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config.schema import RunConfig
from ..ingest.pipeline import Paths
from .interactive import write_map
from .plots import make_figures
from .profile import ExploreProfile, build_profile, load_artefacts
from .report import write_insights, write_report

log = logging.getLogger("rsgt.explore")


def run_explore(
    cfg: RunConfig,
    *,
    base_dir: str | Path = ".",
    max_raster_dim: int = 1200,
    make_plots: bool = True,
    make_map: bool = True,
    max_map_buildings: int = 8000,
) -> ExploreProfile:
    """Profile the ingested data for ``cfg``'s AOI and write the explore outputs.

    ``max_raster_dim`` caps the decimated AHN read (long side, in pixels).
    Set ``make_plots=False`` to skip the static figures (no matplotlib), and
    ``make_map=False`` to skip the interactive Leaflet map (no folium).
    ``max_map_buildings`` caps how many footprints the map embeds (sampled above it).
    """
    paths = Paths.from_config(cfg, base_dir)
    out_dir = paths.processed / "explore"
    fig_dir = out_dir / "figures"

    data = load_artefacts(
        paths.raw, paths.interim, paths.processed, cfg.aoi.name, max_raster_dim=max_raster_dim
    )
    profile = build_profile(data)

    figures: dict[str, Path] = {}
    if make_plots:
        figures = make_figures(data, fig_dir)

    map_path: Path | None = None
    if make_map:
        try:
            map_path = write_map(data, out_dir / "map.html", max_buildings=max_map_buildings)
        except Exception as exc:  # noqa: BLE001 — the map is a bonus, never fatal
            log.warning("explore: interactive map failed (%s)", exc)

    write_insights(profile, out_dir / "insights.json")
    write_report(
        profile, figures, out_dir / "report.html",
        map_filename=map_path.name if map_path else None,
    )
    log.info(
        "explore: wrote %d figure(s)%s + report.html + insights.json to %s",
        len(figures),
        " + map.html" if map_path else "",
        out_dir,
    )
    return profile
