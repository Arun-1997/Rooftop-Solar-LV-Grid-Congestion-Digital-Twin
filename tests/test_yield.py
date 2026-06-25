"""Offline yield tests — pvlib clear-sky model, no network."""

import geopandas as gpd
import pandas as pd
import pvlib
from shapely.geometry import Polygon

from rsgt.config.schema import SolarConfig
from rsgt.solar.yield_model import compute_plane_yields, specific_yield


def _clearsky_tmy():
    """A few clear-sky summer days near Oudewater — deterministic, offline."""
    times = pd.date_range("2019-06-20", "2019-06-23", freq="h", tz="UTC")
    loc = pvlib.location.Location(52.0, 5.0, tz="UTC")
    cs = loc.get_clearsky(times)  # ghi/dni/dhi
    tmy = cs.copy()
    tmy["temp_air"] = 15.0
    tmy["wind_speed"] = 2.0
    return tmy, loc.get_solarposition(times)


def test_south_beats_north():
    tmy, solpos = _clearsky_tmy()
    cfg = SolarConfig()
    dni_extra = pvlib.irradiance.get_extra_radiation(tmy.index)
    south, _ = specific_yield(tmy, solpos, dni_extra, 35, 180, cfg)
    north, _ = specific_yield(tmy, solpos, dni_extra, 35, 0, cfg)
    assert south > north * 1.3  # south clearly better in the N hemisphere


def test_compute_plane_yields_columns_and_sizing():
    tmy, solpos = _clearsky_tmy()
    planes = gpd.GeoDataFrame(
        {
            "plane_id": ["a", "b"],
            "bag_id": ["1", "1"],
            "area_m2": [40.0, 20.0],
            "tilt_deg": [35.0, 35.0],
            "azimuth_deg": [180.0, 0.0],
        },
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])] * 2,
        crs="EPSG:28992",
    )
    out = compute_plane_yields(planes, tmy, solpos, SolarConfig())
    for col in ("usable_area_m2", "kwp", "specific_yield_kwh_kwp", "annual_kwh", "poa_kwh_m2_yr"):
        assert col in out.columns
    # kwp = area * usable_fraction(0.7) * density(0.18)
    assert abs(out.iloc[0]["kwp"] - 40 * 0.7 * 0.18) < 1e-6
    # annual = specific_yield * kwp
    assert abs(out.iloc[0]["annual_kwh"] - out.iloc[0]["specific_yield_kwh_kwp"] * out.iloc[0]["kwp"]) < 0.5
    # south plane out-yields the north one
    assert out.iloc[0]["annual_kwh"] > out.iloc[1]["annual_kwh"]
