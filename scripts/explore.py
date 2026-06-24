#!/usr/bin/env python
"""Standalone runner for the P0.5 *explore* step.

Profiles the data P0 ingested for an AOI and writes figures + an HTML report +
``insights.json`` under ``data/processed/explore/``. This is the same step as
``rsgt explore``, wrapped as a script that prints a short, human-readable summary
and the path to the report.

Usage
-----
    python scripts/explore.py -c configs/oudewater.yaml
    python scripts/explore.py -c configs/example_small.yaml --max-raster-dim 800

Needs the ``geo`` and ``viz`` extras::

    pip install -e ".[geo,viz]"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running from a source checkout without installing (src/ layout).
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rsgt.config.loader import load_config  # noqa: E402
from rsgt.explore import run_explore  # noqa: E402
from rsgt.ingest.pipeline import Paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-c", "--config", required=True, help="Path to a run-config YAML")
    parser.add_argument("--base-dir", help="Base dir for data/ (default: config's repo root)")
    parser.add_argument("--max-raster-dim", type=int, default=1200,
                        help="Decimate AHN rasters to this many pixels on the long side")
    parser.add_argument("--no-plots", action="store_true", help="Skip the static figures (no matplotlib)")
    parser.add_argument("--no-map", action="store_true", help="Skip the interactive map (no folium)")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    args = parser.parse_args(argv)

    level = logging.WARNING if args.verbose == 0 else logging.INFO if args.verbose == 1 else logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")

    cfg = load_config(args.config)
    base_dir = args.base_dir or Path(args.config).resolve().parent.parent
    profile = run_explore(
        cfg,
        base_dir=base_dir,
        max_raster_dim=args.max_raster_dim,
        make_plots=not args.no_plots,
        make_map=not args.no_map,
    )

    out_dir = Paths.from_config(cfg, base_dir).processed / "explore"
    print(f"\nData exploration for AOI '{profile.aoi_name}':\n")
    if profile.headline:
        for line in profile.headline:
            print(f"  • {line}")
    else:
        print("  (no artefacts found — has P0 ingest run for this config?)")
    missing = {k: v for k, v in profile.load_status.items() if v != "ok"}
    if missing:
        print("\n  artefact load status:")
        for k, v in missing.items():
            print(f"    - {k}: {v}")
    print(f"\nReport:   {out_dir / 'report.html'}")
    print(f"Insights: {out_dir / 'insights.json'}")
    map_html = out_dir / "map.html"
    if map_html.is_file():
        print(f"Map:      {map_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
