"""浸潤線の自動推定（カサグランデ基本放物線）のテスト。"""

import math

from teibo.geometry import interp_polyline, surface_y
from teibo.io_json import parse_input
from teibo.model import Point, Section, SoilLayer
from teibo.search import run_all
from teibo.seepage import estimate_phreatic


def _section(mirror=False):
    pts = [(-5, 0), (0, 0), (10, 5), (13, 5), (23, 0), (40, 0)]
    if mirror:
        pts = [(-x, y) for x, y in reversed(pts)]
    layers = [
        SoilLayer(
            name="盛土",
            top=[Point(x, y) for x, y in pts],
            gamma=18.0,
            gamma_sat=19.0,
            c=10.0,
            phi=25.0,
        )
    ]
    return Section(layers=layers)


def test_estimate_left_boundaries():
    sec = _section()
    ph = estimate_phreatic(sec, water_level=4.0, waterside="left", tail_level=0.5)
    pts = ph.points
    # 左端は外水位
    assert math.isclose(pts[0].y, 4.0, abs_tol=1e-6)
    # 右端は裏水位
    assert math.isclose(pts[-1].y, 0.5, abs_tol=1e-6)
    # x は単調増加
    xs = [p.x for p in pts]
    assert xs == sorted(xs)


def test_estimate_monotonic_and_below_surface():
    sec = _section()
    ph = estimate_phreatic(sec, water_level=4.0, waterside="left")
    # 浸潤線は入水点以降で単調非増加
    ys = [p.y for p in ph.points]
    for a, b in zip(ys, ys[1:]):
        assert b <= a + 1e-9
    # 全域で外水位を超えず、堤体内（入水点より川裏側）では地表面を超えない
    for p in ph.points:
        assert p.y <= 4.0 + 1e-6
        if p.y < 4.0 - 1e-6:  # 放物線部（堤体内）
            ysf = surface_y(sec, p.x)
            if ysf is not None:
                assert p.y <= ysf + 1e-6


def test_estimate_right_mirrors_left():
    left = estimate_phreatic(
        _section(), water_level=4.0, waterside="left", tail_level=0.5
    )
    right = estimate_phreatic(
        _section(mirror=True), water_level=4.0, waterside="right", tail_level=0.5
    )
    # 鏡像断面での推定は左右反転で一致する
    for pl, pr in zip(left.points, reversed(right.points)):
        assert math.isclose(pl.x, -pr.x, abs_tol=1e-9)
        assert math.isclose(pl.y, pr.y, abs_tol=1e-9)


def test_higher_water_gives_higher_line():
    sec = _section()
    lo = estimate_phreatic(sec, water_level=2.0, waterside="left")
    hi = estimate_phreatic(sec, water_level=4.0, waterside="left")
    # 堤体中央部で比較
    x = 12.0
    y_lo = interp_polyline(lo.points, x)
    y_hi = interp_polyline(hi.points, x)
    assert y_lo is not None and y_hi is not None
    assert y_hi > y_lo


def test_invalid_water_level_raises():
    sec = _section()
    try:
        estimate_phreatic(sec, water_level=10.0, waterside="left")  # 天端より上
    except ValueError:
        pass
    else:
        raise AssertionError("ValueError が送出されるべき")


def test_json_seepage_auto_generates_phreatic():
    data = parse_input(
        {
            "section": {
                "layers": [
                    {
                        "name": "盛土",
                        "top": [[-5, 0], [0, 0], [10, 5], [13, 5], [23, 0], [40, 0]],
                        "gamma": 18.0,
                        "gamma_sat": 19.0,
                        "c": 10.0,
                        "phi": 25.0,
                    }
                ],
                "seepage": {"water_level": 4.0, "waterside": "left"},
            },
            "cases": [{"name": "常時", "kh": 0.0, "allowable_fs": 1.2}],
            "grid": {"nx": 8, "ny": 8, "nr": 6, "n_slices": 25},
        }
    )
    assert data.section.phreatic is not None
    assert data.section.phreatic_estimated
    # 自動推定した浸潤線で解析が完走する
    results = run_all(data.section, data.cases, data.grid)
    assert results[0].critical is not None
    assert results[0].critical.fs > 0
