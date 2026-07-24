"""非円弧すべり面の自動探索（スペンサー法）。

臨界な非円弧すべり面を、次の手順で探索する:

1. 複数の初期形状（シード）を用意する
   - 円弧すべりの臨界円を折れ線化したもの（形状・入口/出口の良い初期値）
   - 円弧を浅く／深くスケールした変種
   - 明瞭に弱い層があれば、その層に沿う基盤すべり
2. 各シードから、すべり面を等間隔 x 上のノード群で表し、各ノードの
   標高 y と入口/出口 x を座標降下法（1 変数ずつ ± 摂動して改善を採用、
   収束したら刻みを半減）で最適化して最小 Fs を探す。
3. 最良のすべり面をスペンサー法（高精度）で再評価して返す。

多数の候補を評価するため、探索中は粗い評価（coarse=True）を用い、
最終形状のみ高精度で評価する。
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .geometry import surface_y
from .model import LoadCase, Point, Section, SearchGrid
from .search import search_critical
from .spencer import analyze_spencer
from .stability import CircleResult

_INF = float("inf")


def _ground_range(section: Section) -> Tuple[float, float]:
    xs = [p.x for p in section.surface]
    return min(xs), max(xs)


def _deepest_top(section: Section) -> float:
    """最下層上面の標高（探索の下限の目安）。"""
    return min(layer_top(section, ly) for ly in section.layers)


def layer_top(section: Section, layer) -> float:
    return min(p.y for p in layer.top)


def _floor(section: Section, grid: SearchGrid) -> float:
    """すべり面ノードの下限標高。"""
    if grid.y_lower_limit is not None:
        return grid.y_lower_limit
    gy = [p.y for p in section.surface]
    ymin = min(gy)
    # 最下層上面か、地表最深より少し下まで
    return min(_deepest_top(section) + 0.2, ymin - 1.0)


def _make_surface(entry_x: float, exit_x: float, ys: List[float], section: Section) -> List[Point]:
    """入口/出口 x と中間ノード標高 ys から折れ線すべり面を作る。"""
    k = len(ys)
    pts = [Point(entry_x, surface_y(section, entry_x))]
    for i in range(k):
        x = entry_x + (exit_x - entry_x) * (i + 1) / (k + 1)
        pts.append(Point(x, ys[i]))
    pts.append(Point(exit_x, surface_y(section, exit_x)))
    return pts


def _feasible(entry_x: float, exit_x: float, ys: List[float], section: Section,
              floor: float, min_span: float = 1.0, min_depth: float = 0.0) -> bool:
    """すべり面が地表面より下・下限より上にあり、x 昇順かを確認。

    min_span / min_depth により、浅いスライバへの退化を防ぐ（深部臨界面に限定）。
    """
    if exit_x - entry_x < max(1.0, min_span):
        return False
    gy_e = surface_y(section, entry_x)
    gy_x = surface_y(section, exit_x)
    if gy_e is None or gy_x is None:
        return False
    k = len(ys)
    max_depth = 0.0
    for i in range(k):
        x = entry_x + (exit_x - entry_x) * (i + 1) / (k + 1)
        gy = surface_y(section, x)
        if gy is None:
            return False
        if ys[i] > gy - 0.3:  # 地表面より十分下
            return False
        if ys[i] < floor - 1e-9:
            return False
        max_depth = max(max_depth, gy - ys[i])
    if max_depth < min_depth:  # 浅すぎるすべり面を排除
        return False
    # 折れ線が地表面より上に突き出ないか（区間中点でも確認）
    surf = _make_surface(entry_x, exit_x, ys, section)
    for j in range(len(surf) - 1):
        xm = 0.5 * (surf[j].x + surf[j + 1].x)
        gy = surface_y(section, xm)
        ym = 0.5 * (surf[j].y + surf[j + 1].y)
        if gy is not None and ym > gy - 0.05:
            return False
    # 凸性制約: 実際のすべり面は下から見て凸（基面傾角 α が入口→出口で
    # 単調増加）。ジグザグな非物理的形状を排除する。
    tol = math.radians(3.0)
    prev_a = None
    for j in range(len(surf) - 1):
        a = math.atan2(surf[j + 1].y - surf[j].y, surf[j + 1].x - surf[j].x)
        if prev_a is not None and a < prev_a - tol:
            return False
        prev_a = a
    return True


# 層間力傾角 θ の妥当域（これを超える解は非物理的な退化すべりとみなす）
_THETA_MAX = math.radians(45.0)


def _evaluate(entry_x, exit_x, ys, section, case, floor, n, coarse,
              min_span=1.0, min_depth=0.0) -> float:
    if not _feasible(entry_x, exit_x, ys, section, floor, min_span, min_depth):
        return _INF
    surf = _make_surface(entry_x, exit_x, ys, section)
    res = analyze_spencer(section, surf, case, n=n, coarse=coarse)
    if res is None or not math.isfinite(res.fs) or res.fs <= 0:
        return _INF
    # 層間力傾角が過大な解は非物理的（浅いスライバ等）として棄却
    if res.theta is not None and abs(res.theta) > _THETA_MAX:
        return _INF
    return res.fs


def _circle_seed(section: Section, cr: CircleResult, k: int) -> Optional[Tuple[float, float, List[float]]]:
    """円弧すべりの臨界円から入口/出口 x と中間ノード標高を作る。"""
    if not cr.slices:
        return None
    entry_x = cr.slices[0].x_mid - cr.slices[0].width / 2
    exit_x = cr.slices[-1].x_mid + cr.slices[-1].width / 2
    ys = []
    for i in range(k):
        x = entry_x + (exit_x - entry_x) * (i + 1) / (k + 1)
        dx = x - cr.xc
        if abs(dx) > cr.r:
            ys.append(cr.yc - cr.r)
        else:
            ys.append(cr.yc - math.sqrt(cr.r * cr.r - dx * dx))
    return entry_x, exit_x, ys


def _weak_layer_seed(section: Section, grid: SearchGrid, k: int) -> Optional[Tuple[float, float, List[float]]]:
    """最も弱い（c が小さい）中間層に沿う基盤すべりのシード。"""
    if len(section.layers) < 2:
        return None
    # 最上層以外で最も c の小さい層を弱層とみなす
    weak = min(section.layers[1:], key=lambda ly: ly.c + ly.phi)
    y_weak = layer_top(section, weak) - 0.5  # 層上面より少し下
    xmin, xmax = _ground_range(section)
    # 天端側 1/3 を入口、法尻側を出口の目安に
    entry_x = xmin + (xmax - xmin) * 0.35
    exit_x = xmin + (xmax - xmin) * 0.75
    ge = surface_y(section, entry_x)
    gx = surface_y(section, exit_x)
    if ge is None or gx is None:
        return None
    ys = []
    for i in range(k):
        t = (i + 1) / (k + 1)
        # 入口・出口付近は地盤内へ滑らかに、中間は弱層沿い
        ramp = min(t, 1 - t) * 3.0
        ys.append(min(y_weak, min(ge, gx) - 0.5 - ramp))
    return entry_x, exit_x, ys


def _optimize(seed, section, case, grid, floor, n, budget) -> Tuple[float, tuple]:
    """座標降下法で (entry_x, exit_x, ys) を最適化して (fs, params) を返す。

    端点はシード近傍に限定し、far な平地へ滑り面が逃げる退化を防ぐ。
    """
    entry_x, exit_x, ys = seed
    ys = list(ys)
    xmin, xmax = _ground_range(section)
    span = exit_x - entry_x
    margin = max(span * 0.35, 3.0)
    # 入口/出口の許容範囲（シード端点 ± margin かつ拘束条件内）
    ex_min = max(entry_x - margin, xmin)
    ex_max = min(exit_x + margin, xmax)
    if grid.x_entry_min is not None:
        ex_min = max(ex_min, grid.x_entry_min)
    if grid.x_exit_max is not None:
        ex_max = min(ex_max, grid.x_exit_max)
    # 退化防止: シード規模を基準に最小スパン・最小深さを課す
    seed_depth = 0.0
    for i in range(len(ys)):
        x = entry_x + (exit_x - entry_x) * (i + 1) / (len(ys) + 1)
        gy = surface_y(section, x)
        if gy is not None:
            seed_depth = max(seed_depth, gy - ys[i])
    min_span = span * 0.55
    min_depth = max(seed_depth * 0.5, 1.0)

    def ev(ex0, ex1, yy):
        return _evaluate(ex0, ex1, yy, section, case, floor, n, True, min_span, min_depth)

    best_fs = ev(entry_x, exit_x, ys)
    step = max((exit_x - entry_x) / (len(ys) + 1), 1.0) * 0.6
    for _ in range(budget):
        improved = False
        # 中間ノード標高
        for i in range(len(ys)):
            for d in (-step, step):
                trial = list(ys)
                trial[i] += d
                fs = ev(entry_x, exit_x, trial)
                if fs < best_fs - 1e-6:
                    ys, best_fs, improved = trial, fs, True
        # 入口 x
        for d in (-step, step):
            nx = min(max(entry_x + d, ex_min), exit_x - min_span)
            fs = ev(nx, exit_x, ys)
            if fs < best_fs - 1e-6:
                entry_x, best_fs, improved = nx, fs, True
        # 出口 x
        for d in (-step, step):
            nx = max(min(exit_x + d, ex_max), entry_x + min_span)
            fs = ev(entry_x, nx, ys)
            if fs < best_fs - 1e-6:
                exit_x, best_fs, improved = nx, fs, True
        if not improved:
            step *= 0.5
            if step < 0.15:
                break
    return best_fs, (entry_x, exit_x, ys)


def search_noncircular(
    section: Section, case: LoadCase, grid: SearchGrid
) -> Optional[CircleResult]:
    """臨界な非円弧すべり面をスペンサー法で自動探索する。"""
    k = max(2, grid.nc_nodes)
    floor = _floor(section, grid)
    n_search = 16  # 探索中のスライス数（粗）
    n_final = max(grid.n_slices, 30)

    seeds: List[Tuple[float, float, List[float]]] = []

    # 円弧臨界円シード（ビショップ法で探索）
    from dataclasses import replace as _replace

    circ_case = _replace(case, method="fellenius", slip_surface=None)
    circ = search_critical(section, circ_case, grid)
    if circ.critical is not None:
        cs = _circle_seed(section, circ.critical, k)
        if cs is not None:
            seeds.append(cs)
            # 深い変種（軟弱層まで到達する形状を促す）
            ex0, ex1, ys0 = cs
            base = surface_y(section, 0.5 * (ex0 + ex1)) or 0.0
            ysv = [max(base - (base - y) * 1.35, floor) for y in ys0]
            seeds.append((ex0, ex1, ysv))

    # 弱層シード
    ws = _weak_layer_seed(section, grid, k)
    if ws is not None:
        seeds.append(ws)

    if not seeds:
        return None

    best_fs = _INF
    best_surf: Optional[List[Point]] = None
    for seed in seeds:
        fs, params = _optimize(seed, section, case, grid, floor, n_search, budget=12)
        if fs < best_fs:
            best_fs = fs
            entry_x, exit_x, ys = params
            best_surf = _make_surface(entry_x, exit_x, ys, section)

    # ベースライン: 円弧臨界円の折れ線をそのままスペンサー法で評価
    # （探索が退化・失敗しても、円弧相当の妥当な結果を必ず返す）
    if seeds:
        e0, e1, ys0 = seeds[0]
        base_surf = _make_surface(e0, e1, ys0, section)
        base_res = analyze_spencer(section, base_surf, case, n=n_final, coarse=False)
    else:
        base_res = None

    # 探索の最良形状を高精度で再評価
    final = None
    if best_surf is not None and math.isfinite(best_fs):
        final = analyze_spencer(section, best_surf, case, n=n_final, coarse=False)

    # ベースラインと比較し、より小さい（かつ妥当な）Fs を採用
    candidates = [r for r in (final, base_res) if r is not None and math.isfinite(r.fs)]
    if not candidates:
        return None
    return min(candidates, key=lambda r: r.fs)
