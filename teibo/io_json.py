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
    SensitivityTarget,
    SoilLayer,
    Surcharge,
    TensionCrack,
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

    surcharges: List[Surcharge] = []
    for sc in sec.get("surcharges", []):
        surcharges.append(
            Surcharge(
                x_start=float(sc["x_start"]),
                x_end=float(sc["x_end"]),
                q=float(sc["q"]),
                name=sc.get("name", "載荷重"),
            )
        )

    external_water = None
    if sec.get("external_water"):
        external_water = _points(sec["external_water"])

    tension_crack = None
    if sec.get("tension_crack"):
        tc = sec["tension_crack"]
        tension_crack = TensionCrack(
            depth=float(tc["depth"]),
            water_depth=float(tc.get("water_depth", 0.0)),
        )

    section = Section(
        layers=layers,
        phreatic=phreatic,
        name=sec.get("name", "堤防断面"),
        surcharges=surcharges,
        external_water=external_water,
        tension_crack=tension_crack,
    )

    # 浸潤線の自動推定（明示指定があればそちらを優先）
    seep = sec.get("seepage")
    if section.phreatic is None and seep:
        from .seepage import estimate_phreatic

        section.phreatic = estimate_phreatic(
            section,
            water_level=float(seep["water_level"]),
            waterside=seep.get("waterside", "left"),
            tail_level=(
                float(seep["tail_level"]) if seep.get("tail_level") is not None else None
            ),
            n_points=int(seep.get("n_points", 20)),
        )
        section.phreatic_estimated = True

    cases: List[LoadCase] = []
    for c in data.get("cases", []):
        case_phreatic = None
        if c.get("phreatic"):
            case_phreatic = PhreaticLine(points=_points(c["phreatic"]))
        # external_water: キーなし → 継承 (None) / 空リスト → 外水なし / 折れ線 → 差し替え
        case_ext = None
        if "external_water" in c:
            case_ext = _points(c["external_water"]) if c["external_water"] else []
        cases.append(
            LoadCase(
                name=c.get("name", "ケース"),
                kh=float(c.get("kh", 0.0)),
                allowable_fs=float(c.get("allowable_fs", 1.2)),
                method=c.get("method", "fellenius"),
                phreatic=case_phreatic,
                external_water=case_ext,
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
        y_lower_limit=g.get("y_lower_limit"),
        x_entry_min=g.get("x_entry_min"),
        x_entry_max=g.get("x_entry_max"),
        x_exit_min=g.get("x_exit_min"),
        x_exit_max=g.get("x_exit_max"),
    )

    sensitivity: List[SensitivityTarget] = []
    for s in data.get("sensitivity", []):
        sensitivity.append(
            SensitivityTarget(
                layer=s["layer"],
                param=s["param"],
                values=[float(v) for v in s["values"]],
            )
        )

    return AnalysisInput(
        section=section, cases=cases, grid=grid, sensitivity=sensitivity
    )
