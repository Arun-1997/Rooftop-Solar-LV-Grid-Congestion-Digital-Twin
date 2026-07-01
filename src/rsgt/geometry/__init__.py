"""Roof-plane geometry: CityJSON reading + roof-plane extraction (P1 Stage 1)."""

from .roof_planes import (
    extract_roof_planes,
    filter_planes,
    newell_normal,
    normal_to_tilt_azimuth,
    polygon_area_3d,
)

__all__ = [
    "extract_roof_planes",
    "filter_planes",
    "newell_normal",
    "normal_to_tilt_azimuth",
    "polygon_area_3d",
]
