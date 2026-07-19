"""対策工の照査。

対策工（押え盛土・地盤改良・ドレーン工など）を適用した断面を生成し、
無対策断面と同じ照査ケースで再照査して Fs を比較する。

1つの対策工「案」は次の効果を任意に組み合わせられる:
    berm:         押え盛土（地表面に盛土ブロックを追加）
    improvements: 地盤改良（範囲内の c・φ を改良後の値に差し替え、
                  液状化判定の対象外とする）
    phreatic:     浸潤線の差し替え（ドレーン工などによる低下を表現）
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import List, Optional

from .geometry import interp_polyline
from .model import (
    ImprovementZone,
    LoadCase,
    PhreaticLine,
    Point,
    SearchGrid,
    Section,
    SoilLayer,
)
from .search import CaseResult, run_all


@dataclass
class Berm:
    """押え盛土。

    top は盛土後の表面形状（footprint 範囲の折れ線）。既存地表面より
    高い部分だけが盛土として追加される。
    """

    top: List[Point]
    gamma: float
    gamma_sat: float
    c: float
    phi: float
    name: str = "押え盛土"

    def __post_init__(self) -> None:
        if len(self.top) < 2:
            raise ValueError(f"押え盛土 '{self.name}': top は2点以上必要です")


@dataclass
class Countermeasure:
    """対策工の1案。"""

    name: str
    berm: Optional[Berm] = None
    improvements: List[ImprovementZone] = field(default_factory=list)
    phreatic: Optional[PhreaticLine] = None


@dataclass
class CountermeasureResult:
    """1案の照査結果。"""

    countermeasure: Countermeasure
    section: Section
    results: List[CaseResult]

    @property
    def all_ok(self) -> bool:
        return all(r.ok for r in self.results)


def _merged_surface(surf: List[Point], berm_top: List[Point]) -> List[Point]:
    """既存地表面と盛土表面の max を取った新しい地表面折れ線。"""
    xs = sorted({p.x for p in surf} | {p.x for p in berm_top})
    xs = [x for x in xs if surf[0].x <= x <= surf[-1].x]

    # 折れ線同士の交差点を追加（max が折れる位置を正確に拾う）
    extra: List[float] = []
    for a, b in zip(xs, xs[1:]):
        ys_a, ys_b = interp_polyline(surf, a), interp_polyline(surf, b)
        yb_a, yb_b = interp_polyline(berm_top, a), interp_polyline(berm_top, b)
        if None in (ys_a, ys_b, yb_a, yb_b):
            continue
        da, db = yb_a - ys_a, yb_b - ys_b
        if da * db < 0:
            t = da / (da - db)
            extra.append(a + t * (b - a))
    xs = sorted(set(xs) | set(extra))

    pts: List[Point] = []
    for x in xs:
        ys = interp_polyline(surf, x)
        if ys is None:
            continue
        yb = interp_polyline(berm_top, x)
        y = max(ys, yb) if yb is not None else ys
        pts.append(Point(x, y))
    return pts


def apply_countermeasure(section: Section, cm: Countermeasure) -> Section:
    """対策工を適用した断面を返す（元の断面は変更しない）。"""
    sec = copy.deepcopy(section)
    if cm.berm is not None:
        new_surface = _merged_surface(sec.surface, cm.berm.top)
        berm_layer = SoilLayer(
            name=cm.berm.name,
            top=new_surface,
            gamma=cm.berm.gamma,
            gamma_sat=cm.berm.gamma_sat,
            c=cm.berm.c,
            phi=cm.berm.phi,
        )
        sec.layers = [berm_layer] + sec.layers
    if cm.improvements:
        sec.improvements = list(sec.improvements) + list(cm.improvements)
    if cm.phreatic is not None:
        sec.phreatic = cm.phreatic
        sec.phreatic_estimated = False
    sec.name = f"{section.name}（{cm.name}）"
    return sec


def run_countermeasures(
    section: Section,
    cases: List[LoadCase],
    grid: SearchGrid,
    countermeasures: List[Countermeasure],
) -> List[CountermeasureResult]:
    """各対策工案について全ケースを再照査する。"""
    out: List[CountermeasureResult] = []
    for cm in countermeasures:
        sec = apply_countermeasure(section, cm)
        results = run_all(sec, cases, grid)
        out.append(
            CountermeasureResult(countermeasure=cm, section=sec, results=results)
        )
    return out
