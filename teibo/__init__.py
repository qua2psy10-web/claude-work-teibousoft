"""teibo — 堤防の円弧すべり安定性照査ツール。

修正フェレニウス法・簡易ビショップ法による円弧すべり計算で、
堤防（盛土）の安定性を照査する。間隙水圧（浸潤線）、震度法による
地震時照査、臨界すべり円の自動探索に対応する。

v0.2 での拡張:
- 上載荷重（等分布荷重）
- 外水位（水重・間隙水圧への反映）とケース別浸潤線（水位急降下）
- テンションクラック（亀裂内水圧）
- すべり円の拘束条件（始端・終端・下限標高）
- 感度分析（c / φ / γ の変化に対する Fs）
- 浸潤線の自動推定（カサグランデの基本放物線）
"""

from .model import (
    AnalysisInput,
    LiquefactionProps,
    LoadCase,
    PhreaticLine,
    Point,
    Section,
    SearchGrid,
    SensitivityTarget,
    SoilLayer,
    Surcharge,
    TensionCrack,
)
from .countermeasure import (
    Berm,
    Countermeasure,
    CountermeasureResult,
    apply_countermeasure,
    run_countermeasures,
)
from .diagnostics import validate_input
from .io_json import load_input, parse_input
from .liquefaction import fl_value, ru_from_fl
from .model import ImprovementZone
from .newmark import NewmarkResult, run_newmark
from .search import CaseResult, run_all, search_critical, section_for_case
from .seepage import estimate_phreatic
from .sensitivity import SensitivityResult, run_sensitivity
from .stability import CircleResult, Slice, SlipSurface, analyze_circle
from .report import html_report, sensitivity_text_report, text_report

__version__ = "0.8.0"

__all__ = [
    "AnalysisInput",
    "Berm",
    "Countermeasure",
    "CountermeasureResult",
    "apply_countermeasure",
    "run_countermeasures",
    "validate_input",
    "ImprovementZone",
    "LiquefactionProps",
    "fl_value",
    "ru_from_fl",
    "NewmarkResult",
    "run_newmark",
    "LoadCase",
    "PhreaticLine",
    "Point",
    "Section",
    "SearchGrid",
    "SensitivityTarget",
    "SoilLayer",
    "Surcharge",
    "TensionCrack",
    "load_input",
    "parse_input",
    "CaseResult",
    "run_all",
    "search_critical",
    "section_for_case",
    "estimate_phreatic",
    "SensitivityResult",
    "run_sensitivity",
    "CircleResult",
    "Slice",
    "SlipSurface",
    "analyze_circle",
    "html_report",
    "sensitivity_text_report",
    "text_report",
]
