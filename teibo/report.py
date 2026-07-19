"""照査結果のレポート生成（テキスト / HTML+SVG）。"""

from __future__ import annotations

import html
import math
from typing import List, Optional, Tuple

from .countermeasure import CountermeasureResult
from .model import Section
from .newmark import NewmarkResult
from .search import CaseResult, section_for_case
from .sensitivity import SensitivityResult
from .stability import CircleResult


def _min_fl(cr: Optional[CircleResult]) -> Optional[float]:
    """臨界円のスライスのうち液状化判定対象の最小 FL。"""
    if cr is None:
        return None
    fls = [s.fl for s in cr.slices if s.fl is not None]
    return min(fls) if fls else None


def text_report(
    section: Section,
    results: List[CaseResult],
    newmark: Optional[List[NewmarkResult]] = None,
    countermeasures: Optional[List[CountermeasureResult]] = None,
    warnings: Optional[List[str]] = None,
) -> str:
    """コンソール向けテキストレポート。"""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append(f" 堤防安定性照査結果 : {section.name}")
    lines.append("=" * 60)

    if warnings:
        lines.append("\n【入力診断】")
        for w in warnings:
            lines.append(f"  ⚠ {w}")

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
        note = "（カサグランデ基本放物線による自動推定）" if section.phreatic_estimated else ""
        lines.append(f"  浸潤線: 設定あり{note}")
    else:
        lines.append("  浸潤線: なし（乾燥状態）")
    if section.external_water:
        lines.append("  外水位: 設定あり")
    if section.surcharges:
        lines.append("\n【上載荷重】")
        for sc in section.surcharges:
            lines.append(
                f"  {sc.name}: x={sc.x_start:.2f}〜{sc.x_end:.2f} m, "
                f"q={sc.q:.1f} kN/m2"
            )
    if section.tension_crack:
        tc = section.tension_crack
        lines.append(
            f"  テンションクラック: 深さ zc={tc.depth:.2f} m, "
            f"水深 zw={tc.water_depth:.2f} m"
        )

    lines.append("\n【照査結果】")
    for r in results:
        lines.append("-" * 60)
        c = r.case
        method = "修正フェレニウス法" if c.method == "fellenius" else "簡易ビショップ法"
        lines.append(f"  ケース   : {c.name}")
        lines.append(f"  解析法   : {method}")
        lines.append(f"  水平震度 : kh = {c.kh:.3f}")
        if c.phreatic is not None:
            lines.append("  浸潤線   : ケース専用の浸潤線を使用（水位急降下等）")
        if c.external_water is not None:
            note = "外水なし" if not c.external_water else "ケース専用の外水位"
            lines.append(f"  外水位   : {note}")
        if c.consider_liquefaction:
            mfl = _min_fl(r.critical)
            fl_txt = f"最小 FL = {mfl:.3f}" if mfl is not None else "判定対象なし"
            lines.append(f"  液状化   : FL 法で考慮（{fl_txt}）")
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

    if newmark:
        lines.append("\n【ニューマーク法（滑動変位量）】")
        for nm in newmark:
            lines.append("-" * 60)
            lines.append(f"  ケース   : {nm.case.name}")
            if nm.ky is None:
                lines.append("  結果     : 降伏震度を算定できませんでした")
                continue
            lines.append(f"  降伏震度 : ky = {nm.ky:.3f}（設計震度 kh = {nm.kmax:.3f}）")
            method = "加速度波形の時刻歴積分" if nm.used_time_history else "経験式 (Ambraseys & Menu)"
            if nm.displacement is None:
                if nm.ky <= 0.0:
                    lines.append(
                        "  変位量   : 算定不能"
                        "（ky=0: 震度によらず Fs≤1 のため剛体ブロック法の適用外。"
                        "流動的破壊のおそれ）"
                    )
                else:
                    lines.append(f"  変位量   : 算定不能（{method}）")
                continue
            lines.append(f"  変位量   : D = {nm.displacement*100:.1f} cm（{method}）")
            mark = "○ OK" if nm.ok else "× NG"
            lines.append(
                f"  判定     : D={nm.displacement*100:.1f} cm "
                f"{'<=' if nm.ok else '>'} Da={nm.allowable*100:.0f} cm  → {mark}"
            )

    if countermeasures:
        lines.append("\n【対策工の比較】")
        names = ["無対策"] + [c.countermeasure.name for c in countermeasures]
        header = f"  {'ケース':<14}|" + "".join(f"{n:>16}" for n in names)
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for i, r in enumerate(results):
            cells = []
            for res_set in [results] + [c.results for c in countermeasures]:
                rr = res_set[i]
                if rr.critical is None:
                    cells.append(f"{'—':>16}")
                else:
                    mark = "○" if rr.ok else "×"
                    cells.append(f"{f'{rr.critical.fs:.3f} {mark}':>16}")
            lines.append(f"  {r.case.name:<14}|" + "".join(cells))
        for c in countermeasures:
            judge = "全ケース OK" if c.all_ok else "NG ケースあり"
            lines.append(f"  → {c.countermeasure.name}: {judge}")

    lines.append("=" * 60)
    return "\n".join(lines)


def sensitivity_text_report(sens: List[SensitivityResult]) -> str:
    """感度分析結果のテキストレポート。"""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append(" 感度分析結果")
    lines.append("=" * 60)
    for res in sens:
        t = res.target
        lines.append(f"\n【{t.layer} の {res.param_label}】")
        header = f"  {'値':>10} |" + "".join(
            f"{name:>12}" for name in res.case_names
        )
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for row in res.rows:
            cells = "".join(
                f"{('%.3f' % fs) if fs is not None else '—':>12}"
                for fs in row.fs_by_case
            )
            lines.append(f"  {row.value:>10.2f} |{cells}")
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
    if section.external_water:
        for p in section.external_water:
            xs.append(p.x)
            ys.append(p.y)
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    # 下方に余白（最下層を描画するため）
    ymin -= (ymax - ymin) * 0.6 + 2.0
    return xmin, xmax, ymin, ymax


def _make_transform(section: Section, results: List[CaseResult]):
    """断面→SVG 座標変換（sx, sy, poly, w, h）を組み立てる。"""
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

    def poly(points) -> str:
        return " ".join(f"{sx(p.x):.1f},{sy(p.y):.1f}" for p in points)

    return sx, sy, poly, w, h


def section_svg(section: Section) -> str:
    """解析結果なしの断面プレビュー SVG（GUI 用）。"""
    sx, sy, poly, w, h = _make_transform(section, [])
    return _svg_for_case(section, None, sx, sy, poly, w, h)


def html_report(
    section: Section,
    results: List[CaseResult],
    sensitivity: Optional[List[SensitivityResult]] = None,
    newmark: Optional[List[NewmarkResult]] = None,
    countermeasures: Optional[List[CountermeasureResult]] = None,
    warnings: Optional[List[str]] = None,
) -> str:
    """HTML レポート（SVG 断面図つき）。"""
    sx, sy, poly, w, h = _make_transform(section, results)

    svgs: List[str] = []
    for r in results:
        # ケース専用の浸潤線（水位急降下時など）を反映した断面で描画
        sec_c = section_for_case(section, r.case)
        svgs.append(_svg_for_case(sec_c, r, sx, sy, poly, w, h))

    # HTML 組み立て
    parts: List[str] = []
    parts.append("<!-- teibo stability report -->")
    parts.append(f"<h1>堤防安定性照査レポート</h1>")
    parts.append(f"<p class='sub'>断面: {html.escape(section.name)}</p>")

    if warnings:
        parts.append("<div class='warnbox'><strong>入力診断（警告）</strong><ul>")
        for wmsg in warnings:
            parts.append(f"<li>{html.escape(wmsg)}</li>")
        parts.append("</ul></div>")

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

    # 荷重・水条件
    notes: List[str] = []
    if section.phreatic:
        if section.phreatic_estimated:
            notes.append("浸潤線: カサグランデ基本放物線による自動推定")
        else:
            notes.append("浸潤線: 入力値")
    else:
        notes.append("浸潤線: なし（乾燥状態）")
    if section.external_water:
        notes.append("外水位: 設定あり（水重・間隙水圧に考慮）")
    for sc in section.surcharges:
        notes.append(
            f"{html.escape(sc.name)}: x={sc.x_start:.2f}〜{sc.x_end:.2f} m, "
            f"q={sc.q:.1f} kN/m²"
        )
    if section.tension_crack:
        tc = section.tension_crack
        notes.append(
            f"テンションクラック: 深さ zc={tc.depth:.2f} m, 水深 zw={tc.water_depth:.2f} m"
        )
    if notes:
        parts.append("<h2>荷重・水条件</h2>")
        parts.append("<ul>")
        for n in notes:
            parts.append(f"<li>{n}</li>")
        parts.append("</ul>")

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
            extra = ""
            if r.case.consider_liquefaction:
                mfl = _min_fl(cr)
                if mfl is not None:
                    extra = f"　最小 FL={mfl:.3f}（液状化考慮）"
                else:
                    extra = "　液状化: 判定対象なし"
            parts.append(
                f"<p class='cinfo'>中心 (x={cr.xc:.2f}, y={cr.yc:.2f})　"
                f"半径 R={cr.r:.2f} m　最小安全率 Fs={cr.fs:.3f}{extra}</p>"
            )
        parts.append(svg)

    # ニューマーク法
    if newmark:
        parts.append("<h2>ニューマーク法（滑動変位量）</h2>")
        parts.append("<table class='result'>")
        parts.append(
            "<tr><th>ケース</th><th>ky</th><th>kh</th>"
            "<th>D (cm)</th><th>Da (cm)</th><th>算定方法</th><th>判定</th></tr>"
        )
        for nm in newmark:
            ky = f"{nm.ky:.3f}" if nm.ky is not None else "—"
            d = f"{nm.displacement*100:.1f}" if nm.displacement is not None else "—"
            method = "時刻歴積分" if nm.used_time_history else "経験式"
            j = nm.judgement
            cls = "ok" if j == "OK" else "ng"
            parts.append(
                f"<tr><td>{html.escape(nm.case.name)}</td><td>{ky}</td>"
                f"<td>{nm.kmax:.3f}</td><td>{d}</td>"
                f"<td>{nm.allowable*100:.0f}</td><td>{method}</td>"
                f"<td class='{cls}'>{html.escape(j)}</td></tr>"
            )
        parts.append("</table>")

    # 対策工の比較
    if countermeasures:
        parts.append("<h2>対策工の比較</h2>")
        names = ["無対策"] + [c.countermeasure.name for c in countermeasures]
        parts.append("<table class='result'>")
        head = "".join(f"<th>{html.escape(n)}</th>" for n in names)
        parts.append(f"<tr><th>ケース</th>{head}</tr>")
        for i, r in enumerate(results):
            cells = []
            for res_set in [results] + [c.results for c in countermeasures]:
                rr = res_set[i]
                if rr.critical is None:
                    cells.append("<td>—</td>")
                else:
                    cls = "ok" if rr.ok else "ng"
                    cells.append(
                        f"<td>{rr.critical.fs:.3f} "
                        f"<span class='{cls}'>{rr.judgement}</span></td>"
                    )
            parts.append(
                f"<tr><td>{html.escape(r.case.name)}</td>{''.join(cells)}</tr>"
            )
        parts.append("</table>")

        for c in countermeasures:
            parts.append(f"<h3>{html.escape(c.countermeasure.name)}</h3>")
            csx, csy, cpoly, cw, ch = _make_transform(c.section, c.results)
            for rr in c.results:
                sec_c = section_for_case(c.section, rr.case)
                if rr.critical:
                    parts.append(
                        f"<p class='cinfo'>{html.escape(rr.case.name)}: "
                        f"Fs={rr.critical.fs:.3f}（{rr.judgement}）</p>"
                    )
                parts.append(
                    _svg_for_case(sec_c, rr, csx, csy, cpoly, cw, ch)
                )

    # 感度分析
    if sensitivity:
        parts.append("<h2>感度分析</h2>")
        for res in sensitivity:
            t = res.target
            parts.append(
                f"<h3>{html.escape(t.layer)} の {html.escape(res.param_label)}</h3>"
            )
            parts.append("<table class='result'>")
            head = "".join(f"<th>{html.escape(n)}</th>" for n in res.case_names)
            parts.append(f"<tr><th>値</th>{head}</tr>")
            for row in res.rows:
                cells = "".join(
                    f"<td>{('%.3f' % fs) if fs is not None else '—'}</td>"
                    for fs in row.fs_by_case
                )
                parts.append(f"<tr><td>{row.value:.2f}</td>{cells}</tr>")
            parts.append("</table>")

    body = "\n".join(parts)
    return _HTML_TEMPLATE.replace("{{BODY}}", body)


def _svg_for_case(
    section, result: Optional[CaseResult], sx, sy, poly, w, h
) -> str:
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

    # 地盤改良範囲（緑の破線矩形）
    for z in section.improvements:
        x0, y0 = sx(z.x_start), sy(z.y_top)
        x1, y1 = sx(z.x_end), sy(z.y_bottom)
        elems.append(
            f"<rect x='{x0:.1f}' y='{y0:.1f}' width='{x1-x0:.1f}' "
            f"height='{y1-y0:.1f}' fill='#1a7f37' opacity='0.15' "
            f"stroke='#1a7f37' stroke-width='1.5' stroke-dasharray='5,3'/>"
        )
        elems.append(
            f"<text x='{(x0+x1)/2:.1f}' y='{y0-4:.1f}' class='implbl'>"
            f"{z.name}</text>"
        )

    # 外水（地表面より上の水域を塗る）
    if section.external_water:
        from .geometry import external_water_y, surface_y as _surf_y

        ew = section.external_water
        x0w, x1w = ew[0].x, ew[-1].x
        nsm = 120
        region: List[Tuple[float, float, float]] = []
        regions: List[List[Tuple[float, float, float]]] = []
        for k in range(nsm + 1):
            xx = x0w + (x1w - x0w) * k / nsm
            yw_ = external_water_y(section, xx)
            ys_ = _surf_y(section, xx)
            if yw_ is not None and ys_ is not None and yw_ > ys_ + 1e-6:
                region.append((xx, yw_, ys_))
            elif region:
                regions.append(region)
                region = []
        if region:
            regions.append(region)
        for reg in regions:
            top = " ".join(f"{sx(x):.1f},{sy(yw_):.1f}" for x, yw_, _ in reg)
            bot = " ".join(
                f"{sx(x):.1f},{sy(ys_):.1f}" for x, _, ys_ in reversed(reg)
            )
            elems.append(
                f"<polygon points='{top} {bot}' fill='#1e73c8' "
                f"opacity='0.25' stroke='none'/>"
            )
        elems.append(
            f"<polyline points='{poly(ew)}' fill='none' "
            f"stroke='#1e73c8' stroke-width='2'/>"
        )
        p0 = ew[0]
        elems.append(
            f"<text x='{sx(p0.x)+4:.1f}' y='{sy(p0.y)-6:.1f}' "
            f"class='wlbl'>外水位</text>"
        )

    # 上載荷重（下向き矢印列）
    if section.surcharges:
        from .geometry import surface_y as _surf_y2

        for sc in section.surcharges:
            n_arrow = 6
            alen = 18  # 矢印長（px）
            tail_pts = []
            for k in range(n_arrow + 1):
                xx = sc.x_start + (sc.x_end - sc.x_start) * k / n_arrow
                ys_ = _surf_y2(section, xx)
                if ys_ is None:
                    continue
                xpx, ypx = sx(xx), sy(ys_)
                elems.append(
                    f"<line x1='{xpx:.1f}' y1='{ypx-alen:.1f}' "
                    f"x2='{xpx:.1f}' y2='{ypx-2:.1f}' "
                    f"stroke='#b05a00' stroke-width='1.5'/>"
                )
                elems.append(
                    f"<polygon points='{xpx-3:.1f},{ypx-6:.1f} "
                    f"{xpx+3:.1f},{ypx-6:.1f} {xpx:.1f},{ypx-1:.1f}' "
                    f"fill='#b05a00'/>"
                )
                tail_pts.append((xpx, ypx - alen))
            if tail_pts:
                line = " ".join(f"{x:.1f},{y:.1f}" for x, y in tail_pts)
                elems.append(
                    f"<polyline points='{line}' fill='none' "
                    f"stroke='#b05a00' stroke-width='1.5'/>"
                )
                mx = 0.5 * (tail_pts[0][0] + tail_pts[-1][0])
                elems.append(
                    f"<text x='{mx:.1f}' y='{tail_pts[0][1]-5:.1f}' "
                    f"class='qlbl'>q={sc.q:.0f} kN/m²</text>"
                )

    # 浸潤線
    if section.phreatic:
        elems.append(
            f"<polyline points='{poly(section.phreatic.points)}' fill='none' "
            f"stroke='#1e73c8' stroke-width='2' stroke-dasharray='6,4'/>"
        )
        # 水位マーク
        p0 = section.phreatic.points[0]
        lbl = "浸潤線（推定）" if section.phreatic_estimated else "浸潤線"
        elems.append(
            f"<text x='{sx(p0.x)+4:.1f}' y='{sy(p0.y)-4:.1f}' "
            f"class='wlbl'>{lbl}</text>"
        )

    cr: Optional[CircleResult] = result.critical if result is not None else None
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
        # テンションクラック（すべり面上端の鉛直線）
        if cr.crack_x is not None:
            from .geometry import surface_y as _surf_y3

            xck = cr.crack_x
            dxc = xck - cr.xc
            if abs(dxc) <= cr.r:
                ya_c = cr.yc - math.sqrt(cr.r * cr.r - dxc * dxc)
                ys_c = _surf_y3(section, xck)
                if ys_c is not None:
                    elems.append(
                        f"<line x1='{sx(xck):.1f}' y1='{sy(ys_c):.1f}' "
                        f"x2='{sx(xck):.1f}' y2='{sy(ya_c):.1f}' "
                        f"stroke='#7a1f14' stroke-width='2' "
                        f"stroke-dasharray='4,3'/>"
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
  text.qlbl { font-size: 11px; fill: #b05a00; text-anchor: middle; }
  text.implbl { font-size: 11px; fill: #1a7f37; text-anchor: middle; }
  span.ok { color: #1a7f37; font-weight: bold; }
  span.ng { color: #c0392b; font-weight: bold; }
  .warnbox { background: #fff6d9; border: 1px solid #d4a900; border-radius: 6px;
             padding: 10px 14px; margin: 12px 0; font-size: 0.92rem; }
  .warnbox ul { margin: 6px 0 0; padding-left: 20px; }
  @media (prefers-color-scheme: dark) {
    .warnbox { background: #3a3010; border-color: #8a7a20; }
  }
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
