"""複数断面の一括照査（バッチ処理）。

距離標ごとの断面入力 JSON をまとめて照査し、縦断方向の最小安全率
一覧（テキスト / CSV / HTML+縦断グラフ）を出力する。

各入力 JSON にはトップレベルで次を指定できる（省略可）:
    "station":  距離標の表示名（例 "0k200"）。省略時はファイル名。
    "distance": 縦断方向の累積距離 (m)。全断面で指定されている場合は
                この値でソートし、縦断グラフの横軸に用いる。
"""

from __future__ import annotations

import html as _html
import os
from dataclasses import dataclass, field
from typing import List, Optional

from .diagnostics import validate_input
from .io_json import load_input
from .model import AnalysisInput
from .search import CaseResult, run_all


@dataclass
class BatchEntry:
    """1断面ぶんの照査結果。"""

    path: str
    station: str
    distance: Optional[float]
    data: AnalysisInput
    results: List[CaseResult]
    warnings: List[str] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(r.ok for r in self.results)


def run_batch(paths: List[str]) -> List[BatchEntry]:
    """複数の入力ファイルを順に照査する。"""
    entries: List[BatchEntry] = []
    for p in paths:
        data = load_input(p)
        warnings = validate_input(data)
        results = run_all(data.section, data.cases, data.grid)
        station = data.station or os.path.splitext(os.path.basename(p))[0]
        entries.append(
            BatchEntry(
                path=p,
                station=station,
                distance=data.distance,
                data=data,
                results=results,
                warnings=warnings,
            )
        )
    if entries and all(e.distance is not None for e in entries):
        entries.sort(key=lambda e: e.distance)
    return entries


def _case_names(entries: List[BatchEntry]) -> List[str]:
    """全断面のケース名の順序付き和集合。"""
    names: List[str] = []
    for e in entries:
        for r in e.results:
            if r.case.name not in names:
                names.append(r.case.name)
    return names


def _result_for(entry: BatchEntry, name: str) -> Optional[CaseResult]:
    for r in entry.results:
        if r.case.name == name:
            return r
    return None


def batch_text_report(entries: List[BatchEntry]) -> str:
    """縦断方向の Fs 一覧（テキスト）。"""
    names = _case_names(entries)
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append(" 複数断面一括照査 : 縦断方向の最小安全率一覧")
    lines.append("=" * 72)
    header = f"  {'距離標':<10}{'距離(m)':>9} |" + "".join(f"{n:>14}" for n in names)
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for e in entries:
        dist = f"{e.distance:.1f}" if e.distance is not None else "—"
        cells = []
        for n in names:
            r = _result_for(e, n)
            if r is None or r.critical is None:
                cells.append(f"{'—':>14}")
            else:
                mark = "○" if r.ok else "×"
                cells.append(f"{f'{r.critical.fs:.3f} {mark}':>14}")
        lines.append(f"  {e.station:<10}{dist:>9} |" + "".join(cells))
    # ケースごとの最小値
    lines.append("  " + "-" * (len(header) - 2))
    mins = []
    for n in names:
        vals = [
            (_result_for(e, n).critical.fs, e.station)
            for e in entries
            if _result_for(e, n) and _result_for(e, n).critical
        ]
        if vals:
            fs, st = min(vals)
            mins.append(f"{f'{fs:.3f}@{st}':>14}")
        else:
            mins.append(f"{'—':>14}")
    lines.append(f"  {'最小':<10}{'':>9} |" + "".join(mins))
    ng = [e.station for e in entries if not e.all_ok]
    if ng:
        lines.append(f"  NG 断面: {', '.join(ng)}")
    else:
        lines.append("  全断面 OK")
    warn_count = sum(len(e.warnings) for e in entries)
    if warn_count:
        lines.append(f"  ⚠ 入力診断の警告が {warn_count} 件あります（各断面のレポート参照）")
    lines.append("=" * 72)
    return "\n".join(lines)


def batch_csv(entries: List[BatchEntry]) -> str:
    """CSV（BOM なし UTF-8 想定）。"""
    names = _case_names(entries)
    cols = ["station", "distance"]
    for n in names:
        cols += [f"{n}_Fs", f"{n}_判定"]
    rows = [",".join(cols)]
    for e in entries:
        row = [e.station, "" if e.distance is None else f"{e.distance:g}"]
        for n in names:
            r = _result_for(e, n)
            if r is None or r.critical is None:
                row += ["", "解析不能" if r else ""]
            else:
                row += [f"{r.critical.fs:.4f}", r.judgement]
        rows.append(",".join(row))
    return "\n".join(rows) + "\n"


# ---------------------------------------------------------------------------
# HTML レポート（縦断グラフつき）
# ---------------------------------------------------------------------------

def _profile_chart(entries: List[BatchEntry], names: List[str]) -> str:
    """縦断方向の Fs 折れ線グラフ（SVG）。"""
    w, h = 900, 330
    pad_l, pad_r, pad_t, pad_b = 56, 26, 16, 46

    have_dist = all(e.distance is not None for e in entries)
    xs_val = [e.distance if have_dist else i for i, e in enumerate(entries)]
    x0, x1 = min(xs_val), max(xs_val)
    if x1 <= x0:
        x1 = x0 + 1.0

    fs_all = [
        r.critical.fs
        for e in entries
        for r in e.results
        if r.critical is not None
    ] + [r.case.allowable_fs for e in entries for r in e.results]
    ymax = max(fs_all + [1.0]) * 1.15

    def sx(v: float) -> float:
        return pad_l + (v - x0) / (x1 - x0) * (w - pad_l - pad_r)

    def sy(v: float) -> float:
        return h - pad_b - v / ymax * (h - pad_t - pad_b)

    p: List[str] = []
    p.append(
        f"<svg viewBox='0 0 {w} {h}' width='100%' class='chart' role='img' "
        f"aria-label='縦断方向の最小安全率'>"
    )
    # 水平グリッド（0.5 刻み・控えめ）
    gy = 0.0
    while gy <= ymax + 1e-9:
        yy = sy(gy)
        p.append(
            f"<line x1='{pad_l}' y1='{yy:.1f}' x2='{w - pad_r}' y2='{yy:.1f}' "
            f"class='grid'/>"
        )
        p.append(
            f"<text x='{pad_l - 8}' y='{yy + 3.5:.1f}' class='tick' "
            f"text-anchor='end'>{gy:.1f}</text>"
        )
        gy += 0.5
    # x 軸ラベル（距離標）
    for e, xv in zip(entries, xs_val):
        p.append(
            f"<text x='{sx(xv):.1f}' y='{h - pad_b + 16}' class='tick' "
            f"text-anchor='middle'>{_html.escape(e.station)}</text>"
        )
    if have_dist:
        p.append(
            f"<text x='{(pad_l + w - pad_r) / 2:.0f}' y='{h - 6}' class='tick' "
            f"text-anchor='middle'>距離 (m)</text>"
        )
    p.append(
        f"<text x='14' y='{(pad_t + h - pad_b) / 2:.0f}' class='tick' "
        f"text-anchor='middle' transform='rotate(-90 14 {(pad_t + h - pad_b) / 2:.0f})'>Fs</text>"
    )
    # 軸線
    p.append(
        f"<line x1='{pad_l}' y1='{sy(0):.1f}' x2='{w - pad_r}' y2='{sy(0):.1f}' class='axis'/>"
    )

    # 系列（ケース）ごと: 必要安全率の破線 → 折れ線 → マーカー
    for si, n in enumerate(names):
        cls = f"s{si % 4}"
        fsa_vals = {
            _result_for(e, n).case.allowable_fs
            for e in entries
            if _result_for(e, n)
        }
        for fsa in fsa_vals:
            yy = sy(fsa)
            p.append(
                f"<line x1='{pad_l}' y1='{yy:.1f}' x2='{w - pad_r}' y2='{yy:.1f}' "
                f"class='fsa {cls}'/>"
            )
            p.append(
                f"<text x='{w - pad_r - 2}' y='{yy - 4:.1f}' class='tick' "
                f"text-anchor='end'>Fsa={fsa:g}（{_html.escape(n)}）</text>"
            )
        pts = []
        for e, xv in zip(entries, xs_val):
            r = _result_for(e, n)
            if r is None or r.critical is None:
                continue
            pts.append((sx(xv), sy(r.critical.fs), e, r))
        if not pts:
            continue
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in pts)
        p.append(f"<polyline points='{line}' class='series {cls}'/>")
        for x, y, e, r in pts:
            p.append(
                f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4' class='marker {cls}'>"
                f"<title>{_html.escape(e.station)} {_html.escape(n)}: "
                f"Fs={r.critical.fs:.3f}（{r.judgement}）</title></circle>"
            )
    p.append("</svg>")
    return "".join(p)


_BATCH_CSS = """
  :root {
    --s0: #2f6fa8; --s1: #a05510; --s2: #7b3fbf; --s3: #0f8a55;
  }
  @media (prefers-color-scheme: dark) {
    :root { --s0: #4a90c9; --s1: #c9821f; --s2: #9c6ad4; --s3: #1fa568; }
  }
  svg.chart { border: 1px solid #ccc; background: #fbfaf6; border-radius: 4px; }
  svg.chart .grid { stroke: currentColor; stroke-opacity: 0.08; }
  svg.chart .axis { stroke: currentColor; stroke-opacity: 0.45; }
  svg.chart .tick { font-size: 10.5px; fill: currentColor; fill-opacity: 0.65; }
  svg.chart .series { fill: none; stroke-width: 2; }
  svg.chart .marker { stroke: #fbfaf6; stroke-width: 2; }
  svg.chart .fsa { stroke-dasharray: 5,4; stroke-width: 1.2; stroke-opacity: 0.65; }
  svg.chart .s0 { stroke: var(--s0); } svg.chart circle.s0 { fill: var(--s0); }
  svg.chart .s1 { stroke: var(--s1); } svg.chart circle.s1 { fill: var(--s1); }
  svg.chart .s2 { stroke: var(--s2); } svg.chart circle.s2 { fill: var(--s2); }
  svg.chart .s3 { stroke: var(--s3); } svg.chart circle.s3 { fill: var(--s3); }
  .legend { display: flex; gap: 18px; flex-wrap: wrap; margin: 8px 0 4px;
            font-size: 0.85rem; }
  .legend .sw { display: inline-block; width: 16px; height: 3px; border-radius: 2px;
                vertical-align: middle; margin-right: 6px; }
  @media (prefers-color-scheme: dark) {
    svg.chart { background: #262620; border-color: #555; }
    svg.chart .marker { stroke: #262620; }
  }
"""


def batch_html_report(entries: List[BatchEntry], details: bool = False) -> str:
    """HTML レポート（縦断グラフ＋一覧表、必要なら断面別詳細）。"""
    from .report import _HTML_TEMPLATE, _make_transform, _svg_for_case
    from .search import section_for_case

    names = _case_names(entries)
    parts: List[str] = []
    parts.append("<h1>複数断面一括照査レポート</h1>")
    parts.append(f"<p class='sub'>断面数: {len(entries)}</p>")

    parts.append("<h2>縦断方向の最小安全率</h2>")
    legend = "".join(
        f"<span><span class='sw' style='background: var(--s{i % 4})'></span>"
        f"{_html.escape(n)}</span>"
        for i, n in enumerate(names)
    )
    parts.append(f"<div class='legend'>{legend}</div>")
    parts.append(_profile_chart(entries, names))

    parts.append("<h2>一覧表</h2>")
    parts.append("<table class='result'>")
    head = "".join(f"<th>{_html.escape(n)}</th>" for n in names)
    parts.append(f"<tr><th>距離標</th><th>距離 (m)</th>{head}<th>総合</th></tr>")
    for e in entries:
        dist = f"{e.distance:g}" if e.distance is not None else "—"
        cells = []
        for n in names:
            r = _result_for(e, n)
            if r is None or r.critical is None:
                cells.append("<td>—</td>")
            else:
                cls = "ok" if r.ok else "ng"
                cells.append(
                    f"<td>{r.critical.fs:.3f} <span class='{cls}'>{r.judgement}</span></td>"
                )
        total = "ok" if e.all_ok else "ng"
        total_txt = "OK" if e.all_ok else "NG"
        parts.append(
            f"<tr><td>{_html.escape(e.station)}</td><td>{dist}</td>"
            f"{''.join(cells)}<td class='{total}'>{total_txt}</td></tr>"
        )
    parts.append("</table>")

    if details:
        parts.append("<h2>断面別詳細</h2>")
        for e in entries:
            parts.append(f"<h3>{_html.escape(e.station)}　{_html.escape(e.data.section.name)}</h3>")
            if e.warnings:
                parts.append(
                    "<ul>" + "".join(f"<li>⚠ {_html.escape(wmsg)}</li>" for wmsg in e.warnings) + "</ul>"
                )
            sx, sy, poly, w, h = _make_transform(e.data.section, e.results)
            for r in e.results:
                if r.critical:
                    parts.append(
                        f"<p class='cinfo'>{_html.escape(r.case.name)}: "
                        f"Fs={r.critical.fs:.3f}（{r.judgement}）　"
                        f"中心 (x={r.critical.xc:.2f}, y={r.critical.yc:.2f}) "
                        f"R={r.critical.r:.2f} m</p>"
                    )
                sec_c = section_for_case(e.data.section, r.case)
                parts.append(_svg_for_case(sec_c, r, sx, sy, poly, w, h))

    body = "\n".join(parts)
    html_out = _HTML_TEMPLATE.replace("{{BODY}}", body)
    # 縦断グラフ用の CSS を差し込む
    return html_out.replace("<style>", "<style>" + _BATCH_CSS, 1)
