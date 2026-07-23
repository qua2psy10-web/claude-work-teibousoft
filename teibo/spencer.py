"""スペンサー法（非円弧すべり面）による安定計算。

任意形状（折れ線）のすべり面に対し、層間力の傾角 θ を全スライスで
一定と仮定して、力の平衡とモーメントの平衡を同時に満たす安全率 Fs を
求める（Spencer, 1967）。修正フェレニウス法・簡易ビショップ法が満たす
のは平衡条件の一部のみであるのに対し、スペンサー法は力・モーメントの
両平衡を満たすため、非円弧すべり面に対しても厳密性が高い。

各スライスの層間合力 Q_i（傾角 θ 一定）:

    Q_i = { (1/F)[ c_i·l_i + (W_i cosα_i − k_h W_i sinα_i − u_i·l_i) tanφ_i ]
            − (W_i sinα_i + k_h W_i cosα_i) }
          / { cos(α_i − θ) + sin(α_i − θ) tanφ_i / F }

平衡条件:
    力     : Σ Q_i = 0                                   → F_f(θ)
    モーメント: Σ Q_i·(x_i sinθ − y_i cosθ) = 0（基面中点まわり） → F_m(θ)

F_f(θ) = F_m(θ) となる θ を探索し、そのときの Fs を安全率とする。
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .geometry import (
    column_weight,
    improvement_at,
    pore_pressure,
    soil_at,
    surface_y,
    water_overburden,
)
from .model import LoadCase, Point, Section
from .stability import CircleResult, Slice


def _surface_at(surface: List[Point], x: float) -> Optional[Tuple[float, float]]:
    """折れ線すべり面上の (標高 y, 基面傾角 α) を返す。

    α は水平からの基面傾角 (rad)。左→右で下り（y 減少）なら負、
    上り（y 増加）なら正。円弧法の sinα = (x−xc)/R と符号整合する。
    """
    for i in range(len(surface) - 1):
        ax, ay = surface[i].x, surface[i].y
        bx, by = surface[i + 1].x, surface[i + 1].y
        if ax <= x <= bx and bx > ax:
            t = (x - ax) / (bx - ax)
            y = ay + t * (by - ay)
            alpha = math.atan2(by - ay, bx - ax)
            return y, alpha
    return None


def _build_poly_slices(
    section: Section,
    surface: List[Point],
    n: int,
    case: Optional[LoadCase] = None,
) -> Optional[List[Slice]]:
    """折れ線すべり面の下にできるすべり土塊を鉛直スライスに分割する。

    スライス境界は折れ線の頂点に合わせ、各区間を幅に応じて細分して
    合計おおよそ n 枚にする（1 スライス内で α は一定）。
    """
    kh = case.kh if case is not None else 0.0
    x_left, x_right = surface[0].x, surface[-1].x
    total_w = x_right - x_left
    if total_w <= 0:
        return None

    slices: List[Slice] = []
    for i in range(len(surface) - 1):
        ax, ay = surface[i].x, surface[i].y
        bx, by = surface[i + 1].x, surface[i + 1].y
        seg_w = bx - ax
        if seg_w <= 1e-9:
            continue
        # この区間に割り当てるスライス数（幅に比例、最低1）
        m = max(1, round(n * seg_w / total_w))
        sw = seg_w / m
        for k in range(m):
            xm = ax + sw * (k + 0.5)
            sa = _surface_at(surface, xm)
            ys = surface_y(section, xm)
            if sa is None or ys is None:
                continue
            yb, alpha = sa
            h = ys - yb
            if h <= 1e-9:
                continue

            w = column_weight(section, xm, yb, ys) * sw

            x0, x1 = xm - sw / 2, xm + sw / 2
            for sc in section.surcharges:
                ov = min(x1, sc.x_end) - max(x0, sc.x_start)
                if ov > 0:
                    w += sc.q * ov
            w += water_overburden(section, xm) * sw

            cos_a = math.cos(alpha)
            base_len = sw / cos_a if abs(cos_a) > 1e-9 else sw

            u = pore_pressure(section, xm, yb)

            layer = soil_at(section, xm, yb)
            zone = improvement_at(section, xm, yb)
            if zone is not None:
                c = zone.c
                phi = math.radians(zone.phi)
            else:
                c = layer.c if layer else 0.0
                phi = math.radians(layer.phi) if layer else 0.0

            fl = None
            if (
                zone is None
                and case is not None
                and case.consider_liquefaction
                and layer is not None
                and layer.liquefaction is not None
                and u > 0.0
            ):
                from .liquefaction import fl_value, ru_from_fl

                sigma_v = column_weight(section, xm, yb, ys) + water_overburden(
                    section, xm
                )
                sigma_v_eff = max(sigma_v - u, 1e-6)
                fl = fl_value(
                    layer.liquefaction.n_value,
                    layer.liquefaction.fines_content,
                    sigma_v,
                    sigma_v_eff,
                    kh,
                    depth=h,
                )
                ru = ru_from_fl(fl)
                if ru > 0.0:
                    u = min(u + ru * sigma_v_eff, sigma_v)

            slices.append(
                Slice(
                    x_mid=xm,
                    width=sw,
                    height=h,
                    weight=w,
                    alpha=alpha,
                    base_len=base_len,
                    u=u,
                    c=c,
                    phi=phi,
                    fl=fl,
                    y_base=yb,
                )
            )

    if len(slices) < 2:
        return None

    # 起動方向を +x に正規化（Σ W sinα < 0 なら鏡像として扱う）
    if sum(s.weight * math.sin(s.alpha) for s in slices) < 0:
        for s in slices:
            s.alpha = -s.alpha
            s.x_mid = -s.x_mid

    return slices


def _q_forces(
    slices: List[Slice], fs: float, theta: float, kh: float
) -> Optional[List[float]]:
    """与えた (Fs, θ) に対する各スライスの層間合力 Q_i（スペンサー標準形）。

        Q = [ (1/F)(c·l + (W cosα − kh·W sinα − u·l)tanφ) − (W sinα + kh·W cosα) ]
            / [ cos(α−θ) + (tanφ/F) sin(α−θ) ]

    分子は「抵抗力 − 起動力」、分母は層間力を傾角 θ 一定と仮定した
    ときの係数。円弧すべりでは簡易ビショップ法とほぼ一致する。
    """
    out: List[float] = []
    for s in slices:
        a = s.alpha
        t = math.tan(s.phi)
        w = s.weight
        n_eff = w * math.cos(a) - kh * w * math.sin(a) - s.u * s.base_len
        resist = (s.c * s.base_len + n_eff * t) / fs
        drive = w * math.sin(a) + kh * w * math.cos(a)
        den = math.cos(a - theta) + (t / fs) * math.sin(a - theta)
        if den <= 1e-6:
            return None
        out.append((resist - drive) / den)
    return out


def _force_residual(slices, fs, theta, kh) -> Optional[float]:
    q = _q_forces(slices, fs, theta, kh)
    return None if q is None else sum(q)


def _moment_residual(slices, fs, theta, kh) -> Optional[float]:
    q = _q_forces(slices, fs, theta, kh)
    if q is None:
        return None
    st, ct = math.sin(theta), math.cos(theta)
    total = 0.0
    for qi, s in zip(q, slices):
        yb = s.y_base if s.y_base is not None else 0.0
        total += qi * (s.x_mid * st - yb * ct)
    return total


def _force_fs(slices, theta, kh) -> Optional[float]:
    """与えた θ で力平衡 Σ Q=0 を満たす Fs を求める。

    力平衡残差は Fs が大きいほど負（起動項が優勢）、物理解 Fs に近づく
    ほど正に転じる。ただし Fs が小さいと層間力の分母 cos(α−θ)+…/Fs が
    非正となり残差が定義されない領域があるため、高 Fs 側から Fs を下げ
    ながら「定義された値どうしの最初の符号変化（負→正）」を挟んで
    二分探索する。
    """
    # Fs グリッド（高→低）
    n = 80
    fs_hi, fs_lo = 30.0, 0.2
    vals = []
    for i in range(n + 1):
        fs = fs_hi - (fs_hi - fs_lo) * i / n
        r = _force_residual(slices, fs, theta, kh)
        vals.append((fs, r))
    # 定義済みの隣接点で残差が負→正に変わる区間を探す
    prev = None
    for fs, r in vals:
        if r is None:
            prev = None
            continue
        if prev is not None:
            pfs, pr = prev
            if pr < 0 <= r or (pr <= 0 < r):
                lo, hi = fs, pfs  # lo:残差正側 hi:残差負側
                r_lo, r_hi = r, pr
                for _ in range(80):
                    mid = 0.5 * (lo + hi)
                    r_mid = _force_residual(slices, mid, theta, kh)
                    if r_mid is None:
                        break
                    if abs(r_mid) < 1e-10 or abs(hi - lo) < 1e-9:
                        return mid
                    if r_mid >= 0:
                        lo = mid
                    else:
                        hi = mid
                return 0.5 * (lo + hi)
        prev = (fs, r)
    return None


def solve_spencer(
    slices: List[Slice], kh: float
) -> Optional[Tuple[float, float]]:
    """スライス列に対しスペンサー法の (Fs, θ) を求める。

    標準的なスペンサーの反復手順による:
      1. 各 θ に対し、力平衡 Σ Q=0 を厳密に満たす Fs = F_f(θ) を
         二分法で求める（力平衡残差は Fs に単調）。
      2. その Fs を代入したモーメント残差 h(θ)=Σ Q_i(x_i sinθ − y_i cosθ)
         が 0 となる θ を、符号変化を挟んで 1 次元二分探索する。
      3. その θ* における F_f(θ*) を安全率とする（力・モーメント両平衡成立）。
    """

    def h(theta):
        f = _force_fs(slices, theta, kh)
        if f is None:
            return None
        m = _moment_residual(slices, f, theta, kh)
        if m is None:
            return None
        return m, f

    # θ を細かく走査してモーメント残差の符号変化を探す（-50°..+60°）
    n_scan = 111
    lo_deg, hi_deg = -50.0, 60.0
    prev = None
    for i in range(n_scan):
        th = math.radians(lo_deg + (hi_deg - lo_deg) * i / (n_scan - 1))
        hv = h(th)
        if hv is None:
            prev = None
            continue
        m, f = hv
        if prev is not None:
            pth, pm = prev
            if pm == 0.0:
                pf = _force_fs(slices, pth, kh)
                return (pf, pth) if pf is not None else None
            if pm * m < 0:
                lo, hi, mlo = pth, th, pm
                for _ in range(80):
                    mid = 0.5 * (lo + hi)
                    hm = h(mid)
                    if hm is None:
                        break
                    mm, fm = hm
                    if hi - lo < 1e-9:
                        return fm, mid
                    if mlo * mm < 0:
                        hi = mid
                    else:
                        lo, mlo = mid, mm
                mid = 0.5 * (lo + hi)
                fmid = _force_fs(slices, mid, kh)
                return (fmid, mid) if fmid is not None else None
        prev = (th, m)

    # 符号変化なし（層間力の影響が小さい）→ θ=0 の力平衡解を返す
    f0 = _force_fs(slices, 0.0, kh)
    return (f0, 0.0) if f0 is not None else None


def analyze_spencer(
    section: Section,
    surface: List[Point],
    case: Optional[LoadCase] = None,
    n: int = 40,
) -> Optional[CircleResult]:
    """非円弧すべり面をスペンサー法で照査する。

    Returns:
        CircleResult（surface と theta を設定、xc/yc/r は 0）。解が
        得られない場合は None。
    """
    if not surface or len(surface) < 2:
        return None
    kh = case.kh if case is not None else 0.0
    slices = _build_poly_slices(section, surface, n, case)
    if slices is None:
        return None
    sol = solve_spencer(slices, kh)
    if sol is None:
        return None
    fs, theta = sol
    if fs is None or fs <= 0 or not math.isfinite(fs):
        return None
    return CircleResult(
        xc=0.0,
        yc=0.0,
        r=0.0,
        fs=fs,
        slices=slices,
        surface=[Point(p.x, p.y) for p in surface],
        theta=theta,
    )
