"""液状化（FL 法）とニューマーク法のテスト。"""

import math

from teibo.io_json import parse_input
from teibo.liquefaction import fl_value, ru_from_fl
from teibo.model import Point
from teibo.newmark import (
    displacement_empirical,
    displacement_time_history,
    run_newmark,
    yield_kh,
)
from teibo.search import run_all
from teibo.stability import Slice


# ---------- FL 法 ----------

def test_fl_increases_with_n_value():
    """N 値が大きいほど FL は大きい（液状化しにくい）。"""
    args = dict(fines_content=10.0, sigma_v=100.0, sigma_v_eff=60.0, kh=0.2, depth=5.0)
    fl_lo = fl_value(n_value=5, **args)
    fl_hi = fl_value(n_value=20, **args)
    assert fl_lo is not None and fl_hi is not None
    assert fl_hi > fl_lo


def test_fl_decreases_with_kh():
    args = dict(n_value=10, fines_content=10.0, sigma_v=100.0, sigma_v_eff=60.0, depth=5.0)
    fl1 = fl_value(kh=0.15, **args)
    fl2 = fl_value(kh=0.3, **args)
    assert fl2 < fl1


def test_fl_none_when_static():
    """kh=0 では液状化判定の対象外。"""
    assert fl_value(10, 10.0, 100.0, 60.0, kh=0.0, depth=5.0) is None


def test_ru_from_fl():
    assert ru_from_fl(0.8) == 1.0
    assert ru_from_fl(1.0) == 1.0
    assert math.isclose(ru_from_fl(2.0), 2.0 ** -7)
    assert ru_from_fl(None) == 0.0
    # FL が大きいほど ru は小さい
    assert ru_from_fl(1.5) > ru_from_fl(3.0)


def _liq_input(consider: bool):
    return parse_input(
        {
            "section": {
                "layers": [
                    {
                        "name": "盛土",
                        "top": [[0, 0], [8, 4], [11, 4], [19, 0], [30, 0]],
                        "gamma": 18.0,
                        "gamma_sat": 19.0,
                        "c": 5.0,
                        "phi": 28.0,
                    },
                    {
                        "name": "液状化層（緩い砂）",
                        "top": [[0, 0], [30, 0]],
                        "gamma": 17.0,
                        "gamma_sat": 18.0,
                        "c": 0.0,
                        "phi": 30.0,
                        "liquefaction": {"n_value": 6, "fines_content": 5},
                    },
                ],
                "phreatic": [[0, 0], [30, 0]],
            },
            "cases": [
                {
                    "name": "地震時",
                    "kh": 0.2,
                    "allowable_fs": 1.0,
                    "consider_liquefaction": consider,
                }
            ],
            "grid": {"nx": 8, "ny": 8, "nr": 6, "n_slices": 25},
        }
    )


def test_liquefaction_reduces_fs():
    """液状化考慮により Fs は低下し、FL がスライスに記録される。"""
    plain = _liq_input(False)
    liq = _liq_input(True)
    r0 = run_all(plain.section, plain.cases, plain.grid)[0]
    r1 = run_all(liq.section, liq.cases, liq.grid)[0]
    assert r0.critical is not None and r1.critical is not None
    assert r1.critical.fs < r0.critical.fs
    fls = [s.fl for s in r1.critical.slices if s.fl is not None]
    assert fls, "FL が記録されるべき"
    assert all(f > 0 for f in fls)


# ---------- ニューマーク法 ----------

def _slice(alpha_deg, W, c, phi_deg, u=0.0, width=1.0):
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


def test_yield_kh_gives_fs_one():
    from teibo.stability import fellenius_fs

    slices = [_slice(25, 120, 10, 30), _slice(10, 150, 10, 30)]
    ky = yield_kh(slices)
    assert ky is not None and ky > 0
    fs = fellenius_fs(slices, ky)
    assert math.isclose(fs, 1.0, abs_tol=1e-3)


def test_yield_kh_zero_when_unstable():
    """常時から Fs<1 のすべり面では ky=0。"""
    slices = [_slice(40, 200, 1, 10)]
    assert yield_kh(slices) == 0.0


def test_displacement_empirical():
    # ky >= kmax → 滑動しない
    assert displacement_empirical(0.3, 0.2) == 0.0
    # ky が小さいほど変位量は大きい
    d1 = displacement_empirical(0.05, 0.2)
    d2 = displacement_empirical(0.15, 0.2)
    assert d1 is not None and d2 is not None
    assert d1 > d2 > 0
    # ky=0 は適用範囲外
    assert displacement_empirical(0.0, 0.2) is None


def test_displacement_time_history():
    # 一定加速度 300 gal、ay = 0.1g ≈ 98.1 gal → 滑動する
    accel = [Point(t * 0.01, 300.0) for t in range(101)]  # 1 秒間
    d = displacement_time_history(accel, ky=0.1)
    assert d is not None and d > 0
    # 降伏加速度以下なら滑動しない
    d0 = displacement_time_history([Point(0, 50.0), Point(1, 50.0)], ky=0.1)
    assert d0 == 0.0
    # ky が大きいほど変位量は小さい
    d2 = displacement_time_history(accel, ky=0.2)
    assert d2 < d


def test_run_newmark_integration():
    data = parse_input(
        {
            "section": {
                "layers": [
                    {
                        "name": "盛土",
                        "top": [[0, 0], [8, 4], [11, 4], [19, 0], [30, 0]],
                        "gamma": 18.0,
                        "gamma_sat": 19.0,
                        "c": 8.0,
                        "phi": 20.0,
                    }
                ],
                "phreatic": [[0, 2], [11, 2], [30, 0.5]],
            },
            "cases": [
                {
                    "name": "地震時",
                    "kh": 0.25,
                    "allowable_fs": 1.0,
                    "newmark": True,
                    "allowable_displacement": 0.3,
                }
            ],
            "grid": {"nx": 8, "ny": 8, "nr": 6, "n_slices": 25},
        }
    )
    results = run_all(data.section, data.cases, data.grid)
    nms = run_newmark(results, data.accel_series)
    assert len(nms) == 1
    nm = nms[0]
    assert nm.ky is not None
    # 地震時 Fs<1 なら ky < kh のはず
    if results[0].critical.fs < 1.0:
        assert nm.ky < nm.kmax
        assert nm.displacement is not None and nm.displacement > 0
    assert nm.judgement in ("OK", "NG", "算定不能")


def test_newmark_skipped_without_flag():
    data = parse_input(
        {
            "section": {
                "layers": [
                    {
                        "name": "盛土",
                        "top": [[0, 0], [8, 4], [11, 4], [19, 0], [30, 0]],
                        "gamma": 18.0,
                        "gamma_sat": 19.0,
                        "c": 10.0,
                        "phi": 25.0,
                    }
                ]
            },
            "cases": [{"name": "地震時", "kh": 0.15, "allowable_fs": 1.0}],
            "grid": {"nx": 6, "ny": 6, "nr": 5, "n_slices": 20},
        }
    )
    results = run_all(data.section, data.cases, data.grid)
    assert run_newmark(results) == []
