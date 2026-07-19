"""複数断面一括処理のテスト。"""

import json

from teibo.batch import (
    batch_csv,
    batch_html_report,
    batch_text_report,
    run_batch,
)
from teibo.cli import main


def _write_section(path, station, distance, c):
    data = {
        "station": station,
        "distance": distance,
        "section": {
            "name": f"断面 {station}",
            "layers": [
                {
                    "name": "盛土",
                    "top": [[0, 0], [8, 4], [11, 4], [19, 0], [30, 0]],
                    "gamma": 18.0,
                    "gamma_sat": 19.0,
                    "c": c,
                    "phi": 25.0,
                }
            ],
        },
        "cases": [
            {"name": "常時", "kh": 0.0, "allowable_fs": 1.2},
            {"name": "地震時", "kh": 0.15, "allowable_fs": 1.0},
        ],
        "grid": {"nx": 6, "ny": 6, "nr": 5, "n_slices": 20},
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_run_batch_sorts_by_distance(tmp_path):
    # 距離の逆順で渡してもソートされる
    p2 = _write_section(tmp_path / "b.json", "0k200", 200, 10.0)
    p1 = _write_section(tmp_path / "a.json", "0k000", 0, 15.0)
    entries = run_batch([p2, p1])
    assert [e.station for e in entries] == ["0k000", "0k200"]
    for e in entries:
        assert len(e.results) == 2
        assert e.results[0].critical is not None
    # c が大きい断面のほうが Fs が大きい
    assert entries[0].results[0].critical.fs > entries[1].results[0].critical.fs


def test_station_falls_back_to_filename(tmp_path):
    p = tmp_path / "no_300.json"
    _write_section(p, None, None, 10.0)
    # station フィールドを消す
    d = json.loads(p.read_text(encoding="utf-8"))
    del d["station"]
    del d["distance"]
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    entries = run_batch([str(p)])
    assert entries[0].station == "no_300"
    assert entries[0].distance is None


def test_batch_csv_and_text(tmp_path):
    p1 = _write_section(tmp_path / "a.json", "0k000", 0, 15.0)
    p2 = _write_section(tmp_path / "b.json", "0k200", 200, 10.0)
    entries = run_batch([p1, p2])
    csv = batch_csv(entries)
    lines = csv.strip().split("\n")
    assert lines[0] == "station,distance,常時_Fs,常時_判定,地震時_Fs,地震時_判定"
    assert len(lines) == 3
    assert lines[1].startswith("0k000,0,")
    text = batch_text_report(entries)
    assert "0k000" in text and "0k200" in text
    assert "最小" in text


def test_batch_html_report(tmp_path):
    p1 = _write_section(tmp_path / "a.json", "0k000", 0, 15.0)
    entries = run_batch([p1])
    html = batch_html_report(entries, details=True)
    assert "縦断方向の最小安全率" in html
    assert "svg" in html
    assert "断面別詳細" in html


def test_cli_batch(tmp_path):
    p1 = _write_section(tmp_path / "a.json", "0k000", 0, 15.0)
    # 地震時に NG となる弱い断面を混ぜる
    p2 = _write_section(tmp_path / "b.json", "0k200", 200, 1.0)
    csv_out = tmp_path / "out.csv"
    html_out = tmp_path / "out.html"
    code = main(
        ["batch", p1, p2, "--csv", str(csv_out), "--html", str(html_out), "--quiet"]
    )
    # 地震時 NG があるため終了コード 1
    assert code == 1
    assert csv_out.exists() and html_out.exists()
    assert "常時_Fs" in csv_out.read_text(encoding="utf-8")


def test_cli_batch_missing_file():
    assert main(["batch", "no_such_file.json", "--quiet"]) == 2
