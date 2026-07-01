"""Minimal reader for the CityJSONSeq files P0 writes.

A CityJSONSeq (``.city.jsonl``) is one JSON object per line: line 1 is the CityJSON
*header* (carrying the ``transform`` that de-quantises integer vertices into real
RD-New + NAP coordinates), and every following line is one ``CityJSONFeature``
(one building). P0 already re-quantised all features onto the header transform, so
a single transform decodes the whole file.

We deliberately do not depend on ``cjio``: P1 only needs to walk LoD2.2 semantic
surfaces, which is a few lines and keeps the dependency surface small.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

Transform = dict[str, list[float]]
Coord = tuple[float, float, float]


def read_header(path: str | Path) -> Transform | None:
    """Return the CityJSON ``transform`` from line 1, or ``None`` if the file is empty."""
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return None
    with p.open("r", encoding="utf-8") as fh:
        first = fh.readline()
    if not first.strip():
        return None
    return json.loads(first)["transform"]


def iter_features(path: str | Path) -> Iterator[dict]:
    """Yield each ``CityJSONFeature`` dict (skips the header line)."""
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return
    with p.open("r", encoding="utf-8") as fh:
        fh.readline()  # header
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def decode_vertices(feature: dict, transform: Transform) -> list[Coord]:
    """Apply ``transform`` to a feature's integer vertices -> real (x, y, z) metres."""
    sx, sy, sz = transform["scale"]
    tx, ty, tz = transform["translate"]
    return [(v[0] * sx + tx, v[1] * sy + ty, v[2] * sz + tz) for v in feature["vertices"]]


def iter_semantic_surfaces(
    geometry: dict,
) -> Iterator[tuple[str, list[list[int]]]]:
    """Yield ``(surface_type, surface_boundary)`` for a semantically-tagged geometry.

    Handles both ``Solid`` (boundaries nested as shell -> surface -> ring -> index,
    ``values`` as one list per shell) and ``MultiSurface`` (surface -> ring -> index,
    ``values`` as a flat list). ``surface_boundary`` is the list of rings, ring 0
    being the exterior.
    """
    semantics = geometry.get("semantics")
    if not semantics:
        return
    surfaces = semantics.get("surfaces", [])
    values = semantics.get("values", [])
    boundaries = geometry.get("boundaries", [])
    gtype = geometry.get("type")

    if gtype == "Solid":
        for shell, shell_vals in zip(boundaries, values, strict=False):
            for surface, val in zip(shell, shell_vals, strict=False):
                if val is None:
                    continue
                yield surfaces[val].get("type", ""), surface
    elif gtype in ("MultiSurface", "CompositeSurface"):
        for surface, val in zip(boundaries, values, strict=False):
            if val is None:
                continue
            yield surfaces[val].get("type", ""), surface
