"""Typed run-configuration for the rsgt pipeline.

A run is fully described by a single YAML file (see ``configs/``). The models here
validate that file and supply sensible defaults so most configs stay short. The
defaults point at the real, verified Dutch open-data endpoints used by P0:

* 3D BAG   -> OGC API Features at ``api.3dbag.nl`` (CityJSONFeatures, CRS EPSG:7415)
* AHN      -> PDOK WCS (``dsm_05m`` / ``dtm_05m`` coverages)
* BAG      -> PDOK WFS ``bag:pand`` / ``bag:verblijfsobject``
* PC6      -> PDOK/CBS WFS ``postcode6:postcode6``
* boundary -> PDOK OGC API Features ``gemeentegebied``

The capacity map (Netbeheer Nederland) is an ArcGIS feature service whose exact
URL must be supplied by the user (it is not discoverable from a static page); the
defaults below are placeholders and the source is disabled unless configured.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

# Coordinate reference systems used throughout the project.
RD_NEW = "EPSG:28992"          # Amersfoort / RD New (planar, metres)
RD_NEW_NAP = "EPSG:7415"       # RD New + NAP height (3D; 3D BAG storage CRS)
WGS84 = "EPSG:4326"            # lon/lat
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

BBox = tuple[float, float, float, float]


class AOIConfig(BaseModel):
    """Area of interest. Provide either a municipality name or an explicit bbox.

    ``municipality`` is resolved against the PDOK 'bestuurlijke gebieden' service.
    ``bbox`` is in RD New (EPSG:28992) as ``[minx, miny, maxx, maxy]`` and, when
    given alongside a municipality, acts as an offline fallback / clip.
    """

    name: str = Field(..., description="Short slug used for output filenames, e.g. 'oudewater'.")
    municipality: str | None = Field(
        default=None, description="Official municipality name, e.g. 'Oudewater'."
    )
    bbox: BBox | None = Field(
        default=None, description="RD New bbox [minx, miny, maxx, maxy] (metres)."
    )
    buffer_m: float = Field(
        default=0.0, ge=0.0, description="Buffer (metres) added around the resolved AOI."
    )

    @field_validator("bbox")
    @classmethod
    def _bbox_ordered(cls, v: BBox | None) -> BBox | None:
        if v is None:
            return v
        minx, miny, maxx, maxy = v
        if not (maxx > minx and maxy > miny):
            raise ValueError("bbox must be [minx, miny, maxx, maxy] with max > min")
        return v

    @model_validator(mode="after")
    def _need_one(self) -> AOIConfig:
        if self.municipality is None and self.bbox is None:
            raise ValueError("AOI needs at least one of 'municipality' or 'bbox'")
        return self


class PathsConfig(BaseModel):
    """Where the pipeline reads and writes. All relative to ``root``."""

    root: str = Field(default="data", description="Root data directory.")
    raw: str = Field(default="raw")
    interim: str = Field(default="interim")
    processed: str = Field(default="processed")


class Bag3DConfig(BaseModel):
    enabled: bool = True
    api_url: str = "https://api.3dbag.nl"
    collection: str = "pand"
    # 3D BAG only serves CRS 7415; bbox queries must declare this.
    bbox_crs: str = "http://www.opengis.net/def/crs/EPSG/0/7415"
    page_size: int = Field(default=200, ge=1, le=1000)
    max_features: int | None = Field(
        default=None, description="Safety cap on total CityJSONFeatures fetched (None = no cap)."
    )


class AHNConfig(BaseModel):
    enabled: bool = True
    version: Literal["AHN4", "AHN5"] = "AHN4"
    wcs_url: str = "https://service.pdok.nl/rws/ahn/wcs/v1_0"
    dsm_coverage: str = "dsm_05m"
    dtm_coverage: str = "dtm_05m"
    resolution_m: float = Field(default=0.5, gt=0)
    # WCS servers cap request size; we tile GetCoverage into chunks this many
    # metres on a side and (optionally) mosaic them.
    tile_size_m: float = Field(default=1000.0, gt=0)
    mosaic: bool = True
    download_dsm: bool = True
    download_dtm: bool = True
    download_laz: bool = Field(
        default=False, description="Download raw LAZ point-cloud tiles (large; off by default)."
    )


class WFSSourceConfig(BaseModel):
    """Generic PDOK WFS 2.0 source (BAG, PC6, ...)."""

    enabled: bool = True
    wfs_url: str
    type_names: list[str]
    page_size: int = Field(default=1000, ge=1)


class BagConfig(WFSSourceConfig):
    """BAG building attributes via PDOK WFS (defaults so partial configs work)."""

    wfs_url: str = "https://service.pdok.nl/lv/bag/wfs/v2_0"
    type_names: list[str] = Field(default_factory=lambda: ["bag:pand"])


class PC6Config(WFSSourceConfig):
    """PC6 postcode polygons via PDOK/CBS WFS."""

    wfs_url: str = "https://service.pdok.nl/cbs/postcode6/2023/wfs/v1_0"
    type_names: list[str] = Field(default_factory=lambda: ["postcode6:postcode6"])


class CapacityConfig(BaseModel):
    """Netbeheer Nederland capaciteitskaart (ArcGIS Feature Service).

    The service URL is not published as a static link; obtain the FeatureServer
    layer URLs from the map's network requests and set them here. Until then the
    source stays disabled and the pipeline skips it with a clear message.
    """

    enabled: bool = False
    # e.g. "https://services.arcgis.com/<org>/arcgis/rest/services/<svc>/FeatureServer"
    feature_server: str | None = None
    invoeding_layer: int | None = Field(
        default=None, description="Layer id of the feed-in (invoeding) headroom layer."
    )
    afname_layer: int | None = Field(
        default=None, description="Layer id of the consumption (afname) headroom layer."
    )
    excel_url: str | None = Field(
        default=None, description="Fallback: published capacity Excel/CSV URL."
    )
    page_size: int = Field(default=1000, ge=1)


class BoundaryConfig(BaseModel):
    """PDOK 'bestuurlijke gebieden' OGC API Features — municipality boundaries."""

    ogc_url: str = (
        "https://api.pdok.nl/kadaster/bestuurlijkegebieden/ogc/v1"
        "/collections/gemeentegebied/items"
    )
    name_field: str = "naam"


class SourcesConfig(BaseModel):
    boundary: BoundaryConfig = Field(default_factory=BoundaryConfig)
    bag3d: Bag3DConfig = Field(default_factory=Bag3DConfig)
    ahn: AHNConfig = Field(default_factory=AHNConfig)
    bag: BagConfig = Field(default_factory=BagConfig)
    pc6: PC6Config = Field(default_factory=PC6Config)
    capacity: CapacityConfig = Field(default_factory=CapacityConfig)


class HTTPConfig(BaseModel):
    timeout_s: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=4, ge=0)
    backoff_s: float = Field(default=1.0, ge=0)
    user_agent: str = "rsgt/0.0.1 (+https://github.com/) rooftop-solar-grid-twin"


class RunConfig(BaseModel):
    """Top-level run configuration."""

    aoi: AOIConfig
    paths: PathsConfig = Field(default_factory=PathsConfig)
    target_crs: str = RD_NEW
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    http: HTTPConfig = Field(default_factory=HTTPConfig)

    @field_validator("target_crs")
    @classmethod
    def _crs_form(cls, v: str, info: ValidationInfo) -> str:
        if not v or ":" not in v:
            raise ValueError("target_crs must look like 'EPSG:28992'")
        return v
