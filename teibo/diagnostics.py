"""入力診断。

解析前に入力の物理的な不整合を検出して警告する。誤入力
（例: 浸潤線を地表面より上に置いた「池状態」）による異常な
照査結果を防ぐことが目的。エラーではなく警告であり、解析は続行する。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .geometry import external_water_y, interp_polyline, phreatic_y, surface_y
from .model import AnalysisInput, PhreaticLine, Section


def _sample_range(x0: float, x1: float, n: int = 200) -> List[float]:
    if x1 <= x0:
        return [x0]
    return [x0 + (x1 - x0) * i / n for i in range(n + 1)]


def _ranges_where(xs: List[float], flags: List[bool]) -> List[Tuple[float, float]]:
    """True が連続する x 区間のリストにまとめる。"""
    out: List[Tuple[float, float]] = []
    start: Optional[float] = None
    for x, f in zip(xs, flags):
        if f and start is None:
            start = x
        elif not f and start is not None:
            out.append((start, x))
            start = None
    if start is not None:
        out.append((start, xs[-1]))
    return out


def _fmt_ranges(ranges: List[Tuple[float, float]]) -> str:
    return "、".join(f"x={a:.1f}〜{b:.1f}" for a, b in ranges[:3]) + (
        " ほか" if len(ranges) > 3 else ""
    )


def _check_phreatic_above_surface(
    section: Section, phreatic: Optional[PhreaticLine], label: str
) -> List[str]:
    """浸潤線が地表面より上（池状態）の警告。

    外水位が同等以上にある範囲は水没地盤として正常なので除外する。
    """
    if phreatic is None:
        return []
    surf = section.surface
    x0 = max(surf[0].x, phreatic.points[0].x)
    x1 = min(surf[-1].x, phreatic.points[-1].x)
    xs = _sample_range(x0, x1)
    flags: List[bool] = []
    for x in xs:
        ys = surface_y(section, x)
        yp = phreatic_y(phreatic, x)
        bad = ys is not None and yp is not None and yp > ys + 0.05
        if bad:
            ye = external_water_y(section, x)
            if ye is not None and ye >= yp - 0.05:
                bad = False  # 外水位以下の水没地盤（正常）
        flags.append(bad)
    ranges = _ranges_where(xs, flags)
    if not ranges:
        return []
    return [
        f"{label}が地表面より上にあります（{_fmt_ranges(ranges)}）。"
        "地表水（池状態）として扱われ有効応力がほぼ 0 になり、"
        "安全率が異常に小さくなるおそれがあります。"
        "外水として扱う場合は external_water を使用してください。"
    ]


def validate_input(data: AnalysisInput) -> List[str]:
    """入力の不整合を検出し、警告メッセージのリストを返す。"""
    warnings: List[str] = []
    section = data.section
    surf = section.surface

    # 1. 浸潤線 > 地表面（断面・ケース別）
    warnings += _check_phreatic_above_surface(section, section.phreatic, "浸潤線")
    for case in data.cases:
        if case.phreatic is not None:
            warnings += _check_phreatic_above_surface(
                section, case.phreatic, f"ケース「{case.name}」の浸潤線"
            )

    # 2. 層順序: 下の層の上面が上の層の上面より高い
    for upper, lower in zip(section.layers, section.layers[1:]):
        x0 = max(upper.top[0].x, lower.top[0].x)
        x1 = min(upper.top[-1].x, lower.top[-1].x)
        xs = _sample_range(x0, x1)
        flags = []
        for x in xs:
            yu = interp_polyline(upper.top, x)
            yl = interp_polyline(lower.top, x)
            flags.append(yu is not None and yl is not None and yl > yu + 0.05)
        ranges = _ranges_where(xs, flags)
        if ranges:
            warnings.append(
                f"層「{lower.name}」の上面が層「{upper.name}」の上面より"
                f"高い区間があります（{_fmt_ranges(ranges)}）。"
                "layers は上から順に並べてください。"
            )

    # 3. 単位体積重量の逆転
    for ly in section.layers:
        if ly.gamma_sat < ly.gamma:
            warnings.append(
                f"層「{ly.name}」: γsat ({ly.gamma_sat}) < γt ({ly.gamma}) と"
                "なっています。通常は γsat ≥ γt です。"
            )

    # 4. せん断強度ゼロ
    for ly in section.layers:
        if ly.c == 0.0 and ly.phi == 0.0:
            warnings.append(
                f"層「{ly.name}」: c=0 かつ φ=0（せん断強度なし）です。"
                "この層を通るすべり面の安全率はほぼ 0 になります。"
            )

    # 5. 上載荷重が地表面の範囲外
    for sc in section.surcharges:
        if sc.x_end < surf[0].x or sc.x_start > surf[-1].x:
            warnings.append(
                f"載荷重「{sc.name}」（x={sc.x_start}〜{sc.x_end}）が"
                "地表面の定義範囲外にあり、計算に反映されません。"
            )

    # 6. 外水位が全域で地表面より下
    if section.external_water:
        xs = _sample_range(
            section.external_water[0].x, section.external_water[-1].x
        )
        any_above = False
        for x in xs:
            ye = external_water_y(section, x)
            ys = surface_y(section, x)
            if ye is not None and ys is not None and ye > ys:
                any_above = True
                break
        if not any_above:
            warnings.append(
                "外水位が全域で地表面より低く、水重としては作用しません"
                "（間隙水圧の水頭としてのみ考慮されます）。"
            )

    # 7. 液状化特性があるのに考慮しないケースのみ
    has_liq = any(ly.liquefaction is not None for ly in section.layers)
    if has_liq and not any(c.consider_liquefaction for c in data.cases):
        warnings.append(
            "液状化特性（liquefaction）が定義されていますが、"
            "consider_liquefaction が true のケースがありません。"
        )

    return warnings
