"""ブラウザ GUI（Web サーバ）のテスト。"""

import json
import urllib.request

import pytest

from teibo.webapp import _serve_in_thread, make_server

INPUT = {
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
    "cases": [{"name": "常時", "kh": 0.0, "allowable_fs": 1.2}],
    "grid": {"nx": 6, "ny": 6, "nr": 5, "n_slices": 20},
}


@pytest.fixture(scope="module")
def base_url():
    srv = make_server(port=0)  # 空きポートを自動割当
    _serve_in_thread(srv)
    host, port = srv.server_address[:2]
    yield f"http://{host}:{port}"
    srv.shutdown()
    srv.server_close()


def _post(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.status, json.loads(res.read().decode("utf-8"))


def test_index_page(base_url):
    with urllib.request.urlopen(base_url + "/", timeout=10) as res:
        body = res.read().decode("utf-8")
    assert res.status == 200
    assert "teibo" in body
    assert "照査実行" in body


def test_preview_endpoint(base_url):
    status, data = _post(base_url + "/api/preview", {"input": INPUT})
    assert status == 200
    assert "svg" in data
    assert data["svg"].startswith("<svg")


def test_preview_invalid_input(base_url):
    status, data = _post(base_url + "/api/preview", {"input": {"section": {}}})
    assert status == 200
    assert "error" in data


def test_analyze_endpoint(base_url):
    status, data = _post(base_url + "/api/analyze", {"input": INPUT})
    assert status == 200
    assert "report_html" in data
    assert "堤防安定性照査レポート" in data["report_html"]
    assert len(data["summary"]) == 1
    s = data["summary"][0]
    assert s["case"] == "常時"
    assert s["fs"] is not None and s["fs"] > 0
    assert s["judgement"] in ("OK", "NG")
