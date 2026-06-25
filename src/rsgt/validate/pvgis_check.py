"""Validate the physics yield against PVGIS's own estimate (README sec.5.3).

For a reference system (default south, 35 deg, 1 kWp) we compare our TMY+PVWatts
specific yield against PVGIS's published PVcalc estimate for the same location and
system. Close agreement on an unshaded south roof is the expected, confidence-
building result; this is validation, not training.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config.schema import SolarConfig
from ..solar.yield_model import specific_yield

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

log = logging.getLogger("rsgt.validate")


def pvgis_reference_yield(
    lat: float, lon: float, tilt: float, azimuth: float, loss_pct: float
) -> tuple[float, int]:
    """PVGIS PVcalc mean annual specific yield (kWh/kWp) and the #years averaged."""
    import pvlib

    df, *_ = pvlib.iotools.get_pvgis_hourly(
        lat, lon,
        surface_tilt=tilt,
        surface_azimuth=azimuth,
        pvcalculation=True,
        peakpower=1,
        loss=loss_pct,
        optimalangles=False,
        map_variables=True,
    )
    yearly = df["P"].groupby(df.index.year).sum() / 1000.0
    # Drop possibly-partial first/last years.
    if len(yearly) > 2:
        yearly = yearly.iloc[1:-1]
    return float(yearly.mean()), int(len(yearly))


def validate_against_pvgis(
    lat: float, lon: float, tmy: pd.DataFrame, solpos: pd.DataFrame, cfg: SolarConfig
) -> dict:
    """Compare our reference-roof yield against PVGIS. Returns a result dict."""
    import pvlib

    dni_extra = pvlib.irradiance.get_extra_radiation(tmy.index)
    ours, poa = specific_yield(
        tmy, solpos, dni_extra, cfg.reference_tilt_deg, cfg.reference_azimuth_deg, cfg
    )
    pvgis, n_years = pvgis_reference_yield(
        lat, lon, cfg.reference_tilt_deg, cfg.reference_azimuth_deg,
        cfg.system_loss_fraction * 100,
    )
    diff = ours - pvgis
    pct = 100.0 * diff / pvgis if pvgis else float("nan")
    result = {
        "reference_tilt_deg": cfg.reference_tilt_deg,
        "reference_azimuth_deg": cfg.reference_azimuth_deg,
        "ours_kwh_per_kwp": round(ours, 1),
        "pvgis_kwh_per_kwp": round(pvgis, 1),
        "mbe_kwh_per_kwp": round(diff, 1),
        "mbe_pct": round(pct, 2),
        "pvgis_years_averaged": n_years,
        "poa_kwh_m2_yr": round(poa, 1),
    }
    log.info(
        "validation: ours=%.0f vs PVGIS=%.0f kWh/kWp (%.1f%%)",
        ours, pvgis, pct,
    )
    return result
