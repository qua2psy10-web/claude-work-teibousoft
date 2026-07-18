"""堤防の安定性照査で用いるデータモデル。

断面形状・土層・水条件・照査条件を保持する軽量なデータクラス群。
外部依存を持たず、標準ライブラリのみで完結する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# 水の単位体積重量 (kN/m3)
GAMMA_W = 9.81


@dataclass(frozen=True)
class Point:
    """2次元座標 (m)。x は右向き正、y は上向き正。"""

    x: float
    y: float


@dataclass
class SoilLayer:
    """土層。

    top は層上面を表す折れ線（左→右）。層はこの上面から
    次層の上面（最下層は無限深さ）までを占める。

    Attributes:
        name:      層名称。
        top:       層上面折れ線。
        gamma:     湿潤単位体積重量 γt (kN/m3)。浸潤線より上で使用。
        gamma_sat: 飽和単位体積重量 γsat (kN/m3)。浸潤線より下で使用。
        c:         粘着力 c (kN/m2)。
        phi:       内部摩擦角 φ (度)。
    """

    name: str
    top: List[Point]
    gamma: float
    gamma_sat: float
    c: float
    phi: float

    def __post_init__(self) -> None:
        if len(self.top) < 2:
            raise ValueError(f"層 '{self.name}': 上面折れ線は2点以上必要です")
        xs = [p.x for p in self.top]
        if any(b < a for a, b in zip(xs, xs[1:])):
            raise ValueError(f"層 '{self.name}': 上面折れ線の x は昇順である必要があります")


@dataclass
class PhreaticLine:
    """浸潤線（自由水面）。折れ線で与える。

    間隙水圧は u = γw * max(0, y_浸潤線 - y_すべり面) で評価する。
    """

    points: List[Point]

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("浸潤線は2点以上必要です")


@dataclass
class Section:
    """堤防断面。

    layers[0] の上面が地表面（堤防表面）を表す。以降の層は
    上から順に並べる。
    """

    layers: List[SoilLayer]
    phreatic: Optional[PhreaticLine] = None
    name: str = "堤防断面"

    def __post_init__(self) -> None:
        if not self.layers:
            raise ValueError("土層が1層以上必要です")

    @property
    def surface(self) -> List[Point]:
        """地表面（最上層の上面）折れ線。"""
        return self.layers[0].top


@dataclass
class LoadCase:
    """照査ケース。

    Attributes:
        name:        ケース名（例: 常時、地震時）。
        kh:          設計水平震度。常時は 0。
        allowable_fs: 必要安全率 Fsa。
        method:      "fellenius"（修正フェレニウス法）または "bishop"（簡易ビショップ法）。
    """

    name: str
    kh: float = 0.0
    allowable_fs: float = 1.2
    method: str = "fellenius"

    def __post_init__(self) -> None:
        m = self.method.lower()
        if m not in ("fellenius", "bishop"):
            raise ValueError(f"未知の解析法: {self.method}")
        self.method = m


@dataclass
class SearchGrid:
    """臨界すべり円の探索範囲。

    円中心 (xc, yc) を格子状に走査し、各中心について半径を変えて
    最小安全率を探索する。値を省略すると断面から自動設定する。
    """

    xc_min: Optional[float] = None
    xc_max: Optional[float] = None
    yc_min: Optional[float] = None
    yc_max: Optional[float] = None
    nx: int = 15
    ny: int = 15
    # すべり面が到達する最深標高（この標高に接する円までを対象にする）
    tangent_y_min: Optional[float] = None
    tangent_y_max: Optional[float] = None
    nr: int = 12
    # 1つの円あたりの分割数
    n_slices: int = 40


@dataclass
class AnalysisInput:
    """解析入力一式。"""

    section: Section
    cases: List[LoadCase] = field(default_factory=list)
    grid: SearchGrid = field(default_factory=SearchGrid)
