"""幾何計算ユーティリティ。

折れ線の内挿、すべり円と地表面の交点探索、鉛直スライスに沿った
土層厚の積分などを提供する。
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .model import GAMMA_W, PhreaticLine, Point, Section, SoilLayer


def interp_polyline(points: List[Point], x: float) -> Optional[float]:
    """折れ線上の x における y を線形内挿で返す。

    x が折れ線の範囲外の場合は None を返す（外挿しない）。
    """
    if x < points[0].x or x > points[-1].x:
        return None
    for a, b in zip(points, points[1:]):
        if a.x <= x <= b.x:
            if b.x == a.x:
                return max(a.y, b.y)
            t = (x - a.x) / (b.x - a.x)
            return a.y + t * (b.y - a.y)
    return points[-1].y


def surface_y(section: Section, x: float) -> Optional[float]:
    """地表面標高。"""
    return interp_polyline(section.surface, x)


def phreatic_y(phreatic: Optional[PhreaticLine], x: float) -> Optional[float]:
    """浸潤線標高。範囲外や未設定なら None。"""
    if phreatic is None:
        return None
    return interp_polyline(phreatic.points, x)


def layer_top_y(layer: SoilLayer, x: float) -> Optional[float]:
    return interp_polyline(layer.top, x)


def external_water_y(section: Section, x: float) -> Optional[float]:
    """外水位（河川水位）標高。範囲外や未設定なら None。"""
    if section.external_water is None:
        return None
    return interp_polyline(section.external_water, x)


def water_overburden(section: Section, x: float) -> float:
    """地表面より上にある外水の水柱応力 γw·(y_水面 − y_地表) (kN/m2)。

    外水位が地表面より低い位置では 0。
    """
    yw = external_water_y(section, x)
    if yw is None:
        return 0.0
    ys = surface_y(section, x)
    if ys is None:
        return 0.0
    depth = yw - ys
    return GAMMA_W * depth if depth > 0 else 0.0


def arc_lower_y(xc: float, yc: float, r: float, x: float) -> Optional[float]:
    """すべり円（下側の弧）の標高。円の範囲外なら None。"""
    dx = x - xc
    if abs(dx) > r:
        return None
    return yc - math.sqrt(r * r - dx * dx)


def find_arc_surface_intersections(
    section: Section, xc: float, yc: float, r: float, samples: int = 400
) -> Optional[Tuple[float, float]]:
    """すべり円の下弧が地表面と交わる左右2点の x を返す。

    見つからない、または有効なすべり土塊を形成しない場合は None。
    """
    x_left_lim = xc - r
    x_right_lim = xc + r

    # 地表面の定義範囲と円の範囲の重なりを走査対象にする
    surf = section.surface
    x0 = max(x_left_lim, surf[0].x)
    x1 = min(x_right_lim, surf[-1].x)
    if x1 <= x0:
        return None

    def gap(x: float) -> Optional[float]:
        """地表面 - すべり弧。正なら弧が地表面より下（土塊内）。"""
        ys = surface_y(section, x)
        ya = arc_lower_y(xc, yc, r, x)
        if ys is None or ya is None:
            return None
        return ys - ya

    xs = [x0 + (x1 - x0) * i / samples for i in range(samples + 1)]
    signs: List[Optional[float]] = [gap(x) for x in xs]

    # 符号が負→正、正→負 に変わる境界を探す（土塊は gap>0 の区間）
    crossings: List[float] = []
    for i in range(samples):
        g0, g1 = signs[i], signs[i + 1]
        if g0 is None or g1 is None:
            continue
        if g0 == 0.0:
            crossings.append(xs[i])
        if (g0 < 0 < g1) or (g0 > 0 > g1):
            # 二分法で精密化
            lo, hi = xs[i], xs[i + 1]
            glo = g0
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                gm = gap(mid)
                if gm is None:
                    break
                if (glo < 0 and gm < 0) or (glo > 0 and gm > 0):
                    lo, glo = mid, gm
                else:
                    hi = mid
            crossings.append(0.5 * (lo + hi))

    if len(crossings) < 2:
        return None

    xl, xr = crossings[0], crossings[-1]
    if xr - xl < 1e-6:
        return None

    # 区間中央で土塊が存在する（gap>0）ことを確認
    gm = gap(0.5 * (xl + xr))
    if gm is None or gm <= 0:
        return None
    return xl, xr


def column_weight(
    section: Section, x: float, y_bottom: float, y_top: float
) -> float:
    """鉛直スライス（幅1m相当の単位面積重量ではなく単位幅あたりの重量密度）。

    x における [y_bottom, y_top] 区間の土の単位幅重量 (kN/m 当たりは
    呼び出し側で幅を掛ける)。ここでは単位幅・高さ方向の積分値
    Σ γ * 層厚 (kN/m2 の応力に相当) を返す。

    浸潤線より下は飽和単位体積重量、上は湿潤単位体積重量を用いる。
    """
    if y_top <= y_bottom:
        return 0.0

    yw = phreatic_y(section.phreatic, x)

    # 層境界を上から下へ組み立てる
    tops: List[Tuple[float, SoilLayer]] = []
    for layer in section.layers:
        yt = layer_top_y(layer, x)
        if yt is not None:
            tops.append((yt, layer))
    if not tops:
        return 0.0

    total = 0.0
    n = len(tops)
    for i, (yt, layer) in enumerate(tops):
        # 層の下面 = 次層の上面、最下層は -inf
        yb = tops[i + 1][0] if i + 1 < n else -math.inf
        seg_top = min(y_top, yt)
        seg_bot = max(y_bottom, yb)
        if seg_top <= seg_bot:
            continue
        if yw is None:
            total += layer.gamma * (seg_top - seg_bot)
        else:
            # 浸潤線で上下に分割
            wet_top = seg_top
            wet_bot = max(seg_bot, yw)
            if wet_top > wet_bot:
                total += layer.gamma * (wet_top - wet_bot)
            sat_top = min(seg_top, yw)
            sat_bot = seg_bot
            if sat_top > sat_bot:
                total += layer.gamma_sat * (sat_top - sat_bot)
    return total


def soil_at(section: Section, x: float, y: float) -> Optional[SoilLayer]:
    """標高 y にある土層を返す。"""
    tops: List[Tuple[float, SoilLayer]] = []
    for layer in section.layers:
        yt = layer_top_y(layer, x)
        if yt is not None:
            tops.append((yt, layer))
    if not tops:
        return None
    n = len(tops)
    for i, (yt, layer) in enumerate(tops):
        yb = tops[i + 1][0] if i + 1 < n else -math.inf
        if yb <= y <= yt:
            return layer
    # 範囲外なら最下層（深部）または最上層
    if y > tops[0][0]:
        return tops[0][1]
    return tops[-1][1]


def improvement_at(section: Section, x: float, y: float):
    """(x, y) を含む地盤改良範囲を返す（なければ None）。"""
    for z in section.improvements:
        if z.x_start <= x <= z.x_end and z.y_bottom <= y <= z.y_top:
            return z
    return None


def pore_pressure(section: Section, x: float, y_slip: float) -> float:
    """すべり面上の間隙水圧 u (kN/m2)。

    浸潤線と外水位の両方が定義されていれば、高い方の水頭を採用する。
    """
    heads = []
    yw = phreatic_y(section.phreatic, x)
    if yw is not None:
        heads.append(yw)
    ye = external_water_y(section, x)
    if ye is not None:
        heads.append(ye)
    if not heads:
        return 0.0
    head = max(heads) - y_slip
    return GAMMA_W * head if head > 0 else 0.0
