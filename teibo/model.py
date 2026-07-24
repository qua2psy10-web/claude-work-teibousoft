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
class LiquefactionProps:
    """液状化判定（FL 法）に用いる土質特性。

    Attributes:
        n_value:       標準貫入試験 N 値。
        fines_content: 細粒分含有率 FC (%)。
    """

    n_value: float
    fines_content: float = 0.0

    def __post_init__(self) -> None:
        if self.n_value < 0:
            raise ValueError("液状化特性: n_value は 0 以上が必要です")
        if not (0.0 <= self.fines_content <= 100.0):
            raise ValueError("液状化特性: fines_content は 0〜100% が必要です")


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
        liquefaction: 液状化判定用特性（砂質土のみ指定、None なら判定対象外）。
    """

    name: str
    top: List[Point]
    gamma: float
    gamma_sat: float
    c: float
    phi: float
    liquefaction: Optional[LiquefactionProps] = None

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
class Surcharge:
    """上載荷重（等分布荷重）。

    地表面上の x_start〜x_end に鉛直下向きの等分布荷重 q (kN/m2) を
    載荷する。スライス重量に q×幅 として加算され、震度 kh の
    慣性力にも寄与する。
    """

    x_start: float
    x_end: float
    q: float
    name: str = "載荷重"

    def __post_init__(self) -> None:
        if self.x_end <= self.x_start:
            raise ValueError(f"載荷重 '{self.name}': x_end > x_start が必要です")
        if self.q < 0:
            raise ValueError(f"載荷重 '{self.name}': q は 0 以上が必要です")


@dataclass
class TensionCrack:
    """テンションクラック（引張亀裂）。

    Attributes:
        depth:       亀裂深さ zc (m)。地表面からの鉛直深さ。
        water_depth: 亀裂内の水深 zw (m)（0〜zc）。亀裂内水圧
                     Pw = ½·γw·zw² が水平力として起動側に作用する。
    """

    depth: float
    water_depth: float = 0.0

    def __post_init__(self) -> None:
        if self.depth <= 0:
            raise ValueError("テンションクラック: depth は正の値が必要です")
        if not (0.0 <= self.water_depth <= self.depth):
            raise ValueError("テンションクラック: 0 <= water_depth <= depth が必要です")


@dataclass
class ImprovementZone:
    """地盤改良（置換・固化改良等）の範囲。

    矩形範囲 [x_start, x_end] × [y_bottom, y_top] 内のすべり面では
    土層の c・φ に代えて改良後の c・φ を用いる（単位体積重量は
    元の土層のまま）。改良範囲は液状化判定の対象外とする。
    """

    x_start: float
    x_end: float
    y_top: float
    y_bottom: float
    c: float
    phi: float
    name: str = "地盤改良"

    def __post_init__(self) -> None:
        if self.x_end <= self.x_start:
            raise ValueError(f"改良範囲 '{self.name}': x_end > x_start が必要です")
        if self.y_top <= self.y_bottom:
            raise ValueError(f"改良範囲 '{self.name}': y_top > y_bottom が必要です")


@dataclass
class Section:
    """堤防断面。

    layers[0] の上面が地表面（堤防表面）を表す。以降の層は
    上から順に並べる。
    """

    layers: List[SoilLayer]
    phreatic: Optional[PhreaticLine] = None
    name: str = "堤防断面"
    # 上載荷重（複数可）
    surcharges: List[Surcharge] = field(default_factory=list)
    # 外水位（河川水位）。地表面より上の水は重量として作用し、
    # 間隙水圧の水頭にも採用される。
    external_water: Optional[List[Point]] = None
    # テンションクラック
    tension_crack: Optional[TensionCrack] = None
    # 地盤改良範囲（対策工の照査などで使用）
    improvements: List[ImprovementZone] = field(default_factory=list)
    # 浸潤線が自動推定によるものかどうか（レポート注記用）
    phreatic_estimated: bool = False

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
        method:      "fellenius"（修正フェレニウス法）／"bishop"（簡易ビショップ法）／
                     "spencer"（スペンサー法・非円弧すべり面）。
        phreatic:    ケース専用の浸潤線（水位急降下時の残留間隙水圧など）。
                     None なら断面の浸潤線をそのまま用いる。
        external_water: ケース専用の外水位。None なら断面の設定を継承、
                     空リストなら「外水なし」（水位急降下時など）。
        consider_liquefaction: True の場合、液状化特性を持つ飽和層について
                     FL 法で過剰間隙水圧を算定し安定計算へ反映する。
        newmark:     True の場合、臨界円に対して降伏震度 ky と
                     ニューマーク法による滑動変位量を算定する。
        allowable_displacement: ニューマーク法の許容変位量 Da (m)。
        slip_surface: スペンサー法で照査する非円弧すべり面（左→右の折れ線）。
                     method="spencer" のときに用いる。円中心探索は行わない。
    """

    name: str
    kh: float = 0.0
    allowable_fs: float = 1.2
    method: str = "fellenius"
    phreatic: Optional[PhreaticLine] = None
    external_water: Optional[List[Point]] = None
    consider_liquefaction: bool = False
    newmark: bool = False
    allowable_displacement: float = 0.5
    slip_surface: Optional[List[Point]] = None

    def __post_init__(self) -> None:
        m = self.method.lower()
        if m not in ("fellenius", "bishop", "spencer"):
            raise ValueError(f"未知の解析法: {self.method}")
        self.method = m
        if m == "spencer" and self.slip_surface is not None:
            if len(self.slip_surface) < 2:
                raise ValueError("スペンサー法: slip_surface は2点以上必要です")
            xs = [p.x for p in self.slip_surface]
            if any(b < a for a, b in zip(xs, xs[1:])):
                raise ValueError("スペンサー法: slip_surface の x は昇順である必要があります")


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
    # --- すべり円の拘束条件（いずれも None なら制約なし） ---
    # 円弧下端（yc - R）がこの標高より下に入る円を除外する
    y_lower_limit: Optional[float] = None
    # すべり始端 xl（左側交点）の許容範囲
    x_entry_min: Optional[float] = None
    x_entry_max: Optional[float] = None
    # すべり終端 xr（右側交点）の許容範囲
    x_exit_min: Optional[float] = None
    x_exit_max: Optional[float] = None
    # 非円弧すべり面の自動探索（スペンサー法）の中間ノード数
    nc_nodes: int = 6


@dataclass
class SensitivityTarget:
    """感度分析の対象パラメータ。

    layer で指定した土層の param（c / phi / gamma / gamma_sat）を
    values の各値に差し替えて Fs の変化を調べる。
    """

    layer: str
    param: str
    values: List[float]

    _PARAMS = ("c", "phi", "gamma", "gamma_sat")

    def __post_init__(self) -> None:
        if self.param not in self._PARAMS:
            raise ValueError(
                f"感度分析: param は {self._PARAMS} のいずれかを指定してください"
            )
        if not self.values:
            raise ValueError("感度分析: values が空です")


@dataclass
class AnalysisInput:
    """解析入力一式。"""

    section: Section
    cases: List[LoadCase] = field(default_factory=list)
    grid: SearchGrid = field(default_factory=SearchGrid)
    sensitivity: List[SensitivityTarget] = field(default_factory=list)
    # ニューマーク法の時刻歴計算に用いる加速度波形 [(時刻 s, 加速度 gal)]。
    # None の場合は経験式（Ambraseys & Menu）で変位量を推定する。
    accel_series: Optional[List[Point]] = None
    # 対策工の案（countermeasure.Countermeasure のリスト。循環回避のため型は緩く保持）
    countermeasures: List[object] = field(default_factory=list)
    # スペンサー法で照査する非円弧すべり面（入力全体の既定値）。
    # method="spencer" のケースで case.slip_surface 未指定時にこれを用いる。
    slip_surface: Optional[List[Point]] = None
    # 一括処理用: 距離標（例 "0k200"）と縦断方向の累積距離 (m)
    station: Optional[str] = None
    distance: Optional[float] = None
