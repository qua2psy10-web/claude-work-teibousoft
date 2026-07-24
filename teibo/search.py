"""臨界すべり円（最小安全率を与える円）の自動探索。"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
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
        y_lower_limit=grid.y_lower_limit,
        x_entry_min=grid.x_entry_min,
        x_entry_max=grid.x_entry_max,
        x_exit_min=grid.x_exit_min,
        x_exit_max=grid.x_exit_max,
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
    # 下限拘束があれば接線範囲も切り上げる
    if g.y_lower_limit is not None and g.tangent_y_min < g.y_lower_limit:
        g.tangent_y_min = g.y_lower_limit
    return g


def _passes_constraints(g: SearchGrid, res: CircleResult) -> bool:
    """すべり円の拘束条件（始端・終端位置）を満たすか判定する。"""
    if not res.slices:
        return False
    xl = res.slices[0].x_mid - res.slices[0].width / 2
    xr = res.slices[-1].x_mid + res.slices[-1].width / 2
    if g.x_entry_min is not None and xl < g.x_entry_min:
        return False
    if g.x_entry_max is not None and xl > g.x_entry_max:
        return False
    if g.x_exit_min is not None and xr < g.x_exit_min:
        return False
    if g.x_exit_max is not None and xr > g.x_exit_max:
        return False
    return True


def search_critical(
    section: Section, case: LoadCase, grid: SearchGrid
) -> CaseResult:
    """最小安全率のすべり面を求める。

    method="spencer" のケースは円中心探索を行わず、指定された
    非円弧すべり面をスペンサー法で照査する。
    """
    if case.method == "spencer":
        if case.slip_surface:
            # すべり面が指定されていればそれを評価
            from .spencer import analyze_spencer

            res = analyze_spencer(section, case.slip_surface, case, grid.n_slices)
            return CaseResult(case=case, critical=res, evaluated=1 if res else 0)
        # 未指定なら臨界な非円弧すべり面を自動探索
        from .ncsearch import search_noncircular

        res = search_noncircular(section, case, grid)
        return CaseResult(case=case, critical=res, evaluated=1 if res else 0)

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
                if g.y_lower_limit is not None and yc - r < g.y_lower_limit - 1e-9:
                    continue
                res = analyze_circle(section, case, xc, yc, r, g.n_slices)
                if res is None or not _passes_constraints(g, res):
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
                    if (
                        g.y_lower_limit is not None
                        and yc - r < g.y_lower_limit - 1e-9
                    ):
                        continue
                    res = analyze_circle(
                        section, case, xc, yc, r, g.n_slices
                    )
                    if (
                        res is not None
                        and res.fs < best.fs
                        and _passes_constraints(g, res)
                    ):
                        best = res
    return best


def _linspace(a: float, b: float, n: int) -> List[float]:
    if n <= 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def section_for_case(section: Section, case: LoadCase) -> Section:
    """ケース専用の水条件（水位急降下時など）を差し替えた断面を返す。"""
    changes = {}
    if case.phreatic is not None:
        changes["phreatic"] = case.phreatic
        changes["phreatic_estimated"] = False
    if case.external_water is not None:
        # 空リストは「外水なし」を意味する
        changes["external_water"] = case.external_water or None
    if not changes:
        return section
    return replace(section, **changes)


def run_all(section: Section, cases: List[LoadCase], grid: SearchGrid) -> List[CaseResult]:
    return [search_critical(section_for_case(section, c), c, grid) for c in cases]
