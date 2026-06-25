"""P0.5 explore — profile and visualise the P0 ingest artefacts.

A read-only step between P0 (ingest) and P1 (roof-plane extraction). It loads the
GeoPackages, AHN rasters and CityJSONSeq ids that P0 produced and emits a structured
``insights.json`` plus a standalone ``report.html`` with figures, so you can sanity-
check coverage and get a feel for the study area before modelling. See docs/P0_5.md.
"""

from __future__ import annotations

from .interactive import build_map, write_map
from .profile import ExploreProfile, build_profile, load_artefacts
from .run import run_explore

__all__ = [
    "ExploreProfile",
    "build_map",
    "build_profile",
    "load_artefacts",
    "run_explore",
    "write_map",
]
