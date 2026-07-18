"""安定計算（安全率）のテスト。"""

import math

from teibo.model import LoadCase, PhreaticLine, Point, Section, SoilLayer
from teibo.stability import Slice, bishop_fs, fellenius_fs


def _slice(alpha_deg, W, c, phi_deg, u, width=1.0):
    a = math.radians(alpha_deg)
    return Slice(
        x_mid=0.0,
        width=width,
        height=1.0,
        weight=W,
        alpha=a,
        base_len=width / math.cos(a),
        u=u,
        c=c,
        phi=math.radians(phi_deg),
    )


def test_fellenius_hand_calc():
    """手計算との一致（1スライス）。

    α=30°, W=100, c=5, φ=25°, u=10, l=1/cos30
    n = 100*cos30 - 10*l = 75.05
    resist = 5*l + 75.05*tan25 = 40.77
    drive  = 100*sin30 = 50
    Fs = 0.8155
    """
    s = _slice(30, 100, 5, 25, 10)
    fs = fellenius_fs([s], kh=0.0)
    assert fs is not None
    assert math.isclose(fs, 0.8155, abs_tol=2e-3)


def test_bishop_hand_calc():
    """簡易ビショップの反復収束（1スライス）。"""
    s = _slice(30, 100, 5, 25, 10)
    fs = bishop_fs([s], kh=0.0)
    assert fs is not None
    assert math.isclose(fs, 0.8155, abs_tol=3e-3)


def test_seismic_reduces_fs():
    """水平震度を上げると安全率は低下する。"""
    slices = [_slice(20, 120, 8, 28, 5), _slice(5, 150, 8, 28, 10)]
    fs0 = fellenius_fs(slices, kh=0.0)
    fs1 = fellenius_fs(slices, kh=0.15)
    assert fs0 is not None and fs1 is not None
    assert fs1 < fs0


def test_pore_pressure_reduces_fs():
    """間隙水圧が大きいほど安全率は低下する。"""
    dry = [_slice(25, 100, 10, 30, 0)]
    wet = [_slice(25, 100, 10, 30, 30)]
    fs_dry = fellenius_fs(dry, kh=0.0)
    fs_wet = fellenius_fs(wet, kh=0.0)
    assert fs_wet < fs_dry


def test_cohesion_increases_fs():
    low = [_slice(25, 100, 2, 25, 0)]
    high = [_slice(25, 100, 20, 25, 0)]
    assert fellenius_fs(high, 0.0) > fellenius_fs(low, 0.0)


def test_zero_driving_returns_none():
    """全スライス α=0（すべり方向力ゼロ, kh=0）→ 計算不能。"""
    s = _slice(0, 100, 5, 25, 0)
    assert fellenius_fs([s], kh=0.0) is None
