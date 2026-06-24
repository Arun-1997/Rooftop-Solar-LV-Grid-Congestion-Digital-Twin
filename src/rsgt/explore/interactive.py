"""Build an interactive Leaflet (Folium) map of the P0 artefacts.

Produces a single ``map.html`` slippy-map with toggleable layers — BAG buildings
shaded by construction year, PC6 aggregation polygons, the AOI outline, and any
capacity-map layers. Geometry is reprojected from RD New (EPSG:28992) to WGS84,
which Leaflet expects.

The output HTML references Leaflet's JS/CSS from a CDN, so an internet connection
is needed to display the *basemap tiles* when the file is opened (the data itself
is embedded). ``folium`` is imported lazily so the package imports without the
``viz`` extra.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .profile import LoadedData

log = logging.getLogger("rsgt.explore")

WGS84 = "EPSG:4326"


def _bounds_4326(data: LoadedData):
    """[[miny, minx], [maxy, maxx]] for fit_bounds, from the best available layer."""
    for gdf in (data.aoi, data.pc6, data.buildings):
        if gdf is not None and len(gdf):
            minx, miny, maxx, maxy = gdf.to_crs(WGS84).total_bounds
            return [[float(miny), float(minx)], [float(maxy), float(maxx)]]
    return None


def _detect_code_col(gdf) -> str | None:
    for col in ("postcode6", "postcode", "pc6", "PC6"):
        if col in gdf.columns:
            return col
    return None


def _buildings_layer(m, data: LoadedData, *, max_buildings: int) -> None:
    import folium
    from branca.colormap import LinearColormap
    from folium.features import GeoJsonTooltip

    b = data.buildings
    if b is None or not len(b):
        return
    note = ""
    if len(b) > max_buildings:
        b = b.sample(max_buildings, random_state=0)
        note = f" (sampled {max_buildings:,})"

    b = b.copy()
    b["footprint_m2"] = b.geometry.area.round(1)
    b["geometry"] = b.geometry.simplify(0.2, preserve_topology=True)  # trim file size
    keep = [c for c in ("bouwjaar", "status", "footprint_m2") if c in b.columns] + ["geometry"]
    b = b[keep].to_crs(WGS84)

    style_fn = lambda feat: {"fillColor": "#3b7dd8", "color": "#1f3b66",  # noqa: E731
                             "weight": 0.3, "fillOpacity": 0.7}
    if "bouwjaar" in b.columns:
        years = pd.to_numeric(b["bouwjaar"], errors="coerce")
        b["bouwjaar"] = [int(y) if pd.notna(y) else None for y in years]
        valid = years.dropna()
        if not valid.empty:
            cmap = LinearColormap(
                ["#440154", "#31688e", "#35b779", "#fde725"],
                vmin=float(valid.min()), vmax=float(valid.max()),
                caption="BAG construction year",
            )
            cmap.add_to(m)

            def style_fn(feat):  # noqa: F811 — year-aware override
                y = feat["properties"].get("bouwjaar")
                fill = cmap(y) if y is not None else "#999999"
                return {"fillColor": fill, "color": "#333", "weight": 0.3, "fillOpacity": 0.75}

    folium.GeoJson(
        b.to_json(),
        name=f"BAG buildings{note}",
        style_function=style_fn,
        tooltip=GeoJsonTooltip(fields=[c for c in keep if c != "geometry"]),
        smooth_factor=1.0,
    ).add_to(m)


def _outline_layer(m, gdf, name, color, *, tooltip_fields=None) -> None:
    import folium
    from folium.features import GeoJsonTooltip

    if gdf is None or not len(gdf):
        return
    g = gdf.to_crs(WGS84)
    tooltip = None
    if tooltip_fields:
        present = [f for f in tooltip_fields if f in g.columns]
        if present:
            tooltip = GeoJsonTooltip(fields=present)
    folium.GeoJson(
        g.to_json(),
        name=name,
        style_function=lambda f: {"fill": False, "color": color, "weight": 1.8},
        tooltip=tooltip,
    ).add_to(m)


def build_map(data: LoadedData, *, max_buildings: int = 8000):
    """Return a :class:`folium.Map` of the AOI's artefacts, or ``None`` if nothing
    spatial was loaded."""
    bounds = _bounds_4326(data)
    if bounds is None:
        return None
    import folium

    centre = [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2]
    m = folium.Map(location=centre, tiles="OpenStreetMap", control_scale=True, zoom_start=14)

    pc6_code = _detect_code_col(data.pc6) if data.pc6 is not None else None
    _outline_layer(m, data.pc6, "PC6 units", "#d35400",
                   tooltip_fields=[pc6_code] if pc6_code else None)
    _buildings_layer(m, data, max_buildings=max_buildings)
    for kind, gdf in (data.capacity or {}).items():
        cols = [c for c in gdf.columns if c != "geometry"][:5]
        _outline_layer(m, gdf, f"capacity: {kind}", "#8e44ad", tooltip_fields=cols)
    _outline_layer(m, data.aoi, "AOI", "#d1495b")

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds(bounds)
    return m


def write_map(data: LoadedData, path: Path, *, max_buildings: int = 8000) -> Path | None:
    """Build and save the interactive map to ``path``; ``None`` if no spatial data."""
    m = build_map(data, max_buildings=max_buildings)
    if m is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(path))
    log.info("explore: wrote interactive map %s", path.name)
    return path
