"""対策工の照査と入力診断のテスト。"""

import math

from teibo.countermeasure import (
    Berm,
    Countermeasure,
    _merged_surface,
    apply_countermeasure,
    run_countermeasures,
)
from teibo.diagnostics import validate_input
from teibo.geometry import interp_polyline
from teibo.io_json import parse_input
from teibo.model import (
    ImprovementZone,
    LoadCase,
    PhreaticLine,
    Point,
    SearchGrid,
    Section,
    SoilLayer,
)
from teibo.search import run_all, search_critical


def _layers(c=8.0, phi=22.0):
    return [
        SoilLayer(
            name="盛土",
            top=[Point(0, 0), Point(8, 4), Point(11, 4), Point(19, 0), Point(30, 0)],
            gamma=18.0,
            gamma_sat=19.0,
            c=c,
            phi=phi,
        ),
        SoilLayer(
            name="地盤",
            top=[Point(0, 0), Point(30, 0)],
            gamma=17.0,
            gamma_sat=18.0,
            c=10.0,
            phi=20.0,
        ),
    ]


def _grid():
    return SearchGrid(nx=8, ny=8, nr=6, n_slices=25)


CASE = LoadCase(name="常時", kh=0.0, allowable_fs=1.2)


# ---------- 押え盛土 ----------

def test_merged_surface():
    surf = [Point(0, 0), Point(10, 5), Point(20, 0), Point(30, 0)]
    berm = [Point(18, 1.5), Point(24, 1.5), Point(27, 0)]
    merged = _merged_surface(surf, berm)
    # 盛土範囲内では max、それ以外は元の地表面
    assert math.isclose(interp_polyline(merged, 5), 2.5, abs_tol=1e-6)
    y20 = interp_polyline(merged, 20)
    assert math.isclose(y20, 1.5, abs_tol=1e-6)
    assert math.isclose(interp_polyline(merged, 29), 0.0, abs_tol=1e-6)
    # x は単調増加
    xs = [p.x for p in merged]
    assert xs == sorted(xs)


def test_berm_increases_fs():
    """法先押え盛土で川裏側の Fs が上がる。"""
    sec = Section(layers=_layers())
    cm = Countermeasure(
        name="押え盛土",
        berm=Berm(
            top=[Point(17, 1.5), Point(22, 1.5), Point(25, 0)],
            gamma=18.0,
            gamma_sat=19.0,
            c=5.0,
            phi=30.0,
        ),
    )
    grid = SearchGrid(nx=8, ny=8, nr=6, n_slices=25, x_entry_min=8.0)
    fs0 = search_critical(sec, CASE, grid).critical.fs
    sec_cm = apply_countermeasure(sec, cm)
    assert len(sec_cm.layers) == 3  # 盛土層が追加されている
    fs1 = search_critical(sec_cm, CASE, grid).critical.fs
    assert fs1 > fs0
    # 元の断面は変更されない
    assert len(sec.layers) == 2


# ---------- 地盤改良 ----------

def test_improvement_increases_fs():
    sec = Section(layers=_layers())
    cm = Countermeasure(
        name="地盤改良",
        improvements=[
            ImprovementZone(
                x_start=10.0, x_end=22.0, y_top=2.0, y_bottom=-3.0,
                c=100.0, phi=0.0,
            )
        ],
    )
    grid = SearchGrid(nx=8, ny=8, nr=6, n_slices=25, x_entry_min=8.0)
    fs0 = search_critical(sec, CASE, grid).critical.fs
    sec_cm = apply_countermeasure(sec, cm)
    fs1 = search_critical(sec_cm, CASE, grid).critical.fs
    assert fs1 > fs0


def test_improvement_zone_strength_used():
    from teibo.stability import build_slices

    sec = Section(layers=_layers())
    zone = ImprovementZone(
        x_start=0.0, x_end=30.0, y_top=5.0, y_bottom=-10.0, c=50.0, phi=5.0
    )
    sec_imp = apply_countermeasure(
        sec, Countermeasure(name="全面改良", improvements=[zone])
    )
    s = build_slices(sec_imp, 13, 8, 8.5, 20)
    assert s is not None
    for sl in s.slices:
        assert math.isclose(sl.c, 50.0)
        assert math.isclose(sl.phi, math.radians(5.0))


# ---------- ドレーン（浸潤線差し替え） ----------

def test_drain_phreatic_increases_fs():
    high = PhreaticLine(points=[Point(0, 3), Point(11, 3), Point(30, 1)])
    low = [[0, 1.0], [30, 0.0]]
    sec = Section(layers=_layers(), phreatic=high)
    cm = Countermeasure(
        name="ドレーン",
        phreatic=PhreaticLine(points=[Point(x, y) for x, y in low]),
    )
    fs0 = search_critical(sec, CASE, _grid()).critical.fs
    sec_cm = apply_countermeasure(sec, cm)
    fs1 = search_critical(sec_cm, CASE, _grid()).critical.fs
    assert fs1 > fs0


# ---------- 統合（JSON 入力から） ----------

def test_run_countermeasures_from_json():
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
                        "phi": 22.0,
                    }
                ],
                "phreatic": [[0, 2], [11, 2], [30, 0.5]],
            },
            "cases": [{"name": "常時", "kh": 0.0, "allowable_fs": 1.2}],
            "grid": {"nx": 6, "ny": 6, "nr": 5, "n_slices": 20},
            "countermeasures": [
                {
                    "name": "押え盛土+改良",
                    "berm": {
                        "top": [[17, 1.5], [22, 1.5], [25, 0]],
                        "gamma": 18.0,
                        "c": 5.0,
                        "phi": 30.0,
                    },
                    "improvement": {
                        "x_start": 12.0, "x_end": 20.0,
                        "y_top": 1.0, "y_bottom": -2.0,
                        "c": 80.0, "phi": 0.0,
                    },
                }
            ],
        }
    )
    assert len(data.countermeasures) == 1
    base = run_all(data.section, data.cases, data.grid)
    cms = run_countermeasures(
        data.section, data.cases, data.grid, data.countermeasures
    )
    assert len(cms) == 1
    assert len(cms[0].results) == 1
    assert cms[0].results[0].critical.fs > base[0].critical.fs


# ---------- 入力診断 ----------

def _base_dict():
    return {
        "section": {
            "layers": [
                {
                    "name": "盛土",
                    "top": [[0, 0], [8, 4], [11, 4], [19, 0], [30, 0]],
                    "gamma": 18.0,
                    "gamma_sat": 19.0,
                    "c": 8.0,
                    "phi": 22.0,
                }
            ]
        },
        "cases": [{"name": "常時", "kh": 0.0, "allowable_fs": 1.2}],
    }


def test_no_warnings_for_clean_input():
    data = parse_input(_base_dict())
    assert validate_input(data) == []


def test_warns_phreatic_above_surface():
    d = _base_dict()
    d["section"]["phreatic"] = [[0, 1], [30, 1]]  # 平地部(y=0)より上
    warnings = validate_input(parse_input(d))
    assert any("浸潤線が地表面より上" in w for w in warnings)


def test_no_warning_when_external_water_covers():
    d = _base_dict()
    d["section"]["phreatic"] = [[0, 1], [8, 1]]
    d["section"]["external_water"] = [[0, 1.5], [8, 1.5]]  # 外水で水没
    warnings = validate_input(parse_input(d))
    assert not any("浸潤線が地表面より上" in w for w in warnings)


def test_warns_inverted_layers():
    d = _base_dict()
    d["section"]["layers"].append(
        {
            "name": "下層",
            "top": [[0, 2], [30, 2]],  # 平地部で上層の上面(y=0)より高い
            "gamma": 17.0,
            "gamma_sat": 18.0,
            "c": 10.0,
            "phi": 20.0,
        }
    )
    warnings = validate_input(parse_input(d))
    assert any("上面が" in w and "高い" in w for w in warnings)


def test_warns_gamma_sat_less_than_gamma():
    d = _base_dict()
    d["section"]["layers"][0]["gamma_sat"] = 17.0  # γt=18 より小
    warnings = validate_input(parse_input(d))
    assert any("γsat" in w for w in warnings)


def test_warns_zero_strength():
    d = _base_dict()
    d["section"]["layers"][0]["c"] = 0.0
    d["section"]["layers"][0]["phi"] = 0.0
    warnings = validate_input(parse_input(d))
    assert any("せん断強度なし" in w for w in warnings)


def test_warns_surcharge_out_of_range():
    d = _base_dict()
    d["section"]["surcharges"] = [{"x_start": 50, "x_end": 60, "q": 10}]
    warnings = validate_input(parse_input(d))
    assert any("定義範囲外" in w for w in warnings)


def test_warns_unused_liquefaction():
    d = _base_dict()
    d["section"]["layers"][0]["liquefaction"] = {"n_value": 10}
    warnings = validate_input(parse_input(d))
    assert any("consider_liquefaction" in w for w in warnings)
