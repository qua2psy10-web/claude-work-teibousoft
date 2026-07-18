"""照査結果のレポート生成（テキスト / HTML+SVG）。"""

from __future__ import annotations

import html
import math
from typing import List, Optional, Tuple

from .model import Section
from .search import CaseResult
from .stability import CircleResult


def text_report(section: Section, results: List[CaseResult]) -> str:
    """コンソール向けテキストレポート。"""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append(f" 堤防安定性照査結果 : {section.name}")
    lines.append("=" * 60)

    lines.append("\n【土層条件】")
    lines.append(
        f"  {'層名':<12}{'γt':>7}{'γsat':>8}{'c':>7}{'φ':>7}"
    )
    lines.append(
        f"  {'':<12}{'kN/m3':>7}{'kN/m3':>8}{'kN/m2':>7}{'度':>7}"
    )
    for ly in section.layers:
        lines.append(
            f"  {ly.name:<12}{ly.gamma:>7.1f}{ly.gamma_sat:>8.1f}"
            f"{ly.c:>7.1f}{ly.phi:>7.1f}"
        )
    if section.phreatic:
        lines.append("  浸潤線: 設定あり")
    else:
        lines.append("  浸潤線: なし（乾燥状態）")

    lines.append("\n【照査結果】")
    for r in results:
        lines.append("-" * 60)
        c = r.case
        method = "修正フェレニウス法" if c.method == "fellenius" else "簡易ビショップ法"
        lines.append(f"  ケース   : {c.name}")
        lines.append(f"  解析法   : {method}")
        lines.append(f"  水平震度 : kh = {c.kh:.3f}")
        lines.append(f"  必要安全率: Fsa = {c.allowable_fs:.2f}")
        if r.critical is None:
            lines.append("  結果     : 有効なすべり円が見つかりませんでした")
            continue
        cr = r.critical
        lines.append(
            f"  臨界円   : 中心(x={cr.xc:.2f}, y={cr.yc:.2f}), R={cr.r:.2f} m"
        )
        lines.append(f"  最小安全率: Fs = {cr.fs:.3f}")
        mark = "○ OK" if r.ok else "× NG"
        lines.append(f"  判定     : Fs={cr.fs:.3f} {'>=' if r.ok else '<'} Fsa={c.allowable_fs:.2f}  → {mark}")
        lines.append(f"  （評価円数: {r.evaluated}）")
    lines.append("=" * 60)
    return "\n".join(lines)


def _bounds(section: Section) -> Tuple[float, float, float, float]:
    xs: List[float] = []
    ys: List[float] = []
    for ly in section.layers:
        for p in ly.top:
            xs.append(p.x)
            ys.append(p.y)
    if section.phreatic:
        for p in section.phreatic.points:
            xs.append(p.x)
            ys.append(p.y)
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    # 下方に余白（最下層を描画するため）
    ymin -= (ymax - ymin) * 0.6 + 2.0
    return xmin, xmax, ymin, ymax


def html_report(section: Section, results: List[CaseResult]) -> str:
    """HTML レポート（SVG 断面図つき）。"""
    xmin, xmax, ymin, ymax = _bounds(section)
    # 臨界円が枠外に出る場合は拡張
    for r in results:
        if r.critical:
            cr = r.critical
            ymax = max(ymax, cr.yc + 0.5)

    pad = 40
    w = 900
    span_x = xmax - xmin if xmax > xmin else 1.0
    span_y = ymax - ymin if ymax > ymin else 1.0
    scale = (w - 2 * pad) / span_x
    h = int(span_y * scale + 2 * pad)

    def sx(x: float) -> float:
        return pad + (x - xmin) * scale

    def sy(y: float) -> float:
        return h - pad - (y - ymin) * scale

    def poly(points, closed=False) -> str:
        pts = " ".join(f"{sx(p.x):.1f},{sy(p.y):.1f}" for p in points)
        return pts

    svgs: List[str] = []
    for r in results:
        svgs.append(_svg_for_case(section, r, sx, sy, poly, w, h))

    # HTML 組み立て
    parts: List[str] = []
    parts.append("<!-- teibo stability report -->")
    parts.append(f"<h1>堤防安定性照査レポート</h1>")
    parts.append(f"<p class='sub'>断面: {html.escape(section.name)}</p>")

    # 土層表
    parts.append("<h2>土層条件</h2>")
    parts.append("<table class='soil'>")
    parts.append(
        "<tr><th>層名</th><th>γt (kN/m³)</th><th>γsat (kN/m³)</th>"
        "<th>c (kN/m²)</th><th>φ (°)</th></tr>"
    )
    for ly in section.layers:
        parts.append(
            f"<tr><td>{html.escape(ly.name)}</td><td>{ly.gamma:.1f}</td>"
            f"<td>{ly.gamma_sat:.1f}</td><td>{ly.c:.1f}</td>"
            f"<td>{ly.phi:.1f}</td></tr>"
        )
    parts.append("</table>")

    # 照査サマリ
    parts.append("<h2>照査結果一覧</h2>")
    parts.append("<table class='result'>")
    parts.append(
        "<tr><th>ケース</th><th>解析法</th><th>kh</th>"
        "<th>Fs</th><th>Fsa</th><th>判定</th></tr>"
    )
    for r in results:
        c = r.case
        method = "修正フェレニウス法" if c.method == "fellenius" else "簡易ビショップ法"
        fs = f"{r.critical.fs:.3f}" if r.critical else "—"
        cls = "ok" if r.ok else "ng"
        badge = "OK" if r.ok else "NG"
        parts.append(
            f"<tr><td>{html.escape(c.name)}</td><td>{method}</td>"
            f"<td>{c.kh:.3f}</td><td>{fs}</td><td>{c.allowable_fs:.2f}</td>"
            f"<td class='{cls}'>{badge}</td></tr>"
        )
    parts.append("</table>")

    # 各ケース図
    parts.append("<h2>臨界すべり円</h2>")
    for r, svg in zip(results, svgs):
        c = r.case
        parts.append(f"<h3>{html.escape(c.name)}</h3>")
        if r.critical:
            cr = r.critical
            parts.append(
                f"<p class='cinfo'>中心 (x={cr.xc:.2f}, y={cr.yc:.2f})　"
                f"半径 R={cr.r:.2f} m　最小安全率 Fs={cr.fs:.3f}</p>"
            )
        parts.append(svg)

    body = "\n".join(parts)
    return _HTML_TEMPLATE.replace("{{BODY}}", body)


def _svg_for_case(section, result: CaseResult, sx, sy, poly, w, h) -> str:
    elems: List[str] = []
    elems.append(
        f"<svg viewBox='0 0 {w} {h}' width='100%' "
        f"preserveAspectRatio='xMidYMid meet' class='section'>"
    )

    # 土層塗り（最上層のみ簡易的に地表面下を塗る）
    surf = section.surface
    # 地表面ポリゴン（下辺は枠下端まで）
    ground_pts = f"{poly(surf)} {sx(surf[-1].x):.1f},{h - 40:.1f} {sx(surf[0].x):.1f},{h - 40:.1f}"
    elems.append(
        f"<polygon points='{ground_pts}' fill='#e8dcc0' stroke='none'/>"
    )

    # 層境界線
    colors = ["#8a6d3b", "#6d8a3b", "#3b6d8a", "#8a3b6d"]
    for i, ly in enumerate(section.layers):
        col = colors[i % len(colors)]
        elems.append(
            f"<polyline points='{poly(ly.top)}' fill='none' "
            f"stroke='{col}' stroke-width='1.5'/>"
        )

    # 地表面（太線）
    elems.append(
        f"<polyline points='{poly(surf)}' fill='none' "
        f"stroke='#5a4a2a' stroke-width='2.5'/>"
    )

    # 浸潤線
    if section.phreatic:
        elems.append(
            f"<polyline points='{poly(section.phreatic.points)}' fill='none' "
            f"stroke='#1e73c8' stroke-width='2' stroke-dasharray='6,4'/>"
        )
        # 水位マーク
        p0 = section.phreatic.points[0]
        elems.append(
            f"<text x='{sx(p0.x)+4:.1f}' y='{sy(p0.y)-4:.1f}' "
            f"class='wlbl'>浸潤線</text>"
        )

    cr: Optional[CircleResult] = result.critical
    if cr is not None:
        cx, cy, r = sx(cr.xc), sy(cr.yc), cr.r
        rpx = r * (sx(cr.xc + 1) - sx(cr.xc))  # 半径のピクセル換算
        # すべり円弧（土塊部分のみ）
        if cr.slices:
            xl = cr.slices[0].x_mid - cr.slices[0].width / 2
            xr = cr.slices[-1].x_mid + cr.slices[-1].width / 2
            arc_pts = []
            n = 60
            for k in range(n + 1):
                xx = xl + (xr - xl) * k / n
                dx = xx - cr.xc
                if abs(dx) > cr.r:
                    continue
                yy = cr.yc - math.sqrt(cr.r * cr.r - dx * dx)
                arc_pts.append(f"{sx(xx):.1f},{sy(yy):.1f}")
            elems.append(
                f"<polyline points='{' '.join(arc_pts)}' fill='none' "
                f"stroke='#c0392b' stroke-width='2.5'/>"
            )
            # スライス境界（薄線）
            from .geometry import surface_y

            for s in cr.slices[:: max(1, len(cr.slices) // 20)]:
                x0 = s.x_mid
                dx = x0 - cr.xc
                if abs(dx) <= cr.r:
                    ya = cr.yc - math.sqrt(cr.r * cr.r - dx * dx)
                    ysf = surface_y(section, x0)
                    if ysf is not None:
                        elems.append(
                            f"<line x1='{sx(x0):.1f}' y1='{sy(ysf):.1f}' "
                            f"x2='{sx(x0):.1f}' y2='{sy(ya):.1f}' "
                            f"stroke='#c0392b' stroke-width='0.4' opacity='0.5'/>"
                        )
        # 中心点
        elems.append(
            f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='3' fill='#c0392b'/>"
        )
        # Fs ラベル
        color = "#1a7f37" if result.ok else "#c0392b"
        elems.append(
            f"<text x='{cx:.1f}' y='{cy-8:.1f}' class='fslbl' "
            f"fill='{color}'>Fs={cr.fs:.3f} ({result.judgement})</text>"
        )

    elems.append("</svg>")
    return "".join(elems)


_HTML_TEMPLATE = """<style>
  :root { color-scheme: light dark; }
  body { font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic", Meiryo, sans-serif;
         margin: 0 auto; max-width: 960px; padding: 24px; line-height: 1.6; }
  h1 { font-size: 1.5rem; border-bottom: 3px solid #c0392b; padding-bottom: 8px; }
  h2 { font-size: 1.2rem; margin-top: 1.8em; border-left: 5px solid #5a4a2a; padding-left: 10px; }
  h3 { font-size: 1.05rem; margin-top: 1.2em; }
  .sub { color: #666; margin-top: -6px; }
  table { border-collapse: collapse; width: 100%; margin: 8px 0 16px; font-size: 0.95rem; }
  th, td { border: 1px solid #bbb; padding: 6px 10px; text-align: center; }
  th { background: #efe7d4; }
  td.ok { color: #1a7f37; font-weight: bold; }
  td.ng { color: #c0392b; font-weight: bold; }
  .cinfo { background: #f6f2e8; padding: 6px 10px; border-radius: 4px; font-size: 0.92rem; }
  svg.section { border: 1px solid #ccc; background: #fbfaf6; border-radius: 4px; }
  text { font-size: 12px; font-family: sans-serif; }
  text.fslbl { font-size: 13px; font-weight: bold; }
  text.wlbl { font-size: 11px; fill: #1e73c8; }
  @media (prefers-color-scheme: dark) {
    body { background: #1c1c1e; color: #e6e6e6; }
    th { background: #3a3320; }
    svg.section { background: #262620; }
    .cinfo { background: #2a2a24; }
    th, td { border-color: #555; }
  }
</style>
{{BODY}}
"""
