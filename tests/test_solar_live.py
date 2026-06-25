"""Live P1 tests: PVGIS TMY + the validation check. Needs --run-network."""

from __future__ import annotations

import pytest

from rsgt.config.schema import SolarConfig
from rsgt.solar.resource import get_tmy, solar_position
from rsgt.solar.yield_model import specific_yield
from rsgt.validate import validate_against_pvgis

pytestmark = pytest.mark.network

LAT, LON = 52.025, 4.87  # Oudewater


def test_tmy_and_reference_yield(tmp_path):
    tmy = get_tmy(LAT, LON, tmp_path / "pvgis")
    assert len(tmy) == 8760
    assert 950 < tmy["ghi"].sum() / 1000 < 1250  # NL annual GHI kWh/m2
    import pvlib

    solpos = solar_position(tmy.index, LAT, LON)
    dni_extra = pvlib.irradiance.get_extra_radiation(tmy.index)
    south, _ = specific_yield(tmy, solpos, dni_extra, 35, 180, SolarConfig())
    assert 850 < south < 1150  # plausible NL specific yield, south-35


def test_validation_close_to_pvgis(tmp_path):
    tmy = get_tmy(LAT, LON, tmp_path / "pvgis")
    solpos = solar_position(tmy.index, LAT, LON)
    res = validate_against_pvgis(LAT, LON, tmy, solpos, SolarConfig())
    # Our PVWatts baseline should track PVGIS's own estimate within a few %.
    assert abs(res["mbe_pct"]) < 8.0
