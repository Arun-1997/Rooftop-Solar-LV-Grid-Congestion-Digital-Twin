"""Physics-first PV yield: POA transposition + the PVWatts performance model.

For each roof plane we transpose the TMY irradiance onto the plane (Hay-Davies)
and run PVWatts: POA -> cell temperature -> DC -> AC with standard losses and
inverter clipping. Because per-kWp specific yield depends only on (tilt, azimuth),
we compute it once per rounded orientation and reuse it across the many roofs that
share an orientation — exact and fast.

This is the **unshaded baseline**. Horizon/neighbour shading is added in P2; an
ML residual on top of physics is a later phase.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config.schema import SolarConfig

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd
    import pandas as pd

log = logging.getLogger("rsgt.solar")

_TEMP_PARAMS = "open_rack_glass_glass"


def transpose_poa(
    tmy: pd.DataFrame, solpos: pd.DataFrame, dni_extra, tilt: float, azimuth: float,
    model: str,
) -> pd.Series:
    """Plane-of-array global irradiance (W/m^2) for a given tilt/azimuth."""
    import pvlib

    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=tilt,
        surface_azimuth=azimuth,
        solar_zenith=solpos["apparent_zenith"],
        solar_azimuth=solpos["azimuth"],
        dni=tmy["dni"],
        ghi=tmy["ghi"],
        dhi=tmy["dhi"],
        dni_extra=dni_extra,
        model=model,
    )
    return poa["poa_global"]


def pvwatts_ac(poa_global: pd.Series, tmy: pd.DataFrame, kwp: float, cfg: SolarConfig):
    """AC power series (W) from POA for a ``kwp`` system via the PVWatts chain."""
    import pvlib

    params = pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"][_TEMP_PARAMS]
    tcell = pvlib.temperature.sapm_cell(
        poa_global, tmy["temp_air"], tmy["wind_speed"], **params
    )
    pdc0 = kwp * 1000.0  # nameplate DC, W
    dc = pvlib.pvsystem.pvwatts_dc(poa_global, tcell, pdc0=pdc0, gamma_pdc=cfg.gamma_pdc)
    dc *= 1.0 - cfg.system_loss_fraction
    ac = pvlib.inverter.pvwatts(dc, pdc0 / cfg.dc_ac_ratio)
    return ac


def specific_yield(
    tmy: pd.DataFrame, solpos: pd.DataFrame, dni_extra, tilt: float, azimuth: float,
    cfg: SolarConfig,
) -> tuple[float, float]:
    """Return (specific_yield_kwh_per_kwp, poa_kwh_m2_yr) for one orientation."""
    poa = transpose_poa(tmy, solpos, dni_extra, tilt, azimuth, cfg.transposition_model)
    ac = pvwatts_ac(poa, tmy, kwp=1.0, cfg=cfg)
    return float(ac.sum()) / 1000.0, float(poa.sum()) / 1000.0


def compute_plane_yields(
    planes: gpd.GeoDataFrame, tmy: pd.DataFrame, solpos: pd.DataFrame, cfg: SolarConfig
) -> gpd.GeoDataFrame:
    """Add system-size and yield columns to a roof-plane GeoDataFrame.

    New columns: ``usable_area_m2``, ``kwp``, ``poa_kwh_m2_yr``,
    ``specific_yield_kwh_kwp``, ``annual_kwh``.
    """
    import pvlib

    out = planes.copy()
    if len(out) == 0:
        for col in ("usable_area_m2", "kwp", "poa_kwh_m2_yr", "specific_yield_kwh_kwp",
                    "annual_kwh"):
            out[col] = []
        return out

    dni_extra = pvlib.irradiance.get_extra_radiation(tmy.index)

    # Cache specific yield per rounded orientation (1 deg buckets).
    cache: dict[tuple[int, int], tuple[float, float]] = {}

    def lookup(tilt: float, azimuth: float) -> tuple[float, float]:
        key = (int(round(tilt)), int(round(azimuth)) % 360)
        if key not in cache:
            cache[key] = specific_yield(tmy, solpos, dni_extra, float(key[0]), float(key[1]), cfg)
        return cache[key]

    sy, poa, usable, kwp, annual = [], [], [], [], []
    for tilt, azimuth, area in zip(
        out["tilt_deg"], out["azimuth_deg"], out["area_m2"], strict=False
    ):
        s_yield, poa_m2 = lookup(tilt, azimuth)
        ua = area * cfg.usable_fraction
        kw = ua * cfg.module_power_density_kwp_m2
        sy.append(round(s_yield, 1))
        poa.append(round(poa_m2, 1))
        usable.append(round(ua, 2))
        kwp.append(round(kw, 3))
        annual.append(round(s_yield * kw, 1))

    out["usable_area_m2"] = usable
    out["kwp"] = kwp
    out["poa_kwh_m2_yr"] = poa
    out["specific_yield_kwh_kwp"] = sy
    out["annual_kwh"] = annual
    log.info(
        "yield: %d planes, %d unique orientations, %.1f MWh/yr total",
        len(out), len(cache), sum(annual) / 1000.0,
    )
    return out
