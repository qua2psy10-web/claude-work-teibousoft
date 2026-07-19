"""液状化判定（FL 法）と過剰間隙水圧の簡易評価。

道路橋示方書の液状化判定を簡略化した実装:

    N1  = 170·N / (σv' + 70)
    Na  = c1·N1 + c2          （c1, c2 は細粒分含有率 FC による補正）
    RL  = 0.0882·√(Na/1.7)                       (Na < 14)
        = 0.0882·√(Na/1.7) + 1.6e-6·(Na−14)^4.5  (Na ≥ 14)
    R   = cw·RL   （本実装では cw = 1.0 固定）
    rd  = 1 − 0.015·z
    L   = rd·kh·σv/σv'
    FL  = R / L

過剰間隙水圧比（共同溝設計指針の簡易式）:

    ru = 1.0        (FL ≤ 1)
    ru = FL^(−7)    (FL > 1)

安定計算では、液状化特性を持つ飽和層のすべり面において
Δu = ru·σv' を静水圧に加算する。
"""

from __future__ import annotations

import math
from typing import Optional


def _fines_correction(fc: float) -> tuple:
    """細粒分含有率 FC (%) による補正係数 (c1, c2)。"""
    if fc < 10.0:
        c1 = 1.0
    elif fc < 60.0:
        c1 = (fc + 40.0) / 50.0
    else:
        c1 = fc / 20.0 - 1.0
    c2 = 0.0 if fc < 10.0 else (fc - 10.0) / 18.0
    return c1, c2


def fl_value(
    n_value: float,
    fines_content: float,
    sigma_v: float,
    sigma_v_eff: float,
    kh: float,
    depth: float,
) -> Optional[float]:
    """液状化抵抗率 FL を計算する。

    Args:
        n_value:      N 値。
        fines_content: 細粒分含有率 FC (%)。
        sigma_v:      全上載圧 σv (kN/m2)。
        sigma_v_eff:  有効上載圧 σv' (kN/m2)。
        kh:           地盤面の設計水平震度。
        depth:        地表面からの深さ z (m)。

    Returns:
        FL 値。せん断応力比 L が 0 以下（kh=0 など）の場合は None
        （液状化判定の対象外）。
    """
    if kh <= 0.0 or sigma_v_eff <= 0.0 or sigma_v <= 0.0:
        return None

    n1 = 170.0 * n_value / (sigma_v_eff + 70.0)
    c1, c2 = _fines_correction(fines_content)
    na = c1 * n1 + c2

    rl = 0.0882 * math.sqrt(max(na, 0.0) / 1.7)
    if na >= 14.0:
        rl += 1.6e-6 * (na - 14.0) ** 4.5
    r = rl  # cw = 1.0

    rd = max(1.0 - 0.015 * depth, 0.0)
    load = rd * kh * sigma_v / sigma_v_eff
    if load <= 0.0:
        return None
    return r / load


def ru_from_fl(fl: Optional[float]) -> float:
    """FL 値から過剰間隙水圧比 ru を求める（共同溝設計指針の簡易式）。"""
    if fl is None:
        return 0.0
    if fl <= 1.0:
        return 1.0
    return min(1.0, fl ** -7.0)
