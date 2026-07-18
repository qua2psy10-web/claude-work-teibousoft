"""臨界すべり円（最小安全率を与える円）の自動探索。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from .model import LoadCase, Section, SearchGrid
from .stability import CircleResult, analyze_circle


@dataclass
class CaseResult:
    """1照査ケースの結果。"""

    case: LoadCase
    critical: Optional[CircleResult]
    evaluated: int

    @property
    def ok(self) -> bool:
        if self.critical is None:
            return False
        return self.critical.fs >= self.case.allowable_fs

    @property
    def judgement(self) -> str:
        if self.critical is None:
            return "解析不能"
        return "OK" if self.ok else "NG"


def _auto_grid(section: Section, grid: SearchGrid) -> SearchGrid:
    """未設定の探索範囲を断面から自動決定する。"""
    surf = section.surface
    xs = [p.x for p in surf]
    ys = [p.y for p in surf]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    height = ymax - ymin
    width = xmax - xmin

    g = SearchGrid(
        xc_min=grid.xc_min,
        xc_max=grid.xc_max,
        yc_min=grid.yc_min,
        yc_max=grid.yc_max,
        nx=grid.nx,
        ny=grid.ny,
        tangent_y_min=grid.tangent_y_min,
        tangent_y_max=grid.tangent_y_max,
        nr=grid.nr,
        n_slices=grid.n_slices,
    )

    # 円中心は天端側の上方に置くのが一般的
    if g.xc_min is None:
        g.xc_min = xmin + width * 0.15
    if g.xc_max is None:
        g.xc_max = xmax - width * 0.05
    if g.yc_min is None:
        g.yc_min = ymax + height * 0.2
    if g.yc_max is None:
        g.yc_max = ymax + max(height * 2.0, 5.0)

    # すべり面の到達最深標高（接線）
    if g.tangent_y_min is None:
        g.tangent_y_min = ymin - max(height * 1.0, 3.0)
    if g.tangent_y_max is None:
        g.tangent_y_max = ymin + height * 0.5
    return g


def search_critical(
    section: Section, case: LoadCase, grid: SearchGrid
) -> CaseResult:
    """格子探索により最小安全率のすべり円を求める。"""
    g = _auto_grid(section, grid)
    best: Optional[CircleResult] = None
    count = 0

    xs = _linspace(g.xc_min, g.xc_max, g.nx)
    ys = _linspace(g.yc_min, g.yc_max, g.ny)
    tangents = _linspace(g.tangent_y_min, g.tangent_y_max, g.nr)

    for xc in xs:
        for yc in ys:
            for ty in tangents:
                # すべり面が標高 ty に接する円 → R = yc - ty
                r = yc - ty
                if r <= 0.1:
                    continue
                res = analyze_circle(section, case, xc, yc, r, g.n_slices)
                if res is None:
                    continue
                count += 1
                if best is None or res.fs < best.fs:
                    best = res

    # 粗探索の周辺を細かく再探索
    if best is not None:
        best = _refine(section, case, best, g)

    return CaseResult(case=case, critical=best, evaluated=count)


def _refine(
    section: Section,
    case: LoadCase,
    seed: CircleResult,
    g: SearchGrid,
    passes: int = 2,
) -> CircleResult:
    """臨界円近傍を段階的に細分化して精度を上げる。"""
    best = seed
    dx = (g.xc_max - g.xc_min) / max(g.nx - 1, 1)
    dy = (g.yc_max - g.yc_min) / max(g.ny - 1, 1)
    dt = (g.tangent_y_max - g.tangent_y_min) / max(g.nr - 1, 1)
    for _ in range(passes):
        dx *= 0.5
        dy *= 0.5
        dt *= 0.5
        xs = _linspace(best.xc - dx, best.xc + dx, 5)
        ys = _linspace(best.yc - dy, best.yc + dy, 5)
        ty0 = best.yc - best.r
        tys = _linspace(ty0 - dt, ty0 + dt, 5)
        for xc in xs:
            for yc in ys:
                for ty in tys:
                    r = yc - ty
                    if r <= 0.1:
                        continue
                    res = analyze_circle(
                        section, case, xc, yc, r, g.n_slices
                    )
                    if res is not None and res.fs < best.fs:
                        best = res
    return best


def _linspace(a: float, b: float, n: int) -> List[float]:
    if n <= 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def run_all(section: Section, cases: List[LoadCase], grid: SearchGrid) -> List[CaseResult]:
    return [search_critical(section, c, grid) for c in cases]
