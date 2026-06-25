"""Generate a standalone deck.gl + MapLibre web map of per-roof yield.

The output is a single self-contained ``*.html``: the roof GeoJSON is embedded
inline (so you can just double-click the file — no server, no CORS), deck.gl and
MapLibre load from a CDN, and a free keyless CARTO basemap sits underneath.
Roofs are coloured by specific yield (kWh/kWp); click/hover for the breakdown.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..geo.crs import WGS84

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd

log = logging.getLogger("rsgt.export")

_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__</title>
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet"/>
<script src="https://unpkg.com/deck.gl@9.0.38/dist.min.js"></script>
<style>
  html,body{margin:0;height:100%;font-family:system-ui,Segoe UI,Roboto,sans-serif}
  #map{position:absolute;width:100%;height:100%}
  .panel{position:absolute;z-index:2;background:rgba(255,255,255,.92);
         border-radius:8px;box-shadow:0 1px 6px rgba(0,0,0,.3);padding:10px 12px;font-size:13px}
  #title{top:10px;left:10px;max-width:340px}
  #title h1{font-size:15px;margin:0 0 4px}
  #title p{margin:2px 0;color:#444}
  #legend{bottom:18px;left:10px}
  #bar{height:12px;width:220px;border-radius:3px;
       background:linear-gradient(90deg,#440154,#3b528b,#21918c,#5ec962,#fde725)}
  .lrow{display:flex;justify-content:space-between;width:220px;color:#444;margin-top:3px}
  .tip{font-size:12px;line-height:1.45}
  .tip b{color:#111}
</style>
</head>
<body>
<div id="map"></div>
<div id="title" class="panel">
  <h1>__TITLE__</h1>
  <p>__SUBTITLE__</p>
  <p style="color:#666">Colour = specific yield (kWh per kWp / year). Hover a roof for detail.</p>
</div>
<div id="legend" class="panel">
  <div style="font-weight:600;margin-bottom:4px">Specific yield (kWh/kWp·yr)</div>
  <div id="bar"></div>
  <div class="lrow"><span>__VMIN__</span><span>__VMAX__</span></div>
</div>
<script>
const DATA = __DATA__;
const VMIN = __VMIN__, VMAX = __VMAX__;
// viridis-ish ramp (low -> high)
const STOPS = [[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]];
function ramp(t){
  t = Math.max(0, Math.min(1, t));
  const x = t*(STOPS.length-1), i = Math.floor(x), f = x-i;
  const a = STOPS[i], b = STOPS[Math.min(i+1, STOPS.length-1)];
  return [a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f, a[2]+(b[2]-a[2])*f, 220];
}
function colorFor(props){
  const v = props.specific_yield_kwh_kwp;
  if(v==null) return [160,160,160,180];
  return ramp((v-VMIN)/(VMAX-VMIN||1));
}
const map = new maplibregl.Map({
  container:'map',
  style:'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
  center:[__CENTER_LON__, __CENTER_LAT__], zoom:15, pitch:0
});
const layer = new deck.GeoJsonLayer({
  id:'roofs', data:DATA, filled:true, stroked:true,
  getFillColor:f=>colorFor(f.properties),
  getLineColor:[40,40,40,120], lineWidthMinPixels:0.4, pickable:true
});
const overlay = new deck.MapboxOverlay({layers:[layer]});
map.addControl(overlay);
map.addControl(new maplibregl.NavigationControl());
function tip(o){
  if(!o||!o.object) return null;
  const p = o.object.properties, n = x => (x==null?'-':x);
  return {html:`<div class="tip">`
    + `<b>Building</b> ${n(p.bag_id)}<br>`
    + `<b>Specific yield</b> ${n(p.specific_yield_kwh_kwp)} kWh/kWp<br>`
    + `<b>Annual</b> ${n(p.annual_kwh)} kWh/yr &nbsp; <b>Size</b> ${n(p.kwp)} kWp<br>`
    + `<b>Tilt</b> ${n(p.tilt_deg)}&deg; &nbsp; <b>Azimuth</b> ${n(p.azimuth_deg)}&deg;<br>`
    + `<b>Roof area</b> ${n(p.area_m2)} m&sup2; &nbsp; <b>Built</b> ${n(p.bouwjaar)}<br>`
    + `<b>PC6</b> ${n(p.pc6)}</div>`};
}
overlay.setProps({getTooltip:tip});
</script>
</body>
</html>
"""


def write_deckgl_map(
    gdf: gpd.GeoDataFrame, path: str | Path, *, title: str, subtitle: str = "",
    simplify_m: float = 0.2,
) -> Path:
    """Write a self-contained deck.gl yield map. Returns the HTML path."""
    import numpy as np

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    g = gdf.copy()
    if simplify_m and len(g):
        g["geometry"] = g.geometry.simplify(simplify_m, preserve_topology=True)
    g = g.to_crs(WGS84)

    if len(g):
        vals = g["specific_yield_kwh_kwp"].astype(float)
        vmin = float(np.nanpercentile(vals, 5))
        vmax = float(np.nanpercentile(vals, 95))
        minx, miny, maxx, maxy = g.total_bounds  # WGS84 bounds midpoint = view centre
        clon, clat = (minx + maxx) / 2, (miny + maxy) / 2
    else:
        vmin, vmax, clat, clon = 0.0, 1000.0, 52.0, 5.0

    html = (
        _TEMPLATE.replace("__TITLE__", title)
        .replace("__SUBTITLE__", subtitle)
        .replace("__DATA__", g.to_json())
        .replace("__VMIN__", str(round(vmin)))
        .replace("__VMAX__", str(round(vmax)))
        .replace("__CENTER_LAT__", repr(clat))
        .replace("__CENTER_LON__", repr(clon))
    )
    path.write_text(html, encoding="utf-8")
    log.info("export: wrote deck.gl map %s (%d roofs)", path.name, len(g))
    return path
