"""Thin, well-tested clients for the OGC/Esri services P0 ingests.

Each client only knows a *protocol* (WFS 2.0, OGC API Features, ArcGIS Feature
Service, WCS 2.0.1); the source-specific URLs and layer names live in the run
config. Keeping them generic makes them easy to unit-test with mocked responses
and easy to repoint when a service version changes.

All vector results come back as GeoDataFrames in the CRS that was requested from
the service (PDOK returns RD coordinates in GeoJSON when ``srsName=EPSG:28992`` is
asked for, even though that is technically non-conformant GeoJSON), so we set the
CRS explicitly rather than trusting the GeoJSON ``crs`` member.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import requests

from ..geo.crs import epsg_uri

log = logging.getLogger("rsgt.clients")

BBox = tuple[float, float, float, float]


def features_to_gdf(features: list[dict], crs: str):
    """Build a GeoDataFrame from GeoJSON features, forcing ``crs``.

    Returns an empty GeoDataFrame (with the CRS set) when there are no features.
    """
    import geopandas as gpd

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs=crs)
    gdf = gpd.GeoDataFrame.from_features(features, crs=crs)
    return gdf


# --------------------------------------------------------------------------- WFS
class WFSClient:
    """PDOK WFS 2.0 client (used for BAG and PC6).

    Pages through ``GetFeature`` with ``count`` + ``startIndex`` and concatenates
    the results. ``bbox`` is given in ``crs`` (default RD New); we use the short
    ``EPSG:28992`` BBOX form which keeps easting/northing axis order.
    """

    def __init__(self, session: requests.Session, timeout: float = 60.0):
        self.session = session
        self.timeout = timeout

    def get_features(
        self,
        wfs_url: str,
        type_name: str,
        *,
        bbox: BBox | None = None,
        crs: str = "EPSG:28992",
        page_size: int = 1000,
        max_features: int | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Return all matching GeoJSON features (as plain dicts)."""
        features: list[dict] = []
        start = 0
        while True:
            params: dict[str, Any] = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeName": type_name,
                "outputFormat": "application/json",
                "srsName": crs,
                "count": page_size,
                "startIndex": start,
            }
            if bbox is not None:
                params["bbox"] = "{},{},{},{},{}".format(*bbox, crs)
            if extra_params:
                params.update(extra_params)
            resp = self.session.get(wfs_url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            page = payload.get("features", [])
            features.extend(page)
            returned = payload.get("numberReturned", len(page))
            log.info("WFS %s: +%d (total %d)", type_name, returned, len(features))
            if max_features is not None and len(features) >= max_features:
                return features[:max_features]
            if returned < page_size or returned == 0:
                break
            start += returned
        return features


# ----------------------------------------------------------- OGC API Features
class OGCFeaturesClient:
    """OGC API Features client (3D BAG ``api.3dbag.nl`` and PDOK OGC APIs).

    Pages by following ``rel=next`` links, which is the protocol-correct way to
    paginate and works whether the server uses ``offset`` or token cursors.
    """

    def __init__(self, session: requests.Session, timeout: float = 60.0):
        self.session = session
        self.timeout = timeout

    def iter_pages(
        self,
        items_url: str,
        params: dict[str, Any],
        *,
        max_items: int | None = None,
        max_pages: int = 100_000,
    ) -> Iterator[dict]:
        """Yield successive page payloads (parsed JSON) following ``next`` links."""
        next_url: str | None = items_url
        next_params: dict[str, Any] | None = dict(params)
        seen = 0
        for _ in range(max_pages):
            if next_url is None:
                return
            resp = self.session.get(next_url, params=next_params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            yield payload
            seen += payload.get("numberReturned", len(payload.get("features", [])))
            if max_items is not None and seen >= max_items:
                return
            next_url = _next_link(payload)
            next_params = None  # next links are fully-qualified
        log.warning("OGC pager hit max_pages=%d for %s", max_pages, items_url)

    def bbox_params(
        self, bbox: BBox, bbox_crs: str | None, limit: int
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"bbox": "{},{},{},{}".format(*bbox), "limit": limit}
        if bbox_crs:
            params["bbox-crs"] = bbox_crs
        return params

    def get_geojson_features(
        self,
        items_url: str,
        params: dict[str, Any],
        *,
        max_items: int | None = None,
    ) -> list[dict]:
        """Collect GeoJSON ``features`` across all pages (for geo+json APIs)."""
        out: list[dict] = []
        for page in self.iter_pages(items_url, params, max_items=max_items):
            out.extend(page.get("features", []))
            if max_items is not None and len(out) >= max_items:
                return out[:max_items]
        return out


def _next_link(payload: dict) -> str | None:
    for link in payload.get("links", []) or []:
        if link.get("rel") == "next" and link.get("href"):
            return link["href"]
    return None


# --------------------------------------------------------- ArcGIS Feature Server
class ArcGISFeatureServiceClient:
    """ArcGIS Feature Service query client (Netbeheer capaciteitskaart).

    Pages with ``resultOffset``/``resultRecordCount`` and stops when the server
    stops reporting ``exceededTransferLimit`` (or returns a short page).
    """

    def __init__(self, session: requests.Session, timeout: float = 60.0):
        self.session = session
        self.timeout = timeout

    def query_layer(
        self,
        layer_url: str,
        *,
        bbox: BBox | None = None,
        in_sr: int = 28992,
        out_sr: int = 28992,
        where: str = "1=1",
        out_fields: str = "*",
        page_size: int = 1000,
        max_features: int | None = None,
    ) -> list[dict]:
        """Return GeoJSON features from ``{layer_url}/query`` across all pages."""
        query_url = layer_url.rstrip("/") + "/query"
        features: list[dict] = []
        offset = 0
        while True:
            params: dict[str, Any] = {
                "where": where,
                "outFields": out_fields,
                "f": "geojson",
                "outSR": out_sr,
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "returnGeometry": "true",
            }
            if bbox is not None:
                params["geometry"] = "{},{},{},{}".format(*bbox)
                params["geometryType"] = "esriGeometryEnvelope"
                params["inSR"] = in_sr
                params["spatialRel"] = "esriSpatialRelIntersects"
            resp = self.session.get(query_url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            page = payload.get("features", [])
            features.extend(page)
            log.info("ArcGIS %s: +%d (total %d)", layer_url, len(page), len(features))
            if max_features is not None and len(features) >= max_features:
                return features[:max_features]
            exceeded = payload.get("exceededTransferLimit") or payload.get(
                "properties", {}
            ).get("exceededTransferLimit")
            if not exceeded and len(page) < page_size:
                break
            if len(page) == 0:
                break
            offset += len(page)
        return features


# ----------------------------------------------------------------------- WCS
class WCSClient:
    """OGC WCS 2.0.1 client for the AHN raster coverages (DSM/DTM)."""

    def __init__(self, session: requests.Session, timeout: float = 120.0):
        self.session = session
        self.timeout = timeout

    def get_coverage(
        self,
        wcs_url: str,
        coverage_id: str,
        bbox: BBox,
        *,
        fmt: str = "image/tiff",
        axis_x: str = "x",
        axis_y: str = "y",
        subsetting_crs: str | None = None,
    ) -> bytes:
        """GetCoverage for ``bbox`` and return the raw GeoTIFF bytes.

        ``bbox`` is interpreted in the coverage's native CRS unless
        ``subsetting_crs`` (an ``EPSG:xxxx`` code) is given. For AHN the native CRS
        is RD New, so RD-metre subsets work without declaring a CRS.
        """
        minx, miny, maxx, maxy = bbox
        params: dict[str, Any] = {
            "service": "WCS",
            "version": "2.0.1",
            "request": "GetCoverage",
            "coverageId": coverage_id,
            "subset": [f"{axis_x}({minx},{maxx})", f"{axis_y}({miny},{maxy})"],
            "format": fmt,
        }
        if subsetting_crs is not None:
            params["subsettingCrs"] = epsg_uri(subsetting_crs)
        resp = self.session.get(wcs_url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "tif" not in ctype and "image" not in ctype:
            # WCS errors come back as XML with a 200 in some deployments.
            raise RuntimeError(
                f"WCS GetCoverage for {coverage_id} returned '{ctype}', "
                f"not a coverage: {resp.text[:300]}"
            )
        return resp.content
