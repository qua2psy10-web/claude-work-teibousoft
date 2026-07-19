"""感度分析。

指定した土層の土質定数（c / φ / γt / γsat）を複数の値に差し替えて
臨界すべり円探索を再実行し、最小安全率 Fs の変化を調べる。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import List, Optional

from .model import LoadCase, SearchGrid, Section, SensitivityTarget
from .search import run_all

_PARAM_LABELS = {
    "c": "c (kN/m2)",
    "phi": "φ (度)",
    "gamma": "γt (kN/m3)",
    "gamma_sat": "γsat (kN/m3)",
}


@dataclass
class SensitivityRow:
    """1つのパラメータ値に対する各ケースの Fs。"""

    value: float
    fs_by_case: List[Optional[float]] = field(default_factory=list)


@dataclass
class SensitivityResult:
    """1つの感度分析対象の結果表。"""

    target: SensitivityTarget
    case_names: List[str]
    rows: List[SensitivityRow] = field(default_factory=list)

    @property
    def param_label(self) -> str:
        return _PARAM_LABELS.get(self.target.param, self.target.param)


def _vary_section(section: Section, target: SensitivityTarget, value: float) -> Section:
    """対象層のパラメータを差し替えた断面の複製を返す。"""
    sec = copy.deepcopy(section)
    for layer in sec.layers:
        if layer.name == target.layer:
            setattr(layer, target.param, value)
            return sec
    raise ValueError(f"感度分析: 層 '{target.layer}' が見つかりません")


def run_sensitivity(
    section: Section,
    cases: List[LoadCase],
    grid: SearchGrid,
    targets: List[SensitivityTarget],
) -> List[SensitivityResult]:
    """感度分析を実行する。"""
    results: List[SensitivityResult] = []
    for target in targets:
        table = SensitivityResult(
            target=target, case_names=[c.name for c in cases]
        )
        for value in target.values:
            sec = _vary_section(section, target, value)
            case_results = run_all(sec, cases, grid)
            row = SensitivityRow(value=value)
            for cr in case_results:
                row.fs_by_case.append(cr.critical.fs if cr.critical else None)
            table.rows.append(row)
        results.append(table)
    return results
