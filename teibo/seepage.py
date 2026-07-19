"""浸潤線の簡易自動推定。

カサグランデの基本放物線（basic parabola）による定常浸透の簡易解で
堤体内の浸潤線を推定する。厳密な浸透流解析（FEM 等）の代替ではなく、
浸潤線を手入力する手間を省くための実用的な近似である。

手法の概要（川表=左の場合）:
  1. 川表法面と外水位 hw の交点 A（入水点）を求める。
  2. 川表法面の水没部の水平投影長 Δ をとり、A から水側へ 0.3Δ の
     点 A0 を基本放物線の通過点とする（カサグランデの修正）。
  3. 川裏法尻 F を焦点とし、A0 を通る基本放物線
        y² = y0² + 2·y0·ξ,  y0 = √(d² + h²) − d
     （ξ は F から水側への水平距離、d・h は F から見た A0 の位置)
     で浸潤線を生成する。
  4. 浸潤線は地表面と外水位を超えないようにクランプし、川裏側は
     裏水位 tail_level に接続する。
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .model import PhreaticLine, Point, Section
from .geometry import interp_polyline


def _find_crossing(
    pts: List[Point], level: float, x_from: float, x_to: float
) -> Optional[float]:
    """折れ線が標高 level と交わる x を [x_from, x_to] の範囲で探す。

    範囲内で最初（x の小さい側）の交点を返す。
    """
    lo, hi = min(x_from, x_to), max(x_from, x_to)
    for a, b in zip(pts, pts[1:]):
        if b.x < lo or a.x > hi:
            continue
        ya, yb = a.y - level, b.y - level
        if ya == 0.0 and lo <= a.x <= hi:
            return a.x
        if ya * yb < 0:
            t = ya / (ya - yb)
            x = a.x + t * (b.x - a.x)
            if lo <= x <= hi:
                return x
    return None


def _mirror(pts: List[Point]) -> List[Point]:
    """x 反転（左右対称）した折れ線を返す。"""
    return [Point(-p.x, p.y) for p in reversed(pts)]


def _estimate_left(
    surface: List[Point],
    water_level: float,
    tail_level: Optional[float],
    n_points: int,
) -> List[Point]:
    """川表=左として浸潤線折れ線を生成する（内部実装）。"""
    x_left = surface[0].x
    x_right = surface[-1].x

    # 川裏側の基準地盤高（右端の地表面標高）
    y_base = surface[-1].y
    if tail_level is None:
        tail_level = y_base
    h = water_level - y_base
    if h <= 0:
        raise ValueError(
            f"浸潤線推定: 外水位 ({water_level}) が川裏地盤高 ({y_base}) 以下です"
        )

    # 入水点 A: 左側から見て地表面が外水位と交わる最初の点
    x_a = _find_crossing(surface, water_level, x_left, x_right)
    if x_a is None:
        raise ValueError(
            f"浸潤線推定: 外水位 ({water_level}) と川表法面の交点が見つかりません"
            "（水位が天端より高い、または断面範囲外の可能性）"
        )

    # 川表法尻: A より左にあり、地表面標高が川裏地盤高以下となる
    # 最も A に近い点（法面の水没部の始まり）。なければ左端。
    x_toe_w = x_left
    for p in surface:
        if p.x >= x_a:
            break
        if p.y <= y_base + 1e-6:
            x_toe_w = p.x
    delta = max(x_a - x_toe_w, 0.0)

    # カサグランデの修正: A から水側へ 0.3Δ の点 A0 を通過点とする
    x_a0 = x_a - 0.3 * delta

    # 川裏法尻 F（焦点）: A より右で地表面が川裏地盤高まで下がる点
    x_f = _find_crossing(surface, y_base + 1e-9, x_a, x_right)
    if x_f is None or x_f <= x_a:
        x_f = x_right
    d = x_f - x_a0
    if d <= 0:
        raise ValueError("浸潤線推定: 断面形状から放物線を定義できません")

    # 基本放物線 y² = y0² + 2 y0 ξ（ξ は F から水側への距離）
    y0 = math.sqrt(d * d + h * h) - d

    def parabola_y(x: float) -> float:
        xi = x_f - x
        if xi <= 0:
            return y_base + y0
        return y_base + math.sqrt(y0 * y0 + 2.0 * y0 * xi)

    pts: List[Point] = []

    def add(x: float, y: float, clamp_surface: bool = True) -> None:
        # 堤体内では地表面を、全域で外水位を超えないようにクランプ
        if clamp_surface:
            ys = interp_polyline(surface, x)
            if ys is not None:
                y = min(y, ys)
        y = min(y, water_level)
        y = max(y, min(tail_level, y_base))
        if pts and x <= pts[-1].x:
            return
        pts.append(Point(x, y))

    # 左端〜入水点: 外水位で水平（水域なので地表面ではクランプしない）
    add(x_left, water_level, clamp_surface=False)
    add(x_a, water_level, clamp_surface=False)

    # 入水点〜川裏法尻: 基本放物線
    for i in range(1, n_points + 1):
        x = x_a + (x_f - x_a) * i / n_points
        add(x, parabola_y(x))

    # 川裏法尻〜右端: 裏水位へ接続（裏水位が地表面より高い場合も水面を保持）
    add(x_right, tail_level, clamp_surface=False)

    if len(pts) < 2:
        raise ValueError("浸潤線推定: 有効な浸潤線を生成できませんでした")
    return pts


def estimate_phreatic(
    section: Section,
    water_level: float,
    waterside: str = "left",
    tail_level: Optional[float] = None,
    n_points: int = 20,
) -> PhreaticLine:
    """カサグランデの基本放物線により浸潤線を推定する。

    Args:
        section:     堤防断面。
        water_level: 外水位（川表側の水位標高, m）。
        waterside:   川表（水がある側）。"left" または "right"。
        tail_level:  川裏側の水位標高。省略時は川裏地盤高。
        n_points:    放物線部の分割数。

    Returns:
        推定した浸潤線。
    """
    side = waterside.lower()
    if side not in ("left", "right"):
        raise ValueError('浸潤線推定: waterside は "left" か "right" を指定してください')

    surface = section.surface
    if side == "left":
        pts = _estimate_left(surface, water_level, tail_level, n_points)
    else:
        mirrored = _estimate_left(_mirror(surface), water_level, tail_level, n_points)
        pts = _mirror(mirrored)
    return PhreaticLine(points=pts)
