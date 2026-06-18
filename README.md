# Rooftop Solar → LV Grid Congestion Digital Twin
### Project specification

A 3D GIS + ML system that reconstructs every roof in a study area, estimates realistic photovoltaic (PV) generation per roof plane, aggregates the expected feed-in up to grid feeding areas, and flags where mass solar adoption would exceed the grid's available feed-in capacity — presented as an interactive 3D dashboard. Built entirely on open Dutch data.

---

## 1. Problem framing

The Netherlands is in acute grid congestion (*netcongestie*). For rooftop solar specifically, the binding constraint is usually **feed-in** (*invoeding* / *teruglevering*), not consumption: on sunny, low-load days a neighbourhood's PV systems all export at once, which (a) pushes LV feeder voltages above the statutory limit (EN 50160, roughly +10% of nominal) and (b) thermally overloads the MS/LS distribution transformer through reverse power flow. Netbeheer Nederland already publishes, per 6-digit postcode (PC6), whether feed-in headroom remains — so the question "where would more solar tip an area into congestion?" is concrete, operationally relevant, and verifiable against published data.

Most existing rooftop-solar tools (Google Project Sunroof, Zonatlas, PVGIS) stop at *per-building* yield for homeowners. **The differentiator of this project is the aggregation step**: turning per-roof technical potential into a feeder-level expected peak feed-in, then cross-referencing the operator's published capacity map to identify constrained areas. That is a real DSO planning question rather than a consumer demo.

### Scope honesty (important)

True LV feeder topology — which household sits on which transformer and feeder — is **not** public (it is commercially and security sensitive). The publicly available congestion data is at **PC6 and substation (*onderstation*) granularity**. This spec therefore makes the congestion analysis at PC6 / substation feeding-area level, which matches the resolution of the ground-truth data. This is a deliberate, defensible design choice, not a workaround — and it should be stated plainly in any write-up.

---

## 2. Data sources

All open. Reproject everything to **EPSG:28992 (RD New)** / **EPSG:7415 (RD New + NAP)**.

| Source | Role | Format / access |
|---|---|---|
| **3D BAG** (TU Delft / 3DGI), LoD2.2 | Per-roof-plane geometry → orientation, tilt, area, building height | CityJSON, OBJ, WFS / OGC API; tiled (~hundreds of buildings/tile) — `3dbag.nl` |
| **AHN4 / AHN5** point cloud | 3D shading geometry (neighbouring buildings + vegetation); roof-plane refinement & rooftop superstructures | LAZ point cloud + 0.5 m DTM/DSM GeoTIFF; OGC services via PDOK — `ahn.nl` |
| **BAG** | Building attributes: construction year, use function (*woonfunctie* etc.) → load profile, suitability | PDOK WFS/API |
| **BGT** | Surface / land-cover context (impervious surfaces) | PDOK |
| **PC6 postcode geometry** (CBS) | Aggregation units | PDOK / CBS |
| **Netbeheer Nederland capaciteitskaart** — *invoeding* + *afname* layers | **Ground truth**: per-PC6 feed-in / consumption headroom and queue | Esri feature services (ArcGIS Online, hosted by Esri NL) + Excel — `capaciteitskaart.netbeheernederland.nl` |
| **VIVET capaciteitskaart** (Kadaster, on PDOK) | Substation-level capacity with 3/5/10-yr projections; coarser/forward-looking aggregation | PDOK feature service, quarterly updates |
| **PVGIS** (EU JRC) and/or **KNMI** irradiance | Solar resource input + independent yield benchmark | PVGIS API (TMY / SARAH satellite irradiance); KNMI open-data GHI |
| **CBS / RVO / Klimaatmonitor** PV statistics | Baseline installed PV per region + consumption → adoption calibration and aggregate validation | CSV / open data portals |

Notes that matter for modelling: AHN provides ~10 points/m² and is classified (ground, water, building, structure; high-voltage lines distinguished from AHN4 onward). AHN5 (acquired 2023–2025) is rolling out west-first, so the Randstad/Flevoland is well covered; AHN4 covers the whole country as a fallback. 3D BAG is built from BAG footprints + AHN and is `val3dity`-checked, so roof geometry comes pre-validated.

---

## 3. Data pipeline

Offline Python pipeline, `data/raw → data/interim → data/processed`, driven by a YAML run config (AOI bounding box / municipality, AHN version, scenario set). Cache downloads with a manifest for reproducibility.

**Stage 0 — AOI & ingest.** Pick a study area (a Stedin-relevant municipality, or a PC4 cluster). Pull the intersecting 3D BAG tiles, AHN tiles, BAG attributes, PC6 polygons, and capacity-map features. Reproject to RD New.

**Stage 1 — Roof-plane extraction.** From 3D BAG LoD2.2 CityJSON, extract each `RoofSurface` polygon and compute area, centroid, **azimuth** and **tilt** from the surface normal (compute from geometry directly rather than trusting only the derived attributes, for robustness). Drop planes below a usability threshold (too small, or steep and north-facing). Optionally re-fit planes from a fine AHN-derived DSM via RANSAC to catch dormers/chimneys and to validate the 3D BAG planes.

**Stage 2 — 3D shading / horizon (the interesting GIS step).** Build an obstruction surface from the AHN DSM (buildings + vegetation) across the AOI. For each roof plane — or a sample grid of points on it — compute a horizon profile and a **time-resolved shading mask**: for each sun position (azimuth, elevation) across a representative set of timesteps over the year, determine whether the point is occluded by surrounding geometry. Two viable implementations: GRASS GIS `r.horizon` / `r.sun` over the DSM, or a custom ray-caster over the DSM raster. Output: per-plane horizon/shading factor as a function of sun position, plus a scalar annual shading loss and a sky-view factor.

**Stage 3 — Solar resource join.** Attach PVGIS/KNMI irradiance (DNI/DHI/GHI time series or TMY) to each roof location and **transpose to plane-of-array (POA) irradiance** using the plane's tilt/azimuth (Hay–Davies or Perez transposition via `pvlib`).

**Stage 4 — PV physics.** Run a PV performance model (`pvlib`: POA → cell temperature → DC → AC, with standard derates and inverter clipping) modulated by the Stage-2 shading mask, to get **per-plane hourly and annual generation** per kWp and at an assumed module density (kWp installable per m² of usable roof).

**Stage 5 — Feature assembly.** Produce model-ready tables at roof-plane and building level: tilt, azimuth, usable area, POA irradiance, shading factor, sky-view factor, building height, surrounding building density, tree proximity, construction year, use function, PC6 id, substation id — plus the physics yield estimate and (where available) any observed-generation labels.

**Tech / conventions.** Python with `geopandas`, `shapely`, `pyproj`, `rasterio`, `PDAL` or `laspy` (+ a DSM rasteriser), `cjio`/CityJSON for 3D BAG, `pvlib` for the solar physics, `pandas`/`duckdb` for the feature store. `src/` layout, `pyproject.toml` with optional dependency groups (`geo`, `solar`, `dashboard`, `dev`), `pytest`, GitHub Actions CI — i.e. the same package shape as the I&I project.

---

## 4. ML approach

A naïve "train a model to predict solar yield" framing is weak, because physics already predicts PV yield well — that is exactly what PVGIS and `pvlib` do. The defensible ML contributions here are layered on top of physics, which is both more honest and a clean continuation of the **physics-residual** method from the I&I project.

**(A) Per-roof yield — physics-first with an ML residual (primary).** The `pvlib` + DSM-shading model is the first-principles baseline. A gradient-boosted residual model (XGBoost / LightGBM) then learns *systematic deviations* between the physics estimate and observed generation — the things physics handles crudely at scale: complex partial shading, soiling, real installation derates, snow, clipping. This mirrors the residual-on-top-of-a-physical-model pattern you already used and is the methodologically strongest framing.

**(B) Shading surrogate (optional, for scale).** Exact per-timestep ray-casting over a large DSM is expensive. Train a small surrogate — a CNN on a local DSM patch around each roof, or GBT on engineered horizon features — to emulate the expensive shading computation, so the pipeline scales to many thousands of buildings. This is a legitimate "ML surrogate of an expensive simulator," with the physics computation itself as the training target.

**(C) Adoption / penetration model (optional, for realistic scenarios).** To turn *technical potential* into *expected* feed-in, model the probability that a building adopts PV (logistic / GBT classifier) from building and socioeconomic features, calibrated against observed installed-PV statistics per PC6 (CBS / Klimaatmonitor). This produces realistic adoption scenarios (current, +X%, full technical potential) instead of only a worst case.

**Labels / ground truth — the honest part.** Per-installation generation data is not openly available at scale. In order of rigour:
- Validate the *physics* model against PVGIS's own per-location yield estimates and against aggregate published figures (installed capacity and total solar generation per region from CBS/RVO) — i.e. confirm the bottom-up model reproduces known top-down totals. This is validation, not supervised training.
- If any open monitoring data is reachable (e.g. anonymised PVOutput.org systems with known location/tilt/azimuth, or a DSO pilot set), use it as a supervised target for the residual model — explicitly flagged as opportunistic and limited.
- For adoption: CBS / Klimaatmonitor installed-PV-per-PC6 is the supervision target.

**Aggregation to grid units.** For each PC6 / substation feeding area and each adoption scenario, sum the **expected peak feed-in (kW)** — coincident clear-sky midday generation minus a simple self-consumption estimate from BAG use-function + CBS consumption. Compare against the capacity map's available *invoeding* headroom to produce a **congestion-risk score** (predicted peak feed-in ÷ available headroom).

Net framing for a CV: *physics-led estimation; ML for residual correction, shading surrogate, and adoption; validated against published aggregates and the operator's capacity map.* Far more credible than "AI predicts the grid," and a direct extension of the I&I methodological identity.

---

## 5. Validation strategy

Multi-level, in the spirit of the I&I synthetic harness.

1. **Geometry.** Roof-plane areas/orientations vs 3D BAG attributes and vs an AHN re-fit; spot-check against aerial imagery. Report coverage and disagreement.
2. **Shading.** Cross-validate the DSM shading/horizon for sample roofs between two independent methods (e.g. GRASS `r.sun` vs the custom ray-caster), and against obvious cases (a roof beside a tall building must show afternoon loss). Sanity-check sky-view factors.
3. **Physics yield.** Per-roof annual yield vs PVGIS for the same location/tilt/azimuth. Close agreement expected on unshaded south roofs; divergence on shaded/complex roofs is precisely where the ML residual earns its place. Report MAE / MBE in kWh/kWp.
4. **Aggregate.** Capacity-weighted potential and modelled generation summed per region vs CBS/RVO published solar generation and installed capacity. This is the central "grounded in verifiable industry data" check.
5. **Adoption model.** **Spatial** cross-validation — hold out whole PC4 areas, not random rows, to avoid spatial leakage (the same discipline as in the I&I hotspot work) — against observed installed-PV-per-PC6.
6. **Congestion flag (headline result).** Compare the model's flagged feed-in-constrained PC6/substations against the capacity map's *actual* current feed-in restrictions. If the bottom-up model independently flags areas the DSO has already restricted, that is strong external validation. Report precision/recall against the published restriction map.
7. **Ablations.** Physics-only vs physics+residual; with/without shading; worst-case vs adoption-weighted — to show what each component buys.

**Leakage subtlety:** the capacity map cannot be both a training target and a validation set. Keep it as held-out external validation for the congestion flags; train the adoption model on installation statistics instead.

**Synthetic harness:** build a synthetic neighbourhood with known roof geometry, known PV placement and a known transformer limit, and confirm the aggregation + flagging logic recovers the planted congestion — the analogue of the 10/10 hotspot-recovery harness.

---

## 6. 3D dashboard architecture

Three tiers.

**Data / processing tier (offline Python).** The pipeline above emits: per-roof-plane GeoJSON/glTF with yield + shading attributes; per-PC6/substation aggregates with congestion score and the capacity-map comparison; and building geometry exported as **3D Tiles / glTF**, colour-ready.

**Serving tier.** Portfolio-friendly default is **static-first**: pre-baked 3D Tiles + JSON served from object storage or GitHub Pages. Add a small **FastAPI** backend over PostGIS only if live scenario queries are wanted.

**Frontend tier.** React with one of:
- **deck.gl** (+ MapLibre basemap) — recommended primary. Performant on large meshes/extrusions, easy attribute-driven colouring, React-friendly.
- **CesiumJS** — optional mode for globe-accurate **real sun/shadow at a chosen time**, ingesting 3D BAG as 3D Tiles. Use it for the time-of-day shading visualisation.
- **Potree** — optional raw AHN point-cloud inspector (AHN's own viewer already uses Potree, so it is proven on this exact data).

Layers and interactions:
- Textured/extruded buildings coloured by **per-roof yield**.
- A **feeding-area choropleth** (PC6/substation) extruded or glowing by congestion score, toggled on top.
- The **capacity-map restriction overlay** for direct comparison — the credibility anchor.
- A **scenario selector** (current / +X% / full potential) that re-colours the congestion layer.
- A **sun/time slider** (Cesium mode) showing shading through the day.
- Click a **building** → per-plane breakdown (yield, tilt, azimuth, shading loss); click a **feeding area** → predicted peak feed-in vs available headroom vs model flag vs actual DSO restriction.

The core effect is linking micro to macro: one roof's 3D shading and yield on the one hand, and a whole feeding area turning red when adoption crosses a threshold on the other — with the operator's published restrictions overlaid to show the model's flags line up with reality.

---

## 7. Suggested repo structure

```
rooftop-solar-grid-twin/
  pyproject.toml          # optional deps: [geo], [solar], [dashboard], [dev]
  src/rsgt/
    config/               # AOI + run configs (YAML)
    ingest/               # 3D BAG, AHN, BAG, PC6, capacity-map loaders
    geometry/             # roof-plane extraction, AHN re-fit
    shading/              # DSM build, horizon/ray-cast, surrogate
    solar/                # pvlib physics, POA transposition, yield
    ml/                   # residual model, adoption model, shading surrogate
    aggregate/            # PC6/substation rollup, congestion score
    validate/             # validation harness + synthetic case
    export/               # 3D Tiles / glTF / GeoJSON for the dashboard
  dashboard/              # React + deck.gl (+ optional Cesium / Potree)
  tests/
  .github/workflows/ci.yml
  docs/
```

---

## 8. Phased plan (iterative depth)

- **P0** — AOI + data ingest + reproject, for one small municipality.
- **P1** — Roof planes + `pvlib` physics yield → first per-roof yield map. *Ship a static deck.gl map here for an early visible win.*
- **P2** — DSM shading + shading surrogate.
- **P3** — Aggregation to PC6/substation + capacity-map overlay + congestion score.
- **P4** — Adoption model + scenarios.
- **P5** — Full 3D dashboard (Cesium sun/shadow + scenario toggles) + validation write-up.

Each phase is independently shippable, favouring depth over breadth.

---

## 9. CV / integrity framing

Describe it as: a 3D digital twin that estimates rooftop PV potential **physics-first** (`pvlib` + LiDAR-derived shading), uses ML for **residual correction, a shading surrogate, and adoption modelling**, and validates bottom-up results against **published CBS/RVO totals** and the **Netbeheer Nederland capacity map**. Be explicit that the congestion analysis is at PC6/substation resolution (matching public data), that per-installation labels are limited, and that AI assistance was used in development. Avoid any claim that "AI predicts grid congestion" — the model *estimates feed-in and compares it to the operator's published headroom*, which is both accurate and stronger.

---

*Data sources: 3dbag.nl · ahn.nl · pdok.nl · capaciteitskaart.netbeheernederland.nl · PVGIS (EU JRC) · CBS / RVO / Klimaatmonitor. All open data; verify current licence terms per source before publishing results.*
