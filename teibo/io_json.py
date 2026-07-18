"""JSON 入力ファイルの読み込み。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .model import (
    AnalysisInput,
    LoadCase,
    PhreaticLine,
    Point,
    Section,
    SearchGrid,
    SoilLayer,
)


def _points(raw: List[Any]) -> List[Point]:
    return [Point(float(p[0]), float(p[1])) for p in raw]


def load_input(path: str) -> AnalysisInput:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_input(data)


def parse_input(data: Dict[str, Any]) -> AnalysisInput:
    sec = data["section"]

    layers: List[SoilLayer] = []
    for ly in sec["layers"]:
        layers.append(
            SoilLayer(
                name=ly.get("name", "土層"),
                top=_points(ly["top"]),
                gamma=float(ly["gamma"]),
                gamma_sat=float(ly.get("gamma_sat", ly["gamma"])),
                c=float(ly.get("c", 0.0)),
                phi=float(ly.get("phi", 0.0)),
            )
        )

    phreatic = None
    if sec.get("phreatic"):
        phreatic = PhreaticLine(points=_points(sec["phreatic"]))

    section = Section(
        layers=layers,
        phreatic=phreatic,
        name=sec.get("name", "堤防断面"),
    )

    cases: List[LoadCase] = []
    for c in data.get("cases", []):
        cases.append(
            LoadCase(
                name=c.get("name", "ケース"),
                kh=float(c.get("kh", 0.0)),
                allowable_fs=float(c.get("allowable_fs", 1.2)),
                method=c.get("method", "fellenius"),
            )
        )
    if not cases:
        cases = [
            LoadCase(name="常時", kh=0.0, allowable_fs=1.2, method="fellenius"),
            LoadCase(name="地震時", kh=0.15, allowable_fs=1.0, method="fellenius"),
        ]

    g = data.get("grid", {})
    grid = SearchGrid(
        xc_min=g.get("xc_min"),
        xc_max=g.get("xc_max"),
        yc_min=g.get("yc_min"),
        yc_max=g.get("yc_max"),
        nx=int(g.get("nx", 15)),
        ny=int(g.get("ny", 15)),
        tangent_y_min=g.get("tangent_y_min"),
        tangent_y_max=g.get("tangent_y_max"),
        nr=int(g.get("nr", 12)),
        n_slices=int(g.get("n_slices", 40)),
    )

    return AnalysisInput(section=section, cases=cases, grid=grid)
