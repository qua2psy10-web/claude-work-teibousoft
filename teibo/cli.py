"""コマンドラインインターフェース。

使用例:
    python -m teibo analyze examples/river_levee.json
    python -m teibo analyze input.json --html report.html
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .io_json import load_input
from .report import html_report, text_report
from .search import run_all


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="teibo",
        description="堤防の円弧すべり安定性照査ツール",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_an = sub.add_parser("analyze", help="断面を照査する")
    p_an.add_argument("input", help="入力 JSON ファイル")
    p_an.add_argument(
        "--html", metavar="FILE", help="HTML レポートの出力先"
    )
    p_an.add_argument(
        "--quiet", action="store_true", help="テキスト結果を表示しない"
    )

    args = parser.parse_args(argv)

    if args.command == "analyze":
        return _cmd_analyze(args)
    parser.print_help()
    return 1


def _cmd_analyze(args) -> int:
    try:
        data = load_input(args.input)
    except FileNotFoundError:
        print(f"エラー: 入力ファイルが見つかりません: {args.input}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"エラー: 入力の読み込みに失敗しました: {e}", file=sys.stderr)
        return 2

    results = run_all(data.section, data.cases, data.grid)

    if not args.quiet:
        print(text_report(data.section, results))

    if args.html:
        html = html_report(data.section, results)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nHTML レポートを出力しました: {args.html}")

    # いずれかのケースが NG なら終了コード 1
    all_ok = all(r.ok for r in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
