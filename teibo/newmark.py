"""ニューマーク法による滑動変位量の算定。

地震時の最小安全率が 1 を下回る場合でも、すべり土塊を剛体ブロックと
みなして「どれだけ滑動するか」を評価する。

1. 降伏震度 ky: 臨界すべり円について Fs(kh) = 1 となる水平震度を
   二分法で求める。
2. 滑動変位量 D:
   - 加速度波形（時刻歴）が与えられた場合は、降伏加速度
     ay = ky·g を超える加速度を二重積分して累積変位を求める
     （片側すべりの剛体ブロック法）。
   - 波形がない場合は Ambraseys & Menu (1988) の経験式（平均値）
       log10 D[cm] = 0.90 + log10[ (1 − ky/kmax)^2.53 · (ky/kmax)^−1.09 ]
     により推定する（kmax は設計水平震度）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from .model import LoadCase, Point
from .search import CaseResult
from .stability import Slice, bishop_fs, fellenius_fs

GRAVITY = 9.81  # m/s2


@dataclass
class NewmarkResult:
    """1ケースのニューマーク法算定結果。"""

    case: LoadCase
    ky: Optional[float]            # 降伏震度（None: 算定不能）
    kmax: float                    # 設計水平震度（最大震度）
    displacement: Optional[float]  # 滑動変位量 D (m)
    allowable: float               # 許容変位量 Da (m)
    used_time_history: bool = False

    @property
    def ok(self) -> Optional[bool]:
        if self.displacement is None:
            return None
        return self.displacement <= self.allowable

    @property
    def judgement(self) -> str:
        if self.ok is None:
            return "算定不能"
        return "OK" if self.ok else "NG"


def yield_kh(
    slices: List[Slice],
    extra_driving: float = 0.0,
    method: str = "fellenius",
    kh_max: float = 2.0,
    tol: float = 1e-4,
) -> Optional[float]:
    """Fs(kh) = 1 となる降伏震度 ky を二分法で求める。

    Fs(0) ≤ 1 の場合は 0 を返す（常時から不安定）。
    kh_max でも Fs > 1 の場合は kh_max を返す。
    """
    fs_func = bishop_fs if method == "bishop" else fellenius_fs

    def fs(kh: float) -> Optional[float]:
        return fs_func(slices, kh, extra_driving=extra_driving)

    f0 = fs(0.0)
    if f0 is None:
        return None
    if f0 <= 1.0:
        return 0.0
    fh = fs(kh_max)
    if fh is None:
        return None
    if fh > 1.0:
        return kh_max

    lo, hi = 0.0, kh_max
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        fm = fs(mid)
        if fm is None:
            return None
        if fm > 1.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def displacement_empirical(ky: float, kmax: float) -> Optional[float]:
    """Ambraseys & Menu (1988) の経験式による滑動変位量 (m)。

    ky ≥ kmax なら 0（滑動しない）。ky = 0（常時から不安定）は
    経験式の適用範囲外のため None。
    """
    if kmax <= 0.0:
        return 0.0
    if ky >= kmax:
        return 0.0
    if ky <= 0.0:
        return None
    ratio = ky / kmax
    log_d = 0.90 + math.log10((1.0 - ratio) ** 2.53 * ratio ** -1.09)
    return (10.0 ** log_d) / 100.0  # cm → m


def displacement_time_history(
    accel: List[Point], ky: float
) -> Optional[float]:
    """加速度波形の二重積分による滑動変位量 (m)。

    Args:
        accel: [(時刻 s, 加速度 gal)] の波形（Point の x=t, y=gal）。
        ky:    降伏震度。降伏加速度 ay = ky·g を超える区間で滑動する。

    片側すべりの剛体ブロック法（加速度は絶対値で評価）。
    """
    if ky < 0.0 or len(accel) < 2:
        return None
    ay = ky * GRAVITY  # m/s2
    v = 0.0
    d = 0.0
    for p0, p1 in zip(accel, accel[1:]):
        dt = p1.x - p0.x
        if dt <= 0.0:
            continue
        a = 0.5 * (abs(p0.y) + abs(p1.y)) / 100.0  # gal → m/s2
        if v > 0.0 or a > ay:
            v += (a - ay) * dt
            if v < 0.0:
                v = 0.0
            else:
                d += v * dt
    return d


def run_newmark(
    results: List[CaseResult],
    accel_series: Optional[List[Point]] = None,
) -> List[NewmarkResult]:
    """`newmark: true` のケースについて ky と滑動変位量を算定する。"""
    out: List[NewmarkResult] = []
    for r in results:
        c = r.case
        if not c.newmark:
            continue
        if r.critical is None:
            out.append(
                NewmarkResult(
                    case=c,
                    ky=None,
                    kmax=c.kh,
                    displacement=None,
                    allowable=c.allowable_displacement,
                )
            )
            continue
        ky = yield_kh(
            r.critical.slices, r.critical.extra_driving, method=c.method
        )
        used_th = False
        if ky is None:
            disp = None
        elif accel_series:
            disp = displacement_time_history(accel_series, ky)
            used_th = True
        else:
            disp = displacement_empirical(ky, c.kh)
        out.append(
            NewmarkResult(
                case=c,
                ky=ky,
                kmax=c.kh,
                displacement=disp,
                allowable=c.allowable_displacement,
                used_time_history=used_th,
            )
        )
    return out
