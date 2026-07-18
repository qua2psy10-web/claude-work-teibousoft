"""teibo — 堤防の円弧すべり安定性照査ツール。

修正フェレニウス法・簡易ビショップ法による円弧すべり計算で、
堤防（盛土）の安定性を照査する。間隙水圧（浸潤線）、震度法による
地震時照査、臨界すべり円の自動探索に対応する。
"""

from .model import (
    AnalysisInput,
    LoadCase,
    PhreaticLine,
    Point,
    Section,
    SearchGrid,
    SoilLayer,
)
from .io_json import load_input, parse_input
from .search import CaseResult, run_all, search_critical
from .stability import CircleResult, Slice, analyze_circle
from .report import html_report, text_report

__version__ = "0.1.0"

__all__ = [
    "AnalysisInput",
    "LoadCase",
    "PhreaticLine",
    "Point",
    "Section",
    "SearchGrid",
    "SoilLayer",
    "load_input",
    "parse_input",
    "CaseResult",
    "run_all",
    "search_critical",
    "CircleResult",
    "Slice",
    "analyze_circle",
    "html_report",
    "text_report",
]
