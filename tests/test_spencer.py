"""スペンサー法（非円弧すべり面）のテスト。"""

import json
import math

from teibo.geometry import arc_lower_y, find_arc_surface_intersections
from teibo.io_json import parse_input
from teibo.model import LoadCase, PhreaticLine, Point, Section, SoilLayer
from teibo.search import run_all
from teibo.model import SearchGrid
from teibo.spencer import (
    _force_residual,
    _moment_residual,
    analyze_spencer,
)
from teibo.stability import bishop_fs, build_slices


def _section():
    return Section(
        layers=[
            SoilLayer(
                "盛土",
                [Point(-5, 0), Point(0, 0), Point(10, 5), Point(13, 5), Point(23, 0), Point(40, 0)],
                18, 19, 10, 25,
            ),
            SoilLayer("基礎地盤", [Point(-5, 0), Point(40, 0)], 17, 18, 15, 20),
        ],
        phreatic=PhreaticLine([Point(-5, 4), Point(0, 4), Point(23, 1), Point(40, 1)]),
    )


def _arc_polyline(section, xc, yc, r, n=60):
    xl, xr = find_arc_surface_intersections(section, xc, yc, r)
    return [
        Point(xl + (xr - xl) * i / n, arc_lower_y(xc, yc, r, xl + (xr - xl) * i / n))
        for i in range(n + 1)
    ]


def test_spencer_matches_bishop_on_circle():
    """円弧すべり面ではスペンサー法が簡易ビショップ法とほぼ一致する。"""
    sec = _section()
    xc, yc, r = 2.57, 7.12, 9.62
    arc = _arc_polyline(sec, xc, yc, r)
    for kh in (0.0, 0.15):
        case = LoadCase("c", kh=kh, method="bishop")
        ss = build_slices(sec, xc, yc, r, 60, case)
        fb = bishop_fs(ss.slices, kh)
        res = analyze_spencer(sec, arc, LoadCase("s", kh=kh, method="spencer"), n=60)
        assert res is not None
        # 円弧すべりでは 3% 以内で一致
        assert abs(res.fs - fb) / fb < 0.03


def test_spencer_equilibrium_residuals_zero():
    """求めた (Fs, θ) で力・モーメント両平衡が成立する。"""
    sec = _section()
    surf = [Point(9, 4.5), Point(13, -2.2), Point(21, -2.2), Point(24, 0)]
    # 軟弱層を足す
    sec = Section(
        layers=[
            SoilLayer("盛土", [Point(-5, 0), Point(0, 0), Point(10, 5), Point(13, 5), Point(23, 0), Point(40, 0)], 19, 20, 15, 30),
            SoilLayer("軟弱層", [Point(-5, -1.5), Point(40, -1.5)], 16, 16, 8, 4),
            SoilLayer("支持層", [Point(-5, -3.0), Point(40, -3.0)], 18, 19, 30, 25),
        ],
        phreatic=PhreaticLine([Point(-5, -1), Point(10, 2), Point(13, 2), Point(23, -1), Point(40, -1)]),
    )
    for kh in (0.0, 0.15):
        case = LoadCase("s", kh=kh, method="spencer")
        res = analyze_spencer(sec, surf, case, n=40)
        assert res is not None
        assert res.surface is not None and res.theta is not None
        fr = _force_residual(res.slices, res.fs, res.theta, kh)
        mr = _moment_residual(res.slices, res.fs, res.theta, kh)
        assert abs(fr) < 1e-3
        assert abs(mr) < 1e-2


def test_spencer_seismic_lowers_fs():
    """地震時（kh>0）は常時より安全率が下がる。"""
    sec = Section(
        layers=[
            SoilLayer("盛土", [Point(-5, 0), Point(0, 0), Point(10, 5), Point(13, 5), Point(23, 0), Point(40, 0)], 19, 20, 15, 30),
            SoilLayer("軟弱層", [Point(-5, -1.5), Point(40, -1.5)], 16, 16, 8, 4),
            SoilLayer("支持層", [Point(-5, -3.0), Point(40, -3.0)], 18, 19, 30, 25),
        ],
        phreatic=PhreaticLine([Point(-5, -1), Point(10, 2), Point(13, 2), Point(23, -1), Point(40, -1)]),
    )
    surf = [Point(9, 4.5), Point(13, -2.2), Point(21, -2.2), Point(24, 0)]
    f0 = analyze_spencer(sec, surf, LoadCase("常時", kh=0.0, method="spencer"), 40)
    fk = analyze_spencer(sec, surf, LoadCase("地震時", kh=0.15, method="spencer"), 40)
    assert f0 is not None and fk is not None
    assert fk.fs < f0.fs


def test_input_slip_surface_distributed_to_spencer_case():
    """入力全体の slip_surface が method=spencer のケースに配られる。"""
    data = {
        "section": {
            "name": "t",
            "layers": [
                {"name": "盛土", "top": [[-5, 0], [0, 0], [10, 5], [13, 5], [23, 0], [40, 0]], "gamma": 19, "gamma_sat": 20, "c": 15, "phi": 30},
                {"name": "軟弱層", "top": [[-5, -1.5], [40, -1.5]], "gamma": 16, "gamma_sat": 16, "c": 8, "phi": 4},
                {"name": "支持層", "top": [[-5, -3], [40, -3]], "gamma": 18, "gamma_sat": 19, "c": 30, "phi": 25},
            ],
            "phreatic": [[-5, -1], [10, 2], [13, 2], [23, -1], [40, -1]],
        },
        "slip_surface": [[9, 4.5], [13, -2.2], [21, -2.2], [24, 0]],
        "cases": [
            {"name": "常時", "kh": 0.0, "allowable_fs": 1.2, "method": "spencer"},
            {"name": "地震時", "kh": 0.15, "allowable_fs": 1.0, "method": "spencer"},
        ],
        "grid": {"n_slices": 40},
    }
    inp = parse_input(data)
    assert inp.slip_surface is not None
    for c in inp.cases:
        assert c.method == "spencer"
        assert c.slip_surface is not None and len(c.slip_surface) == 4
    results = run_all(inp.section, inp.cases, inp.grid)
    assert results[0].critical is not None
    assert results[0].critical.surface is not None
    # 常時 OK・地震時 NG
    assert results[0].ok is True
    assert results[1].ok is False


def test_spencer_case_without_surface_auto_searches():
    """slip_surface 未指定の spencer ケースは臨界非円弧面を自動探索する。"""
    sec = _section()
    case = LoadCase("s", kh=0.0, method="spencer")  # slip_surface なし
    results = run_all(sec, [case], SearchGrid(nx=10, ny=10, nr=8, n_slices=30, nc_nodes=5))
    cr = results[0].critical
    assert cr is not None
    assert cr.surface is not None and len(cr.surface) >= 3
    assert cr.theta is not None
    # 求めた解は力・モーメント両平衡を満たす
    fr = _force_residual(cr.slices, cr.fs, cr.theta, case.kh)
    mr = _moment_residual(cr.slices, cr.fs, cr.theta, case.kh)
    tw = sum(s.weight for s in cr.slices)
    assert abs(fr) < 1e-3 * tw
    assert abs(mr) < 1e-3 * tw * 30.0


def test_noncircular_search_finds_base_slide():
    """明確に弱い連続層があると、自動探索は円弧より低い基盤すべりを見つける。"""
    from teibo.ncsearch import search_noncircular

    sec = Section(
        layers=[
            SoilLayer("盛土", [Point(-5, 0), Point(0, 0), Point(10, 5), Point(13, 5), Point(23, 0), Point(40, 0)], 20, 21, 25, 32),
            SoilLayer("極軟弱層", [Point(-5, -1.0), Point(40, -1.0)], 15, 15, 2, 1),
            SoilLayer("支持層", [Point(-5, -2.0), Point(40, -2.0)], 19, 20, 40, 28),
        ],
        phreatic=PhreaticLine([Point(-5, -1.5), Point(40, -1.5)]),
    )
    grid = SearchGrid(nx=12, ny=12, nr=10, n_slices=40, nc_nodes=7)
    case = LoadCase("常時", kh=0.0, method="spencer")
    circ = run_all(sec, [LoadCase("c", kh=0.0, method="bishop")], grid)[0].critical
    res = search_noncircular(sec, case, grid)
    assert res is not None and res.surface is not None
    # 基盤すべりが円弧よりはるかに危険（低い Fs）であることを検出
    assert res.fs < circ.fs
    # すべり面の最深部が軟弱層付近まで達している
    ys = [p.y for p in res.surface]
    assert min(ys) <= -0.9


def test_example_noncircular_json():
    """同梱の非円弧すべり例が読み込め、両ケースとも解が得られる。"""
    with open("examples/levee_noncircular.json", encoding="utf-8") as f:
        data = json.load(f)
    inp = parse_input(data)
    results = run_all(inp.section, inp.cases, inp.grid)
    assert len(results) == 2
    for r in results:
        assert r.critical is not None
        assert r.critical.surface is not None
        assert math.isfinite(r.critical.fs)
