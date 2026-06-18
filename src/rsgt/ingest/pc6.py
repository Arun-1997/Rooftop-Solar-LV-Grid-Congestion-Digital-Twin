"""Ingest PC6 (6-digit postcode) polygons — the grid-aggregation units.

PC6 is the finest resolution at which the Netbeheer congestion data is published,
so it is the unit the whole project aggregates to. Sourced from the PDOK/CBS
``postcode6`` WFS. Thin wrapper over the generic WFS source.
"""

from __future__ import annotations

import requests

from ..config.schema import WFSSourceConfig
from .aoi import AreaOfInterest
from .manifest import DownloadManifest
from .vector import ingest_wfs_source


def ingest_pc6(
    aoi: AreaOfInterest,
    cfg: WFSSourceConfig,
    session: requests.Session,
    manifest: DownloadManifest,
    out_dir,
    *,
    timeout: float = 60.0,
    force: bool = False,
) -> dict:
    return ingest_wfs_source(
        "pc6", cfg, aoi, session, manifest, out_dir, timeout=timeout, force=force
    )
