"""円弧すべり安定計算。

修正フェレニウス法（震度法対応）および簡易ビショップ法により
1つのすべり円に対する安全率を計算する。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from .geometry import (
    arc_lower_y,
    column_weight,
    find_arc_surface_intersections,
    pore_pressure,
    soil_at,
    surface_y,
    water_overburden,
)
from .model import GAMMA_W, LoadCase, Section


@dataclass
class Slice:
    """1スライスの計算諸元。"""

    x_mid: float
    width: float
    height: float
    weight: float          # W (kN/m)
    alpha: float           # base 傾角 (rad)
    base_len: float        # l (m)
    u: float               # 間隙水圧 (kN/m2)
    c: float               # 粘着力 (kN/m2)
    phi: float             # 内部摩擦角 (rad)


@dataclass
class CircleResult:
    """1つのすべり円の照査結果。"""

    xc: float
    yc: float
    r: float
    fs: float
    slices: List[Slice] = field(default_factory=list)
    valid: bool = True
    # テンションクラックですべり面を打ち切った位置（描画用）
    crack_x: Optional[float] = None
    # クラック水圧などによる追加起動力（モーメント換算, kN/m）
    extra_driving: float = 0.0

    def __lt__(self, other: "CircleResult") -> bool:
        return self.fs < other.fs


@dataclass
class SlipSurface:
    """スライス分割済みのすべり面。"""

    slices: List[Slice]
    crack_x: Optional[float] = None
    extra_driving: float = 0.0


def _apply_tension_crack(
    section: Section, xc: float, yc: float, r: float, xl: float, xr: float
) -> Optional[tuple]:
    """テンションクラックですべり面上端を打ち切る。

    上端側（地表面が高い側）から、被り厚（地表面 − すべり弧）が
    亀裂深さ zc に達する位置 x_crack を探し、すべり面をそこで
    打ち切る。亀裂内水圧 Pw = ½·γw·zw² の起動モーメントを
    半径 R で除して等価起動力に換算する。

    Returns:
        (xl, xr, crack_x, extra_driving) または None（有効なすべり面が残らない場合）。
    """
    crack = section.tension_crack
    if crack is None:
        return xl, xr, None, 0.0

    def cover(x: float) -> Optional[float]:
        ys = surface_y(section, x)
        ya = arc_lower_y(xc, yc, r, x)
        if ys is None or ya is None:
            return None
        return ys - ya

    ys_l = surface_y(section, xl)
    ys_r = surface_y(section, xr)
    if ys_l is None or ys_r is None:
        return xl, xr, None, 0.0
    # 上端 = 地表面が高い側（天端側）
    upper_is_left = ys_l >= ys_r

    # 上端から内側へ走査し、被り厚が zc に達する位置を二分法で求める
    n_scan = 100
    zc = crack.depth
    x_from, x_to = (xl, xr) if upper_is_left else (xr, xl)
    x_crack = None
    prev_x = x_from
    for i in range(1, n_scan + 1):
        x = x_from + (x_to - x_from) * i / n_scan
        cv = cover(x)
        if cv is None:
            prev_x = x
            continue
        if cv >= zc:
            lo, hi = prev_x, x
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                cm = cover(mid)
                if cm is None or cm < zc:
                    lo = mid
                else:
                    hi = mid
            x_crack = 0.5 * (lo + hi)
            break
        prev_x = x
    if x_crack is None:
        # 被り厚が亀裂深さに達しない → 亀裂がすべり土塊を貫通
        return None

    ya_crack = arc_lower_y(xc, yc, r, x_crack)
    if ya_crack is None:
        return None

    # クラック内水圧（水平力）→ 起動モーメント → 等価起動力
    zw = crack.water_depth
    extra = 0.0
    if zw > 0:
        pw = 0.5 * GAMMA_W * zw * zw
        y_thrust = ya_crack + zw / 3.0
        arm = yc - y_thrust
        if arm > 0:
            extra = pw * arm / r

    if upper_is_left:
        return x_crack, xr, x_crack, extra
    return xl, x_crack, x_crack, extra


def build_slices(
    section: Section, xc: float, yc: float, r: float, n: int
) -> Optional[SlipSurface]:
    """すべり円に対して鉛直スライスを生成する。"""
    inter = find_arc_surface_intersections(section, xc, yc, r)
    if inter is None:
        return None
    xl, xr = inter

    cracked = _apply_tension_crack(section, xc, yc, r, xl, xr)
    if cracked is None:
        return None
    xl, xr, crack_x, extra_driving = cracked

    width = (xr - xl) / n
    if width <= 0:
        return None

    slices: List[Slice] = []
    for i in range(n):
        xm = xl + width * (i + 0.5)
        ys = surface_y(section, xm)
        ya = arc_lower_y(xc, yc, r, xm)
        if ys is None or ya is None:
            continue
        h = ys - ya
        if h <= 0:
            continue

        w = column_weight(section, xm, ya, ys) * width  # kN/m

        # 上載荷重（スライスとの重なり幅 × q）
        x0, x1 = xm - width / 2, xm + width / 2
        for sc in section.surcharges:
            ov = min(x1, sc.x_end) - max(x0, sc.x_start)
            if ov > 0:
                w += sc.q * ov

        # 地表面より上の外水（水柱重量）
        w += water_overburden(section, xm) * width

        dx = xm - xc
        # sin(alpha) = 水平距離 / R。中心より右側(下流)を正とする
        sin_a = max(-0.999, min(0.999, dx / r))
        alpha = math.asin(sin_a)
        cos_a = math.cos(alpha)
        base_len = width / cos_a if cos_a > 1e-9 else width

        u = pore_pressure(section, xm, ya)

        layer = soil_at(section, xm, ya)
        c = layer.c if layer else 0.0
        phi = math.radians(layer.phi) if layer else 0.0

        slices.append(
            Slice(
                x_mid=xm,
                width=width,
                height=h,
                weight=w,
                alpha=alpha,
                base_len=base_len,
                u=u,
                c=c,
                phi=phi,
            )
        )

    if not slices:
        return None

    # 重力による起動モーメント Σ W sinα が負なら、すべりは −x 方向
    # （α の符号規約と逆向き）。α を反転した鏡像として評価することで
    # 左右どちらの向きのすべりも扱う（kh・クラック水圧はすべり方向に作用）。
    if sum(s.weight * math.sin(s.alpha) for s in slices) < 0:
        for s in slices:
            s.alpha = -s.alpha

    return SlipSurface(slices=slices, crack_x=crack_x, extra_driving=extra_driving)


def fellenius_fs(
    slices: List[Slice], kh: float, extra_driving: float = 0.0
) -> Optional[float]:
    """修正フェレニウス法（震度法）による安全率。

    地震時慣性力 kh*W をスライス基面の接線・法線方向に分解する:
        接線(すべり)成分 : W sinα + kh W cosα
        法線成分        : N = W cosα - kh W sinα

        Fs = Σ[ c·l + (N - u·l) tanφ ] / ( Σ[ W sinα + kh W cosα ] + D_extra )

    D_extra はクラック水圧等の追加起動力（モーメント/R 換算）。
    """
    numer = 0.0
    denom = extra_driving
    for s in slices:
        sin_a = math.sin(s.alpha)
        cos_a = math.cos(s.alpha)
        n_eff = s.weight * cos_a - kh * s.weight * sin_a - s.u * s.base_len
        resist = s.c * s.base_len + max(n_eff, 0.0) * math.tan(s.phi)
        drive = s.weight * sin_a + kh * s.weight * cos_a
        numer += resist
        denom += drive
    if denom <= 1e-9:
        return None
    return numer / denom


def bishop_fs(
    slices: List[Slice],
    kh: float,
    tol: float = 1e-4,
    max_iter: int = 100,
    extra_driving: float = 0.0,
) -> Optional[float]:
    """簡易ビショップ法（震度法）による安全率（反復計算）。

        Fs = Σ[ (c·b + (W - u·b) tanφ) / mα ] / ( Σ[ W sinα + kh W cosα ] + D_extra )
        mα = cosα ( 1 + tanα tanφ / Fs )
    """
    denom = extra_driving
    for s in slices:
        denom += s.weight * math.sin(s.alpha) + kh * s.weight * math.cos(s.alpha)
    if denom <= 1e-9:
        return None

    fs = 1.0
    for _ in range(max_iter):
        numer = 0.0
        for s in slices:
            tan_phi = math.tan(s.phi)
            m_alpha = math.cos(s.alpha) * (
                1.0 + math.tan(s.alpha) * tan_phi / fs
            )
            if abs(m_alpha) < 1e-6:
                return None
            base = s.c * s.width + (s.weight - s.u * s.width) * tan_phi
            numer += base / m_alpha
        new_fs = numer / denom
        if new_fs <= 0:
            return None
        if abs(new_fs - fs) < tol:
            return new_fs
        fs = new_fs
    return fs


def analyze_circle(
    section: Section, case: LoadCase, xc: float, yc: float, r: float, n: int
) -> Optional[CircleResult]:
    """1つのすべり円について安全率を計算する。"""
    surf = build_slices(section, xc, yc, r, n)
    if surf is None:
        return None
    if case.method == "bishop":
        fs = bishop_fs(surf.slices, case.kh, extra_driving=surf.extra_driving)
    else:
        fs = fellenius_fs(surf.slices, case.kh, extra_driving=surf.extra_driving)
    if fs is None or not math.isfinite(fs):
        return None
    return CircleResult(
        xc=xc,
        yc=yc,
        r=r,
        fs=fs,
        slices=surf.slices,
        crack_x=surf.crack_x,
        extra_driving=surf.extra_driving,
    )
