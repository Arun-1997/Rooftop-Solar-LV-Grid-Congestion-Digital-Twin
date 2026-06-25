"""Solar resource: fetch the irradiance time series and solar geometry.

We attach one **PVGIS TMY** (Typical Meteorological Year — 8760 representative
hours of GHI/DNI/DHI + air temperature + wind) to the AOI's centre. For a small
municipality a single TMY for the whole area is accurate and keeps the run fast;
per-building TMY would barely move the numbers. The TMY is cached to
``<raw>/pvgis/`` so the network call happens once.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ..geo.crs import RD_NEW, WGS84

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

log = logging.getLogger("rsgt.solar")


def centroid_lonlat(geometry_rd, *, src_crs: str = RD_NEW) -> tuple[float, float]:
    """Return (lat, lon) of an RD-New geometry's centroid in WGS84."""
    from pyproj import Transformer

    c = geometry_rd.centroid
    transformer = Transformer.from_crs(src_crs, WGS84, always_xy=True)
    lon, lat = transformer.transform(c.x, c.y)
    return float(lat), float(lon)


def get_tmy(
    lat: float, lon: float, cache_dir: str | Path, *, force: bool = False
) -> pd.DataFrame:
    """Fetch (and cache) a PVGIS TMY for a location. Returns an hourly DataFrame
    indexed by a tz-aware DatetimeIndex with columns incl. ghi/dni/dhi/temp_air/
    wind_speed."""
    import pandas as pd

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = f"tmy_{lat:.4f}_{lon:.4f}"
    csv_path = cache_dir / f"{stem}.csv"
    meta_path = cache_dir / f"{stem}.json"

    if csv_path.is_file() and not force:
        log.info("TMY cache hit %s", csv_path.name)
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    import pvlib

    log.info("fetching PVGIS TMY for (%.4f, %.4f)", lat, lon)
    # pvlib returns (data, metadata) in >=0.11 and a 4-tuple in older versions.
    out = pvlib.iotools.get_pvgis_tmy(lat, lon, map_variables=True)
    data = out[0]
    data.to_csv(csv_path)
    meta_path.write_text(
        json.dumps(
            {
                "source": "PVGIS TMY (pvlib.iotools.get_pvgis_tmy)",
                "lat": lat,
                "lon": lon,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ghi_kwh_m2_yr": round(float(data["ghi"].sum()) / 1000, 1),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return data


def solar_position(times, lat: float, lon: float, *, altitude: float = 0.0):
    """Apparent solar position for the TMY timestamps at a location."""
    import pvlib

    loc = pvlib.location.Location(lat, lon, tz="UTC", altitude=altitude)
    return loc.get_solarposition(times)
