"""Ingest BAG building attributes (PDOK WFS ``bag:pand`` etc.).

BAG supplies construction year (``bouwjaar``), use function (``gebruiksdoel``),
status and footprint area — inputs to the suitability and self-consumption steps
later in the pipeline. This is a thin wrapper over the generic WFS source.
"""

from __future__ import annotations

import requests

from ..config.schema import WFSSourceConfig
from .aoi import AreaOfInterest
from .manifest import DownloadManifest
from .vector import ingest_wfs_source


def ingest_bag(
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
        "bag", cfg, aoi, session, manifest, out_dir, timeout=timeout, force=force
    )
