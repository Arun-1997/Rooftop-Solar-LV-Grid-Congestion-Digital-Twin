"""Stage 0 data ingest: AOI resolution, source loaders, and the pipeline."""

from .aoi import AreaOfInterest, resolve_aoi
from .manifest import DownloadManifest
from .pipeline import ALL_SOURCES, IngestSummary, Paths, run_ingest

__all__ = [
    "run_ingest",
    "IngestSummary",
    "Paths",
    "ALL_SOURCES",
    "AreaOfInterest",
    "resolve_aoi",
    "DownloadManifest",
]
