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
)
from .model import LoadCase, Section


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

    def __lt__(self, other: "CircleResult") -> bool:
        return self.fs < other.fs


def build_slices(
    section: Section, xc: float, yc: float, r: float, n: int
) -> Optional[List[Slice]]:
    """すべり円に対して鉛直スライスを生成する。"""
    inter = find_arc_surface_intersections(section, xc, yc, r)
    if inter is None:
        return None
    xl, xr = inter
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
    return slices


def fellenius_fs(slices: List[Slice], kh: float) -> Optional[float]:
    """修正フェレニウス法（震度法）による安全率。

    地震時慣性力 kh*W をスライス基面の接線・法線方向に分解する:
        接線(すべり)成分 : W sinα + kh W cosα
        法線成分        : N = W cosα - kh W sinα

        Fs = Σ[ c·l + (N - u·l) tanφ ] / Σ[ W sinα + kh W cosα ]
    """
    numer = 0.0
    denom = 0.0
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
    slices: List[Slice], kh: float, tol: float = 1e-4, max_iter: int = 100
) -> Optional[float]:
    """簡易ビショップ法（震度法）による安全率（反復計算）。

        Fs = Σ[ (c·b + (W - u·b) tanφ) / mα ] / Σ[ W sinα + kh W cosα ]
        mα = cosα ( 1 + tanα tanφ / Fs )
    """
    denom = 0.0
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
    slices = build_slices(section, xc, yc, r, n)
    if slices is None:
        return None
    if case.method == "bishop":
        fs = bishop_fs(slices, case.kh)
    else:
        fs = fellenius_fs(slices, case.kh)
    if fs is None or not math.isfinite(fs):
        return None
    return CircleResult(xc=xc, yc=yc, r=r, fs=fs, slices=slices)
