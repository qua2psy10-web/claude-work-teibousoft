"""ブラウザ GUI（標準ライブラリのみのローカル Web サーバ）。

`python -m teibo gui` で起動し、ブラウザから入力シート（フォーム）
または JSON を編集しながら断面プレビューと安定照査を実行できる。

エンドポイント:
    GET  /             GUI ページ
    POST /api/preview  入力 JSON → 断面プレビュー SVG + 入力診断
    POST /api/analyze  入力 JSON → 照査実行、HTML レポートとサマリを返す
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .countermeasure import run_countermeasures
from .diagnostics import validate_input
from .io_json import parse_input
from .newmark import run_newmark
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
        "seepage": {"water_level": 4.0, "waterside": "left", "tail_level": 0.0},
        "external_water": [[-5, 4], [8, 4]],
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
            page = _PAGE.replace(
                "{{INITIAL_INPUT}}", _escape_for_textarea(self.initial_input)
            )
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
            warnings = validate_input(data)
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": f"入力エラー: {e}"})
            return
        self._send_json({"svg": svg, "warnings": warnings})

    def _api_analyze(self, body: dict) -> None:
        try:
            data = parse_input(body.get("input", body))
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": f"入力エラー: {e}"})
            return
        try:
            warnings = validate_input(data) or None
            results = run_all(data.section, data.cases, data.grid)
            nm = run_newmark(results, data.accel_series) or None
            cms = None
            if data.countermeasures:
                cms = run_countermeasures(
                    data.section, data.cases, data.grid, data.countermeasures
                )
            sens = None
            if body.get("sensitivity") and data.sensitivity:
                sens = run_sensitivity(
                    data.section, data.cases, data.grid, data.sensitivity
                )
            report = html_report(
                data.section,
                results,
                sensitivity=sens,
                newmark=nm,
                countermeasures=cms,
                warnings=warnings,
            )
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
  * { box-sizing: border-box; }
  body { font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic", Meiryo, sans-serif;
         margin: 0; display: flex; flex-direction: column; height: 100vh; }
  header { background: #5a4a2a; color: #fff; padding: 8px 16px; display: flex;
           align-items: center; gap: 16px; flex-wrap: wrap; }
  header h1 { font-size: 1.05rem; margin: 0; font-weight: 600; }
  header .btns { margin-left: auto; display: flex; gap: 8px; align-items: center; }
  button { padding: 6px 14px; border: none; border-radius: 4px; cursor: pointer;
           font-size: 0.9rem; }
  #run { background: #c0392b; color: #fff; font-weight: 600; }
  #run:disabled { opacity: 0.5; cursor: wait; }
  .ghost { background: #7a6a4a; color: #fff; }
  main { flex: 1; display: flex; min-height: 0; }
  #left { width: 46%; min-width: 380px; display: flex; flex-direction: column;
          border-right: 1px solid #999; min-height: 0; }
  .tabs { display: flex; border-bottom: 1px solid #999; background: #efe7d4; }
  .tabs button { border-radius: 0; background: transparent; color: inherit;
                 padding: 8px 18px; border-bottom: 3px solid transparent; }
  .tabs button.active { border-bottom-color: #c0392b; font-weight: 600;
                        background: rgba(192,57,43,0.06); }
  #sheet { flex: 1; overflow-y: auto; padding: 10px 12px; display: none; }
  #sheet.active { display: block; }
  #jsonwrap { flex: 1; display: none; flex-direction: column; min-height: 0; }
  #jsonwrap.active { display: flex; }
  #editor { flex: 1; width: 100%; border: none; resize: none;
            font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12.5px;
            padding: 10px; line-height: 1.5; }
  #msg { padding: 6px 10px; font-size: 0.85rem; min-height: 1.2em;
         border-top: 1px solid #ccc; }
  #msg.err { color: #b3261e; } #msg.ok { color: #1a7f37; }
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
  /* 入力シート */
  details.sec { border: 1px solid #c9bfa5; border-radius: 6px; margin-bottom: 10px;
                background: rgba(239,231,212,0.35); }
  details.sec > summary { padding: 7px 12px; font-weight: 600; cursor: pointer;
                          user-select: none; }
  .secbody { padding: 4px 12px 12px; }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
         margin: 6px 0; }
  .row label { font-size: 0.85rem; display: flex; gap: 4px; align-items: center; }
  input[type=number] { width: 76px; padding: 3px 5px; }
  input[type=text] { padding: 3px 6px; }
  select { padding: 3px 5px; }
  table.pts, table.cases { border-collapse: collapse; font-size: 0.85rem;
                           margin: 4px 0; }
  table.pts th, table.pts td, table.cases th, table.cases td {
    border: 1px solid #bbb; padding: 2px 4px; text-align: center; }
  table.pts input { width: 68px; border: none; background: transparent;
                    text-align: center; }
  table.cases input[type=number] { width: 62px; }
  table.cases input[type=text] { width: 110px; }
  .mini { padding: 2px 8px; font-size: 0.8rem; background: #d8cdb2; color: #333; }
  .mini.del { background: #e5c1bb; }
  .layercard { border: 1px solid #d5cbb0; border-radius: 6px; padding: 8px 10px;
               margin: 8px 0; background: rgba(255,255,255,0.35); }
  .layercard h4 { margin: 0 0 4px; font-size: 0.9rem; }
  .hint { font-size: 0.78rem; color: #777; margin: 2px 0; }
  @media (prefers-color-scheme: dark) {
    .tabs { background: #33301f; }
    #preview svg { background: #262620; border-color: #555; }
    #left { border-color: #555; }
    details.sec { background: rgba(58,51,32,0.4); border-color: #5a523a; }
    .layercard { background: rgba(255,255,255,0.05); border-color: #5a523a; }
    .mini { background: #5a523a; color: #eee; }
    .mini.del { background: #6a3a32; }
    .hint { color: #999; }
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
    <div class="tabs">
      <button id="tabSheet" class="active">入力シート</button>
      <button id="tabJson">JSON</button>
    </div>
    <div id="sheet" class="active"></div>
    <div id="jsonwrap">
      <textarea id="editor" spellcheck="false">{{INITIAL_INPUT}}</textarea>
    </div>
    <div id="msg"></div>
  </div>
  <div id="right">
    <div id="preview"></div>
    <div id="summary"></div>
    <div id="reportwrap"><iframe id="report"></iframe></div>
  </div>
</main>
<script>
'use strict';
const editor = document.getElementById('editor');
const msg = document.getElementById('msg');
const preview = document.getElementById('preview');
const summary = document.getElementById('summary');
const report = document.getElementById('report');
const runBtn = document.getElementById('run');
const sheet = document.getElementById('sheet');
const jsonwrap = document.getElementById('jsonwrap');
const tabSheet = document.getElementById('tabSheet');
const tabJson = document.getElementById('tabJson');

let state = JSON.parse(editor.value);
let activeTab = 'sheet';

function setMsg(text, isErr) {
  msg.textContent = text || '';
  msg.className = isErr ? 'err' : 'ok';
}

/* ---------- 共通ヘルパ ---------- */
function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'checked') e.checked = v;
    else if (k === 'selected') { if (v) e.setAttribute('selected', ''); }
    else if (k === 'value') e.value = v;
    else if (v === false || v == null) { /* 論理属性の false は付けない */ }
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    e.append(c.nodeType ? c : document.createTextNode(c));
  }
  return e;
}
function num(v) { const f = parseFloat(v); return isNaN(f) ? 0 : f; }

function numField(label, value, onchange, step) {
  return el('label', null, label,
    el('input', {type: 'number', step: step || 'any', value: value ?? '',
                 oninput: ev => { onchange(num(ev.target.value)); sync(); }}));
}
function optNumField(label, value, onchange) {
  return el('label', null, label,
    el('input', {type: 'number', step: 'any', value: value ?? '',
                 oninput: ev => {
                   const t = ev.target.value.trim();
                   onchange(t === '' ? null : num(t)); sync();
                 }}));
}

/* 座標テーブル [[x,y],...] */
function pointsTable(pts, rerender) {
  const tbl = el('table', {class: 'pts'});
  tbl.append(el('tr', null, el('th', null, '#'), el('th', null, 'x (m)'),
                 el('th', null, 'y (m)'), el('th', null, '')));
  pts.forEach((p, i) => {
    tbl.append(el('tr', null,
      el('td', null, String(i + 1)),
      el('td', null, el('input', {type: 'number', step: 'any', value: p[0],
        oninput: ev => { p[0] = num(ev.target.value); sync(); }})),
      el('td', null, el('input', {type: 'number', step: 'any', value: p[1],
        oninput: ev => { p[1] = num(ev.target.value); sync(); }})),
      el('td', null, el('button', {class: 'mini del', onclick: () => {
        pts.splice(i, 1); rerender(); sync();
      }}, '×'))));
  });
  const addRow = el('button', {class: 'mini', onclick: () => {
    const last = pts[pts.length - 1] || [0, 0];
    pts.push([last[0] + 5, last[1]]);
    rerender(); sync();
  }}, '＋ 点を追加');
  return el('div', null, tbl, addRow);
}

/* ---------- 入力シート描画 ---------- */
function renderForm() {
  sheet.textContent = '';
  const sec = state.section = state.section || {};
  sec.layers = sec.layers || [];

  /* --- 断面・土層 --- */
  const dLayers = el('details', {class: 'sec', open: ''},
    el('summary', null, '断面・土層'));
  const bodyL = el('div', {class: 'secbody'});
  bodyL.append(el('div', {class: 'row'},
    el('label', null, '断面名 ',
      el('input', {type: 'text', size: 30, value: sec.name || '',
        oninput: ev => { sec.name = ev.target.value; sync(); }}))));
  bodyL.append(el('p', {class: 'hint'},
    '層は上から順。1層目の上面が堤防表面。座標は左→右（x昇順）、y は標高 (m)。'));
  sec.layers.forEach((ly, i) => {
    const card = el('div', {class: 'layercard'});
    card.append(el('h4', null, `第${i + 1}層`));
    card.append(el('div', {class: 'row'},
      el('label', null, '層名 ',
        el('input', {type: 'text', size: 14, value: ly.name || '',
          oninput: ev => { ly.name = ev.target.value; sync(); }})),
      numField('γt', ly.gamma, v => ly.gamma = v),
      numField('γsat', ly.gamma_sat, v => ly.gamma_sat = v),
      numField('c', ly.c, v => ly.c = v),
      numField('φ', ly.phi, v => ly.phi = v)));
    const liqOn = !!ly.liquefaction;
    const liqRow = el('div', {class: 'row'},
      el('label', null,
        el('input', {type: 'checkbox', checked: liqOn, onchange: ev => {
          if (ev.target.checked) ly.liquefaction = {n_value: 10, fines_content: 10};
          else delete ly.liquefaction;
          renderForm(); sync();
        }}), '液状化特性'),
      liqOn ? numField('N値', ly.liquefaction.n_value,
                v => ly.liquefaction.n_value = v) : null,
      liqOn ? numField('FC(%)', ly.liquefaction.fines_content,
                v => ly.liquefaction.fines_content = v) : null);
    card.append(liqRow);
    card.append(el('div', {class: 'hint'}, '層上面の座標'));
    ly.top = ly.top || [[0, 0], [10, 0]];
    card.append(pointsTable(ly.top, renderForm));
    card.append(el('button', {class: 'mini del', onclick: () => {
      sec.layers.splice(i, 1); renderForm(); sync();
    }}, 'この層を削除'));
    bodyL.append(card);
  });
  bodyL.append(el('button', {class: 'mini', onclick: () => {
    const last = sec.layers[sec.layers.length - 1];
    sec.layers.push({name: `第${sec.layers.length + 1}層`,
      top: last ? JSON.parse(JSON.stringify(last.top)) : [[0, 0], [10, 0]],
      gamma: 18, gamma_sat: 19, c: 10, phi: 25});
    renderForm(); sync();
  }}, '＋ 層を追加'));
  dLayers.append(bodyL);
  sheet.append(dLayers);

  /* --- 水条件 --- */
  const dWater = el('details', {class: 'sec', open: ''},
    el('summary', null, '水条件（浸潤線・外水位）'));
  const bodyW = el('div', {class: 'secbody'});
  const mode = sec.phreatic ? 'points' : (sec.seepage ? 'auto' : 'none');
  const radios = el('div', {class: 'row'});
  [['none', 'なし'], ['auto', '自動推定（カサグランデ）'], ['points', '座標で入力']]
    .forEach(([v, lbl]) => {
      radios.append(el('label', null,
        el('input', {type: 'radio', name: 'phmode', checked: mode === v,
          onchange: () => {
            if (v === 'none') { delete sec.phreatic; delete sec.seepage; }
            else if (v === 'auto') {
              delete sec.phreatic;
              sec.seepage = sec.seepage ||
                {water_level: 4.0, waterside: 'left', tail_level: 0.0};
            } else {
              delete sec.seepage;
              sec.phreatic = sec.phreatic || [[0, 2], [20, 1]];
            }
            renderForm(); sync();
          }}), lbl));
    });
  bodyW.append(el('div', {class: 'hint'}, '浸潤線'), radios);
  if (mode === 'auto') {
    const sp = sec.seepage;
    bodyW.append(el('div', {class: 'row'},
      numField('外水位 (m)', sp.water_level, v => sp.water_level = v),
      el('label', null, '川表側 ',
        el('select', {onchange: ev => { sp.waterside = ev.target.value; sync(); }},
          el('option', {value: 'left', selected: sp.waterside !== 'right'}, '左'),
          el('option', {value: 'right', selected: sp.waterside === 'right'}, '右'))),
      numField('裏水位 (m)', sp.tail_level, v => sp.tail_level = v)));
  } else if (mode === 'points') {
    bodyW.append(pointsTable(sec.phreatic, renderForm));
  }
  const extOn = !!sec.external_water;
  bodyW.append(el('div', {class: 'row'},
    el('label', null,
      el('input', {type: 'checkbox', checked: extOn, onchange: ev => {
        if (ev.target.checked) sec.external_water = [[0, 3], [10, 3]];
        else delete sec.external_water;
        renderForm(); sync();
      }}), '外水位（河川水位）を設定')));
  if (extOn) bodyW.append(pointsTable(sec.external_water, renderForm));
  dWater.append(bodyW);
  sheet.append(dWater);

  /* --- 荷重・クラック --- */
  const dLoad = el('details', {class: 'sec'},
    el('summary', null, '上載荷重・テンションクラック'));
  const bodyQ = el('div', {class: 'secbody'});
  sec.surcharges = sec.surcharges || [];
  sec.surcharges.forEach((sc, i) => {
    bodyQ.append(el('div', {class: 'row'},
      el('label', null, '名称 ',
        el('input', {type: 'text', size: 10, value: sc.name || '載荷重',
          oninput: ev => { sc.name = ev.target.value; sync(); }})),
      numField('x開始', sc.x_start, v => sc.x_start = v),
      numField('x終了', sc.x_end, v => sc.x_end = v),
      numField('q (kN/m²)', sc.q, v => sc.q = v),
      el('button', {class: 'mini del', onclick: () => {
        sec.surcharges.splice(i, 1); renderForm(); sync();
      }}, '×')));
  });
  bodyQ.append(el('button', {class: 'mini', onclick: () => {
    (sec.surcharges = sec.surcharges || []).push(
      {name: '載荷重', x_start: 0, x_end: 5, q: 10});
    renderForm(); sync();
  }}, '＋ 載荷重を追加'));
  if (sec.surcharges && sec.surcharges.length === 0) delete sec.surcharges;
  const tcOn = !!sec.tension_crack;
  const tcRow = el('div', {class: 'row'},
    el('label', null,
      el('input', {type: 'checkbox', checked: tcOn, onchange: ev => {
        if (ev.target.checked) sec.tension_crack = {depth: 1.0, water_depth: 0.0};
        else delete sec.tension_crack;
        renderForm(); sync();
      }}), 'テンションクラック'),
    tcOn ? numField('深さ zc (m)', sec.tension_crack.depth,
             v => sec.tension_crack.depth = v) : null,
    tcOn ? numField('水深 zw (m)', sec.tension_crack.water_depth,
             v => sec.tension_crack.water_depth = v) : null);
  bodyQ.append(tcRow);
  dLoad.append(bodyQ);
  sheet.append(dLoad);

  /* --- 照査ケース --- */
  const dCases = el('details', {class: 'sec', open: ''},
    el('summary', null, '照査ケース'));
  const bodyC = el('div', {class: 'secbody'});
  state.cases = state.cases || [];
  const tbl = el('table', {class: 'cases'});
  tbl.append(el('tr', null,
    ...['ケース名', 'kh', 'Fsa', '解析法', '液状化', 'ﾆｭｰﾏｰｸ', 'Da(m)', '']
      .map(h => el('th', null, h))));
  state.cases.forEach((c, i) => {
    tbl.append(el('tr', null,
      el('td', null, el('input', {type: 'text', value: c.name || '',
        oninput: ev => { c.name = ev.target.value; sync(); }})),
      el('td', null, el('input', {type: 'number', step: 'any', value: c.kh ?? 0,
        oninput: ev => { c.kh = num(ev.target.value); sync(); }})),
      el('td', null, el('input', {type: 'number', step: 'any',
        value: c.allowable_fs ?? 1.2,
        oninput: ev => { c.allowable_fs = num(ev.target.value); sync(); }})),
      el('td', null, el('select', {onchange: ev => {
          c.method = ev.target.value; sync(); }},
        el('option', {value: 'fellenius',
          selected: c.method !== 'bishop'}, 'フェレニウス'),
        el('option', {value: 'bishop',
          selected: c.method === 'bishop'}, 'ビショップ'))),
      el('td', null, el('input', {type: 'checkbox',
        checked: !!c.consider_liquefaction,
        onchange: ev => {
          if (ev.target.checked) c.consider_liquefaction = true;
          else delete c.consider_liquefaction;
          sync();
        }})),
      el('td', null, el('input', {type: 'checkbox', checked: !!c.newmark,
        onchange: ev => {
          if (ev.target.checked) c.newmark = true; else delete c.newmark;
          renderForm(); sync();
        }})),
      el('td', null, c.newmark ? el('input', {type: 'number', step: 'any',
        value: c.allowable_displacement ?? 0.5,
        oninput: ev => { c.allowable_displacement = num(ev.target.value); sync(); }})
        : '—'),
      el('td', null, el('button', {class: 'mini del', onclick: () => {
        state.cases.splice(i, 1); renderForm(); sync();
      }}, '×'))));
  });
  bodyC.append(tbl);
  bodyC.append(el('button', {class: 'mini', onclick: () => {
    state.cases.push({name: 'ケース', kh: 0.0, allowable_fs: 1.2,
                      method: 'fellenius'});
    renderForm(); sync();
  }}, '＋ ケースを追加'));
  dCases.append(bodyC);
  sheet.append(dCases);

  /* --- 探索設定 --- */
  const dGrid = el('details', {class: 'sec'},
    el('summary', null, '探索設定（すべり円）'));
  const bodyG = el('div', {class: 'secbody'});
  const g = state.grid = state.grid || {};
  function gOpt(label, key) {
    return optNumField(label, g[key], v => {
      if (v === null) delete g[key]; else g[key] = v;
    });
  }
  bodyG.append(el('p', {class: 'hint'}, '空欄は断面から自動設定。'));
  bodyG.append(el('div', {class: 'row'},
    gOpt('分割数', 'n_slices'), gOpt('中心x分割', 'nx'),
    gOpt('中心y分割', 'ny'), gOpt('接線分割', 'nr')));
  bodyG.append(el('div', {class: 'hint'}, '拘束条件（空欄は制約なし）'));
  bodyG.append(el('div', {class: 'row'},
    gOpt('下限標高', 'y_lower_limit'),
    gOpt('始端x最小', 'x_entry_min'), gOpt('始端x最大', 'x_entry_max'),
    gOpt('終端x最小', 'x_exit_min'), gOpt('終端x最大', 'x_exit_max')));
  dGrid.append(bodyG);
  sheet.append(dGrid);

  /* --- 高度な設定の注記 --- */
  const extras = [];
  if (state.countermeasures) extras.push('対策工');
  if (state.sensitivity) extras.push('感度分析');
  if (state.accel_series) extras.push('加速度波形');
  if (extras.length) {
    sheet.append(el('p', {class: 'hint'},
      `※ ${extras.join('・')} が定義されています（編集は JSON タブで）。`));
  } else {
    sheet.append(el('p', {class: 'hint'},
      '※ 対策工・感度分析・加速度波形など高度な設定は JSON タブで編集できます。'));
  }
}

/* ---------- 同期・プレビュー ---------- */
let timer = null;
function sync() {
  editor.value = JSON.stringify(state, null, 2);
  clearTimeout(timer);
  timer = setTimeout(updatePreview, 500);
}

async function updatePreview() {
  try {
    const res = await fetch('/api/preview', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({input: state})
    });
    const data = await res.json();
    if (data.error) { setMsg(data.error, true); return; }
    preview.innerHTML = data.svg;
    if (data.warnings && data.warnings.length) {
      setMsg('⚠ ' + data.warnings.join(' ／ '), true);
    } else {
      setMsg('プレビュー更新', false);
    }
  } catch (e) { setMsg('通信エラー: ' + e, true); }
}

/* JSON タブでの手編集 */
editor.addEventListener('input', () => {
  clearTimeout(timer);
  timer = setTimeout(() => {
    try { state = JSON.parse(editor.value); }
    catch (e) { setMsg('JSON 構文エラー: ' + e.message, true); return; }
    updatePreview();
  }, 600);
});

/* タブ切替 */
function activate(tab) {
  activeTab = tab;
  tabSheet.classList.toggle('active', tab === 'sheet');
  tabJson.classList.toggle('active', tab === 'json');
  sheet.classList.toggle('active', tab === 'sheet');
  jsonwrap.classList.toggle('active', tab === 'json');
  if (tab === 'sheet') {
    try { state = JSON.parse(editor.value); }
    catch (e) { setMsg('JSON 構文エラーのため直前の状態を表示します', true); }
    renderForm();
  } else {
    editor.value = JSON.stringify(state, null, 2);
  }
}
tabSheet.addEventListener('click', () => activate('sheet'));
tabJson.addEventListener('click', () => activate('json'));

/* 実行 */
runBtn.addEventListener('click', async () => {
  if (activeTab === 'json') {
    try { state = JSON.parse(editor.value); }
    catch (e) { setMsg('JSON 構文エラー: ' + e.message, true); return; }
  }
  runBtn.disabled = true;
  setMsg('照査を実行中…', false);
  try {
    const res = await fetch('/api/analyze', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({input: state,
        sensitivity: document.getElementById('sens').checked})
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

/* 読込・保存 */
document.getElementById('load').addEventListener('click', () =>
  document.getElementById('file').click());
document.getElementById('file').addEventListener('change', ev => {
  const f = ev.target.files[0];
  if (!f) return;
  const r = new FileReader();
  r.onload = () => {
    try { state = JSON.parse(r.result); }
    catch (e) { setMsg('読込んだファイルが JSON として解釈できません', true); return; }
    editor.value = JSON.stringify(state, null, 2);
    if (activeTab === 'sheet') renderForm();
    updatePreview();
  };
  r.readAsText(f);
});
document.getElementById('save').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify(state, null, 2)],
                       {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'teibo_input.json';
  a.click();
  URL.revokeObjectURL(a.href);
});

renderForm();
updatePreview();
</script>
</body>
</html>
"""
