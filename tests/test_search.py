"""臨界すべり円探索の統合テスト。"""

import os

from teibo.io_json import load_input, parse_input
from teibo.search import run_all

EXAMPLE = os.path.join(
    os.path.dirname(__file__), "..", "examples", "river_levee.json"
)


def _simple_input():
    return parse_input(
        {
            "section": {
                "name": "テスト盛土",
                "layers": [
                    {
                        "name": "盛土",
                        "top": [
                            [0, 0], [8, 4], [11, 4], [19, 0], [30, 0],
                        ],
                        "gamma": 18.0, "gamma_sat": 19.0,
                        "c": 10.0, "phi": 25.0,
                    },
                    {
                        "name": "地盤",
                        "top": [[0, 0], [30, 0]],
                        "gamma": 18.0, "gamma_sat": 19.0,
                        "c": 20.0, "phi": 22.0,
                    },
                ],
            },
            "cases": [
                {"name": "常時", "kh": 0.0, "allowable_fs": 1.2},
                {"name": "地震時", "kh": 0.15, "allowable_fs": 1.0},
            ],
            "grid": {"nx": 10, "ny": 10, "nr": 8, "n_slices": 30},
        }
    )


def test_search_finds_circle():
    data = _simple_input()
    results = run_all(data.section, data.cases, data.grid)
    assert len(results) == 2
    for r in results:
        assert r.critical is not None
        assert r.critical.fs > 0
        assert r.evaluated > 0


def test_seismic_case_lower_than_static():
    data = _simple_input()
    results = run_all(data.section, data.cases, data.grid)
    static, seismic = results[0], results[1]
    assert seismic.critical.fs < static.critical.fs


def test_example_file_runs():
    data = load_input(os.path.abspath(EXAMPLE))
    results = run_all(data.section, data.cases, data.grid)
    assert len(results) == 2
    # 常時は OK になる設計断面
    assert results[0].critical is not None
    assert results[0].ok
