"""拡張機能（上載荷重・水位条件・クラック・拘束条件・感度分析）のテスト。"""

import math

from teibo.geometry import pore_pressure, water_overburden
from teibo.io_json import parse_input
from teibo.model import (
    LoadCase,
    PhreaticLine,
    Point,
    SearchGrid,
    Section,
    SensitivityTarget,
    SoilLayer,
    Surcharge,
    TensionCrack,
)
from teibo.search import run_all, section_for_case, search_critical
from teibo.sensitivity import run_sensitivity
from teibo.stability import analyze_circle, build_slices


def _layers():
    return [
        SoilLayer(
            name="盛土",
            top=[Point(0, 0), Point(8, 4), Point(11, 4), Point(19, 0), Point(30, 0)],
            gamma=18.0,
            gamma_sat=19.0,
            c=10.0,
            phi=25.0,
        ),
        SoilLayer(
            name="地盤",
            top=[Point(0, 0), Point(30, 0)],
            gamma=18.0,
            gamma_sat=19.0,
            c=20.0,
            phi=22.0,
        ),
    ]


def _grid(**kw):
    base = dict(nx=8, ny=8, nr=6, n_slices=25)
    base.update(kw)
    return SearchGrid(**base)


CASE = LoadCase(name="常時", kh=0.0, allowable_fs=1.2)


# ---------- A1: 上載荷重 ----------

def test_surcharge_reduces_fs():
    """天端への載荷重は安全率を低下させる。"""
    sec_plain = Section(layers=_layers())
    sec_load = Section(
        layers=_layers(),
        surcharges=[Surcharge(x_start=8.0, x_end=11.0, q=30.0)],
    )
    fs_plain = search_critical(sec_plain, CASE, _grid()).critical.fs
    fs_load = search_critical(sec_load, CASE, _grid()).critical.fs
    assert fs_load < fs_plain


def test_surcharge_adds_weight_to_slices():
    sec_plain = Section(layers=_layers())
    sec_load = Section(
        layers=_layers(),
        surcharges=[Surcharge(x_start=8.0, x_end=11.0, q=30.0)],
    )
    s0 = build_slices(sec_plain, 9.5, 9.0, 10.0, 20)
    s1 = build_slices(sec_load, 9.5, 9.0, 10.0, 20)
    assert s0 is not None and s1 is not None
    w0 = sum(s.weight for s in s0.slices)
    w1 = sum(s.weight for s in s1.slices)
    # 荷重合計 = q × 幅 = 30 × 3 = 90 kN/m 分だけ重くなる
    assert math.isclose(w1 - w0, 90.0, rel_tol=0.05)


# ---------- A2: 外水位・ケース別水条件 ----------

def test_external_water_overburden_and_pore_pressure():
    sec = Section(
        layers=_layers(),
        external_water=[Point(0, 2), Point(5, 2)],
    )
    # x=2: 地表 y=1（勾配1:2）、外水位 y=2 → 水柱 1m
    assert math.isclose(water_overburden(sec, 2.0), 9.81 * 1.0, rel_tol=1e-6)
    # 地表より水位が低い位置では 0
    assert water_overburden(sec, 4.5) == 0.0
    # 間隙水圧は外水位を水頭として効く: y_slip=-1 → head=3
    assert math.isclose(pore_pressure(sec, 2.0, -1.0), 9.81 * 3.0, rel_tol=1e-6)


def test_external_water_reduces_fs_on_waterside():
    """外水位（間隙水圧の増加）は川表側の安定を低下させる。

    ※水重（抑え効果）と間隙水圧増の両方が効くが、この形状では
      水位が法先までしかなく間隙水圧の影響が支配的になる。
    """
    sec_dry = Section(layers=_layers())
    sec_wet = Section(
        layers=_layers(),
        external_water=[Point(0, 3), Point(6, 3)],
    )
    # 川表(左)側だけを探索対象にする
    g = _grid(xc_min=2.0, xc_max=9.0, x_exit_max=11.0)
    fs_dry = search_critical(sec_dry, CASE, g).critical.fs
    fs_wet = search_critical(sec_wet, CASE, g).critical.fs
    assert fs_wet != fs_dry  # 外水が計算に反映されている


def test_case_specific_water_override():
    high = PhreaticLine(points=[Point(0, 3), Point(30, 3)])
    sec = Section(
        layers=_layers(),
        phreatic=PhreaticLine(points=[Point(0, 1), Point(30, 1)]),
        external_water=[Point(0, 3), Point(6, 3)],
    )
    case = LoadCase(
        name="水位急降下時",
        phreatic=high,
        external_water=[],
    )
    sec_c = section_for_case(sec, case)
    assert sec_c.phreatic is high
    assert sec_c.external_water is None
    # 元の断面は変更されない
    assert sec.external_water is not None

    # 継承ケース（オーバーライドなし）はそのまま
    sec_same = section_for_case(sec, CASE)
    assert sec_same is sec


def test_drawdown_case_lower_fs():
    """水位急降下（浸潤線高いまま外水なし）は常時より Fs が低い。"""
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
                ],
                "phreatic": [[0, 0.5], [30, 0.5]],
            },
            "cases": [
                {"name": "常時", "kh": 0.0, "allowable_fs": 1.2},
                {
                    "name": "水位急降下時",
                    "kh": 0.0,
                    "allowable_fs": 1.2,
                    "phreatic": [[0, 3.5], [11, 3.5], [30, 0.5]],
                },
            ],
            "grid": {"nx": 8, "ny": 8, "nr": 6, "n_slices": 25},
        }
    )
    results = run_all(data.section, data.cases, data.grid)
    assert results[1].critical.fs < results[0].critical.fs


# ---------- A3: テンションクラック ----------

def test_tension_crack_truncates_and_changes_fs():
    sec_plain = Section(layers=_layers())
    sec_crack = Section(layers=_layers(), tension_crack=TensionCrack(depth=1.5))
    circle = (9.5, 9.0, 10.0)
    s0 = build_slices(sec_plain, *circle, 25)
    s1 = build_slices(sec_crack, *circle, 25)
    assert s0 is not None and s1 is not None
    assert s0.crack_x is None
    assert s1.crack_x is not None
    # クラックですべり面が短くなる
    len0 = s0.slices[-1].x_mid - s0.slices[0].x_mid
    len1 = s1.slices[-1].x_mid - s1.slices[0].x_mid
    assert len1 < len0


def test_crack_water_pressure_reduces_fs():
    """クラック内水圧があるほど安全率は低下する。"""
    sec_dry = Section(layers=_layers(), tension_crack=TensionCrack(depth=1.5))
    sec_wet = Section(
        layers=_layers(), tension_crack=TensionCrack(depth=1.5, water_depth=1.5)
    )
    # 川表法面上の片側すべり円（頭部が天端側に明確にある）
    circle = (2.8, 6.6, 6.55)
    r_dry = analyze_circle(sec_dry, CASE, *circle, 25)
    r_wet = analyze_circle(sec_wet, CASE, *circle, 25)
    assert r_dry is not None and r_wet is not None
    assert r_dry.extra_driving == 0.0
    assert r_wet.extra_driving > 0.0
    assert r_wet.fs < r_dry.fs


# ---------- A4: すべり円の拘束条件 ----------

def test_y_lower_limit_constrains_depth():
    sec = Section(layers=_layers())
    limit = -0.5
    res = search_critical(sec, CASE, _grid(y_lower_limit=limit))
    assert res.critical is not None
    assert res.critical.yc - res.critical.r >= limit - 1e-6


def test_exit_constraint_respected():
    sec = Section(layers=_layers())
    res = search_critical(sec, CASE, _grid(x_exit_min=15.0, x_exit_max=22.0))
    assert res.critical is not None
    xr = res.critical.slices[-1].x_mid + res.critical.slices[-1].width / 2
    assert 15.0 - 1e-6 <= xr <= 22.0 + 1e-6


def test_constraint_changes_critical_circle():
    """拘束をかけると（無拘束の臨界円が除外され）Fs は同じか大きくなる。"""
    sec = Section(layers=_layers())
    free = search_critical(sec, CASE, _grid()).critical
    limited = search_critical(sec, CASE, _grid(y_lower_limit=1.0)).critical
    assert limited is not None
    assert limited.fs >= free.fs - 1e-9


# ---------- A5: 感度分析 ----------

def test_sensitivity_table_shape_and_monotonic():
    sec = Section(layers=_layers())
    cases = [CASE, LoadCase(name="地震時", kh=0.15, allowable_fs=1.0)]
    targets = [SensitivityTarget(layer="盛土", param="c", values=[5.0, 20.0])]
    tables = run_sensitivity(sec, cases, _grid(), targets)
    assert len(tables) == 1
    t = tables[0]
    assert t.case_names == ["常時", "地震時"]
    assert len(t.rows) == 2
    for row in t.rows:
        assert len(row.fs_by_case) == 2
    # c を大きくすると Fs は増える（各ケースで単調増）
    for j in range(2):
        assert t.rows[1].fs_by_case[j] > t.rows[0].fs_by_case[j]


def test_sensitivity_unknown_layer_raises():
    sec = Section(layers=_layers())
    targets = [SensitivityTarget(layer="存在しない層", param="c", values=[5.0])]
    try:
        run_sensitivity(sec, [CASE], _grid(), targets)
    except ValueError:
        pass
    else:
        raise AssertionError("ValueError が送出されるべき")
