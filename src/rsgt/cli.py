"""Command-line interface for the rsgt pipeline.

Examples
--------
Run the full Stage 0 ingest for a config::

    rsgt ingest --config configs/oudewater.yaml

Only resolve and save the AOI (no downloads)::

    rsgt aoi --config configs/oudewater.yaml

Ingest a subset of sources, forcing re-download::

    rsgt ingest -c configs/oudewater.yaml --only bag3d ahn --force

Profile + visualise what P0 ingested (the P0.5 explore step)::

    rsgt explore -c configs/oudewater.yaml

Run P1 — per-roof physics yield + deck.gl map + PVGIS validation::

    rsgt yield -c configs/oudewater.yaml

Just extract roof planes (P1 step 1), without the solar physics::

    rsgt roofs -c configs/oudewater.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config.loader import load_config
from .ingest.aoi import resolve_aoi
from .ingest.download import build_session
from .ingest.pipeline import ALL_SOURCES, Paths, run_ingest


def _setup_logging(verbosity: int) -> None:
    level = logging.WARNING if verbosity == 0 else logging.INFO if verbosity == 1 else logging.DEBUG
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s"
    )


def _cmd_ingest(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    base_dir = args.base_dir or Path(args.config).resolve().parent.parent
    summary = run_ingest(cfg, base_dir=base_dir, only=args.only, force=args.force)
    print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
    statuses = [r.get("status") for r in summary.results.values()]
    return 1 if "error" in statuses else 0


def _cmd_aoi(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    base_dir = args.base_dir or Path(args.config).resolve().parent.parent
    paths = Paths.from_config(cfg, base_dir)
    paths.ensure()
    session = build_session(cfg.http)
    aoi = resolve_aoi(cfg.aoi, cfg.sources.boundary, session, timeout=cfg.http.timeout_s)
    out = aoi.save(paths.interim / f"{aoi.name}_aoi.geojson")
    print(
        json.dumps(
            {"name": aoi.name, "source": aoi.source, "bbox_rd": list(aoi.bbox), "saved": str(out)},
            indent=2,
        )
    )
    return 0


def _cmd_explore(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    base_dir = args.base_dir or Path(args.config).resolve().parent.parent
    # Imported lazily: the explore step pulls in geopandas/rasterio/matplotlib,
    # which the lightweight `rsgt aoi`/`--help` paths must not require.
    from .explore import run_explore

    profile = run_explore(
        cfg,
        base_dir=base_dir,
        max_raster_dim=args.max_raster_dim,
        make_plots=not args.no_plots,
        make_map=not args.no_map,
    )
    print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _cmd_roofs(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    base_dir = args.base_dir or Path(args.config).resolve().parent.parent
    from .solar.pipeline import run_roofs

    result = run_roofs(cfg, base_dir=base_dir, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _cmd_yield(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    base_dir = args.base_dir or Path(args.config).resolve().parent.parent
    # Lazy import: the P1 physics stack (pvlib) is the [solar] extra.
    from .solar.pipeline import run_yield

    summary = run_yield(
        cfg,
        base_dir=base_dir,
        make_map=not args.no_map,
        validate=not args.no_validation,
        force=args.force,
    )
    print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
    return 1 if summary.result.get("yield", {}).get("status") == "error" else 0


def build_parser() -> argparse.ArgumentParser:
    # -v is a per-subcommand flag (e.g. `rsgt ingest -c x -vv`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v", "--verbose", action="count", default=0, help="-v info, -vv debug"
    )

    parser = argparse.ArgumentParser(prog="rsgt", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ing = sub.add_parser("ingest", parents=[common], help="Run Stage 0 ingest for a config")
    p_ing.add_argument("-c", "--config", required=True, help="Path to a run-config YAML")
    p_ing.add_argument(
        "--only", nargs="+", choices=ALL_SOURCES, help="Restrict to these sources"
    )
    p_ing.add_argument("--force", action="store_true", help="Ignore cache; re-download")
    p_ing.add_argument("--base-dir", help="Base dir for data/ (default: config's repo root)")
    p_ing.set_defaults(func=_cmd_ingest)

    p_aoi = sub.add_parser("aoi", parents=[common], help="Resolve and save the AOI only")
    p_aoi.add_argument("-c", "--config", required=True, help="Path to a run-config YAML")
    p_aoi.add_argument("--base-dir", help="Base dir for data/ (default: config's repo root)")
    p_aoi.set_defaults(func=_cmd_aoi)

    p_exp = sub.add_parser(
        "explore", parents=[common], help="Profile + visualise the P0 ingest (P0.5)"
    )
    p_exp.add_argument("-c", "--config", required=True, help="Path to a run-config YAML")
    p_exp.add_argument("--base-dir", help="Base dir for data/ (default: config's repo root)")
    p_exp.add_argument(
        "--max-raster-dim", type=int, default=1200,
        help="Decimate AHN rasters to this many pixels on the long side (default: 1200)",
    )
    p_exp.add_argument(
        "--no-plots", action="store_true", help="Skip the static figures (no matplotlib)"
    )
    p_exp.add_argument(
        "--no-map", action="store_true", help="Skip the interactive Leaflet map (no folium)"
    )
    p_exp.set_defaults(func=_cmd_explore)

    p_roofs = sub.add_parser(
        "roofs", parents=[common], help="P1 step 1: extract roof planes from 3D BAG"
    )
    p_roofs.add_argument("-c", "--config", required=True, help="Path to a run-config YAML")
    p_roofs.add_argument("--base-dir", help="Base dir for data/ (default: config's repo root)")
    p_roofs.add_argument("--force", action="store_true", help="Re-extract even if cached")
    p_roofs.set_defaults(func=_cmd_roofs)

    p_yield = sub.add_parser(
        "yield", parents=[common], help="Run P1: per-roof physics yield + map + validation"
    )
    p_yield.add_argument("-c", "--config", required=True, help="Path to a run-config YAML")
    p_yield.add_argument("--base-dir", help="Base dir for data/ (default: config's repo root)")
    p_yield.add_argument("--force", action="store_true", help="Ignore caches; recompute")
    p_yield.add_argument("--no-map", action="store_true", help="Skip the deck.gl map export")
    p_yield.add_argument(
        "--no-validation", action="store_true", help="Skip the PVGIS validation (no network)"
    )
    p_yield.set_defaults(func=_cmd_yield)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
