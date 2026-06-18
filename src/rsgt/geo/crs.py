"""CRS constants and reprojection helpers.

Everything in this project is worked in **RD New (EPSG:28992)**; height-aware data
(3D BAG) is stored in **EPSG:7415 (RD New + NAP)**, which shares the planar axes.

``pyproj``/``shapely`` are imported lazily inside functions so that importing the
package does not require the ``geo`` extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

RD_NEW = "EPSG:28992"
RD_NEW_NAP = "EPSG:7415"
WGS84 = "EPSG:4326"

BBox = tuple[float, float, float, float]

if TYPE_CHECKING:  # pragma: no cover
    from shapely.geometry.base import BaseGeometry


def epsg_uri(crs: str) -> str:
    """Return the OGC CRS URI for an ``EPSG:xxxx`` code.

    >>> epsg_uri("EPSG:28992")
    'http://www.opengis.net/def/crs/EPSG/0/28992'
    """
    code = crs.split(":")[-1]
    return f"http://www.opengis.net/def/crs/EPSG/0/{code}"


def reproject_bbox(
    bbox: BBox, src_crs: str, dst_crs: str, *, densify: int = 21
) -> BBox:
    """Reproject an axis-aligned bbox, densifying edges so the result encloses the
    source rectangle even under non-affine transforms (e.g. RD New <-> WGS84).

    Transforming only the 4 corners can shrink the box; we sample ``densify``
    points along each edge and take the envelope of all transformed points.
    """
    if src_crs == dst_crs:
        return bbox
    from pyproj import Transformer

    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    minx, miny, maxx, maxy = bbox
    n = max(densify, 2)
    xs: list[float] = []
    ys: list[float] = []

    def _add(px: float, py: float) -> None:
        tx, ty = transformer.transform(px, py)
        xs.append(tx)
        ys.append(ty)

    for i in range(n):
        t = i / (n - 1)
        x = minx + (maxx - minx) * t
        y = miny + (maxy - miny) * t
        _add(x, miny)
        _add(x, maxy)
        _add(minx, y)
        _add(maxx, y)
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_polygon(bbox: BBox) -> BaseGeometry:
    """Return a shapely box polygon for ``[minx, miny, maxx, maxy]``."""
    from shapely.geometry import box

    return box(*bbox)


def tile_bbox(bbox: BBox, tile_size: float) -> list[BBox]:
    """Split a bbox into a grid of sub-boxes at most ``tile_size`` on a side.

    Used to chunk large WCS / coverage requests that exceed a service's per-request
    pixel limit. The last row/column may be smaller than ``tile_size``.
    """
    minx, miny, maxx, maxy = bbox
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    out: list[BBox] = []
    y = miny
    while y < maxy:
        y2 = min(y + tile_size, maxy)
        x = minx
        while x < maxx:
            x2 = min(x + tile_size, maxx)
            out.append((x, y, x2, y2))
            x = x2
        y = y2
    return out


def buffer_bbox(bbox: BBox, buffer: float) -> BBox:
    """Expand a bbox by ``buffer`` on all sides."""
    minx, miny, maxx, maxy = bbox
    return (minx - buffer, miny - buffer, maxx + buffer, maxy + buffer)
