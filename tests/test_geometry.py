"""幾何計算のテスト。"""

import math

from teibo.geometry import (
    arc_lower_y,
    column_weight,
    find_arc_surface_intersections,
    interp_polyline,
    phreatic_y,
    pore_pressure,
    surface_y,
)
from teibo.model import PhreaticLine, Point, Section, SoilLayer


def test_interp_polyline_basic():
    pts = [Point(0, 0), Point(10, 10)]
    assert interp_polyline(pts, 0) == 0
    assert interp_polyline(pts, 10) == 10
    assert interp_polyline(pts, 5) == 5
    # 範囲外は None
    assert interp_polyline(pts, -1) is None
    assert interp_polyline(pts, 11) is None


def test_interp_polyline_multi_segment():
    pts = [Point(0, 0), Point(2, 4), Point(4, 0)]
    assert interp_polyline(pts, 1) == 2
    assert interp_polyline(pts, 2) == 4
    assert interp_polyline(pts, 3) == 2


def test_arc_lower_y():
    # 中心(0,10) 半径10 → x=0 で下弧は y=0
    assert math.isclose(arc_lower_y(0, 10, 10, 0), 0.0, abs_tol=1e-9)
    # x=10 (=半径) で y=10（接点）
    assert math.isclose(arc_lower_y(0, 10, 10, 10), 10.0, abs_tol=1e-9)
    # 範囲外
    assert arc_lower_y(0, 10, 10, 11) is None


def _flat_section():
    layer = SoilLayer(
        name="地盤",
        top=[Point(-50, 0), Point(50, 0)],
        gamma=18.0,
        gamma_sat=20.0,
        c=10.0,
        phi=20.0,
    )
    return Section(layers=[layer])


def test_column_weight_dry():
    layer = SoilLayer(
        name="土", top=[Point(0, 10), Point(100, 10)],
        gamma=20.0, gamma_sat=21.0, c=0, phi=0,
    )
    sec = Section(layers=[layer])
    # y=0..5 の柱：層上面(10)より下なので全て湿潤
    assert math.isclose(column_weight(sec, 5, 0, 5), 20.0 * 5, rel_tol=1e-9)


def test_column_weight_with_phreatic():
    layer = SoilLayer(
        name="土", top=[Point(0, 10), Point(100, 10)],
        gamma=18.0, gamma_sat=20.0, c=0, phi=0,
    )
    sec = Section(
        layers=[layer],
        phreatic=PhreaticLine([Point(0, 3), Point(100, 3)]),
    )
    # y=0..5：上2m(3..5)湿潤=18*2、下3m(0..3)飽和=20*3
    expected = 18.0 * 2 + 20.0 * 3
    assert math.isclose(column_weight(sec, 50, 0, 5), expected, rel_tol=1e-9)


def test_pore_pressure():
    sec = Section(
        layers=[SoilLayer("土", [Point(0, 10), Point(100, 10)], 18, 20, 0, 0)],
        phreatic=PhreaticLine([Point(0, 3), Point(100, 3)]),
    )
    # 浸潤線 y=3、すべり面 y=0 → u = 9.81*3
    assert math.isclose(pore_pressure(sec, 50, 0), 9.81 * 3, rel_tol=1e-9)
    # 浸潤線より上のすべり面 → 0
    assert pore_pressure(sec, 50, 5) == 0.0


def test_find_intersections_flat_ground():
    # 平坦地盤 y=0、中心(0,8) 半径10 → 交点は ±6
    sec = _flat_section()
    inter = find_arc_surface_intersections(sec, 0, 8, 10)
    assert inter is not None
    xl, xr = inter
    assert math.isclose(xl, -6.0, abs_tol=0.05)
    assert math.isclose(xr, 6.0, abs_tol=0.05)


def test_no_intersection_when_circle_above_ground():
    sec = _flat_section()
    # 円が地表面より完全に上（中心高すぎず半径小さい）→ 土塊なし
    assert find_arc_surface_intersections(sec, 0, 20, 5) is None
