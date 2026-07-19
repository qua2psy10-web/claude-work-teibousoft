"""ブラウザ GUI（標準ライブラリのみのローカル Web サーバ）。

`python -m teibo gui` で起動し、ブラウザから入力 JSON を編集しながら
断面プレビューと安定照査を実行できる。

エンドポイント:
    GET  /             GUI ページ
    POST /api/preview  入力 JSON → 断面プレビュー SVG
    POST /api/analyze  入力 JSON → 照査実行、HTML レポートとサマリを返す
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .io_json import parse_input
from .report import html_report, section_svg
from .search import run_all
from .sensitivity import run_sensitivity

_DEFAULT_INPUT = {
    "section": {
        "name": "河川堤防 標準断面",
        "layers": [
            {
                "name": "盛土（堤体）",
                "top": [[-5, 0], [0, 0], [10, 5], [13, 5], [23, 0], [40, 0]],
                "gamma": 18.0,
                "gamma_sat": 19.0,
                "c": 10.0,
                "phi": 25.0,
            },
            {
                "name": "基礎地盤",
                "top": [[-5, 0], [40, 0]],
                "gamma": 17.0,
                "gamma_sat": 18.0,
                "c": 15.0,
                "phi": 20.0,
            },
        ],
        "seepage": {"water_level": 4.0, "waterside": "left", "tail_level": 0.5},
    },
    "cases": [
        {"name": "常時", "kh": 0.0, "allowable_fs": 1.2, "method": "fellenius"},
        {"name": "地震時", "kh": 0.15, "allowable_fs": 1.0, "method": "fellenius"},
    ],
    "grid": {"nx": 12, "ny": 12, "nr": 10, "n_slices": 40},
}


class _Handler(BaseHTTPRequestHandler):
    initial_input: str = json.dumps(_DEFAULT_INPUT, ensure_ascii=False, indent=2)

    # --- helpers -------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, code: int = 200) -> None:
        self._send(
            code,
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _read_body(self) -> Optional[dict]:
        try:
            n = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def log_message(self, fmt, *args):  # noqa: D102 - 静かに
        pass

    # --- routes --------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            page = _PAGE.replace("{{INITIAL_INPUT}}", _escape_for_textarea(self.initial_input))
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        body = self._read_body()
        if body is None:
            self._send_json({"error": "リクエスト JSON を解釈できません"}, 400)
            return

        if self.path == "/api/preview":
            self._api_preview(body)
        elif self.path == "/api/analyze":
            self._api_analyze(body)
        else:
            self._send_json({"error": "unknown endpoint"}, 404)

    def _api_preview(self, body: dict) -> None:
        try:
            data = parse_input(body.get("input", body))
            svg = section_svg(data.section)
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": f"入力エラー: {e}"})
            return
        self._send_json({"svg": svg})

    def _api_analyze(self, body: dict) -> None:
        try:
            data = parse_input(body.get("input", body))
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": f"入力エラー: {e}"})
            return
        try:
            results = run_all(data.section, data.cases, data.grid)
            sens = None
            if body.get("sensitivity") and data.sensitivity:
                sens = run_sensitivity(
                    data.section, data.cases, data.grid, data.sensitivity
                )
            report = html_report(data.section, results, sensitivity=sens)
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": f"解析エラー: {e}"})
            return

        summary = []
        for r in results:
            summary.append(
                {
                    "case": r.case.name,
                    "fs": round(r.critical.fs, 3) if r.critical else None,
                    "fsa": r.case.allowable_fs,
                    "judgement": r.judgement,
                }
            )
        self._send_json({"report_html": report, "summary": summary})


def _escape_for_textarea(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;")


def make_server(
    host: str = "127.0.0.1", port: int = 8765, initial_input: Optional[str] = None
) -> ThreadingHTTPServer:
    """GUI 用 HTTP サーバを生成する（起動は呼び出し側で serve_forever）。"""
    handler = type("Handler", (_Handler,), {})
    if initial_input is not None:
        handler.initial_input = initial_input
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str = "127.0.0.1", port: int = 8765, initial_input: Optional[str] = None) -> None:
    """GUI サーバを起動する（Ctrl+C で停止）。"""
    srv = make_server(host, port, initial_input)
    actual_port = srv.server_address[1]
    print(f"teibo GUI: http://{host}:{actual_port}/ で起動しました（Ctrl+C で停止）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def _serve_in_thread(srv: ThreadingHTTPServer) -> threading.Thread:
    """テスト用: 別スレッドでサーバを回す。"""
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return t


_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>teibo — 堤防安定性照査 GUI</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic", Meiryo, sans-serif;
         margin: 0; display: flex; flex-direction: column; height: 100vh; }
  header { background: #5a4a2a; color: #fff; padding: 8px 16px; display: flex;
           align-items: center; gap: 16px; }
  header h1 { font-size: 1.05rem; margin: 0; font-weight: 600; }
  header .btns { margin-left: auto; display: flex; gap: 8px; align-items: center; }
  button { padding: 6px 14px; border: none; border-radius: 4px; cursor: pointer;
           font-size: 0.9rem; }
  #run { background: #c0392b; color: #fff; font-weight: 600; }
  #run:disabled { opacity: 0.5; cursor: wait; }
  .ghost { background: #7a6a4a; color: #fff; }
  main { flex: 1; display: flex; min-height: 0; }
  #left { width: 40%; min-width: 320px; display: flex; flex-direction: column;
          border-right: 1px solid #999; }
  #editor { flex: 1; width: 100%; box-sizing: border-box; border: none; resize: none;
            font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12.5px;
            padding: 10px; line-height: 1.5; }
  #msg { padding: 6px 10px; font-size: 0.85rem; min-height: 1.2em; }
  #msg.err { color: #c0392b; } #msg.ok { color: #1a7f37; }
  #right { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  #preview { padding: 8px; border-bottom: 1px solid #999; }
  #preview svg { width: 100%; height: auto; border: 1px solid #ccc;
                 background: #fbfaf6; border-radius: 4px; }
  #summary { padding: 4px 10px; font-size: 0.9rem; display: flex; gap: 14px;
             flex-wrap: wrap; }
  #summary .ok { color: #1a7f37; font-weight: 600; }
  #summary .ng { color: #c0392b; font-weight: 600; }
  #reportwrap { flex: 1; min-height: 0; }
  #report { width: 100%; height: 100%; border: none; }
  label.chk { color: #fff; font-size: 0.85rem; display: flex; gap: 4px;
              align-items: center; }
  @media (prefers-color-scheme: dark) {
    #preview svg { background: #262620; border-color: #555; }
    #left { border-color: #555; }
  }
</style>
</head>
<body>
<header>
  <h1>teibo 堤防安定性照査</h1>
  <div class="btns">
    <label class="chk"><input type="checkbox" id="sens">感度分析</label>
    <button class="ghost" id="load">JSON読込</button>
    <button class="ghost" id="save">JSON保存</button>
    <button id="run">照査実行</button>
    <input type="file" id="file" accept=".json" style="display:none">
  </div>
</header>
<main>
  <div id="left">
    <textarea id="editor" spellcheck="false">{{INITIAL_INPUT}}</textarea>
    <div id="msg"></div>
  </div>
  <div id="right">
    <div id="preview"></div>
    <div id="summary"></div>
    <div id="reportwrap"><iframe id="report"></iframe></div>
  </div>
</main>
<script>
const editor = document.getElementById('editor');
const msg = document.getElementById('msg');
const preview = document.getElementById('preview');
const summary = document.getElementById('summary');
const report = document.getElementById('report');
const runBtn = document.getElementById('run');

function parseEditor() {
  try { return JSON.parse(editor.value); }
  catch (e) { setMsg('JSON 構文エラー: ' + e.message, true); return null; }
}
function setMsg(text, isErr) {
  msg.textContent = text || '';
  msg.className = isErr ? 'err' : 'ok';
}

let timer = null;
async function updatePreview() {
  const input = parseEditor();
  if (!input) return;
  try {
    const res = await fetch('/api/preview', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({input})
    });
    const data = await res.json();
    if (data.error) { setMsg(data.error, true); return; }
    preview.innerHTML = data.svg;
    setMsg('プレビュー更新', false);
  } catch (e) { setMsg('通信エラー: ' + e, true); }
}
editor.addEventListener('input', () => {
  clearTimeout(timer);
  timer = setTimeout(updatePreview, 600);
});

runBtn.addEventListener('click', async () => {
  const input = parseEditor();
  if (!input) return;
  runBtn.disabled = true;
  setMsg('照査を実行中…', false);
  try {
    const res = await fetch('/api/analyze', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({input, sensitivity: document.getElementById('sens').checked})
    });
    const data = await res.json();
    if (data.error) { setMsg(data.error, true); return; }
    report.srcdoc = data.report_html;
    summary.innerHTML = data.summary.map(s => {
      const cls = s.judgement === 'OK' ? 'ok' : 'ng';
      const fs = s.fs === null ? '—' : s.fs.toFixed(3);
      return `<span>${s.case}: Fs=${fs} / Fsa=${s.fsa} <span class="${cls}">${s.judgement}</span></span>`;
    }).join('');
    setMsg('照査完了', false);
  } catch (e) { setMsg('通信エラー: ' + e, true); }
  finally { runBtn.disabled = false; }
});

document.getElementById('load').addEventListener('click', () =>
  document.getElementById('file').click());
document.getElementById('file').addEventListener('change', ev => {
  const f = ev.target.files[0];
  if (!f) return;
  const r = new FileReader();
  r.onload = () => { editor.value = r.result; updatePreview(); };
  r.readAsText(f);
});
document.getElementById('save').addEventListener('click', () => {
  const blob = new Blob([editor.value], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'teibo_input.json';
  a.click();
  URL.revokeObjectURL(a.href);
});

updatePreview();
</script>
</body>
</html>
"""
