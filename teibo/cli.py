"""コマンドラインインターフェース。

使用例:
    python -m teibo analyze examples/river_levee.json
    python -m teibo analyze input.json --html report.html
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .countermeasure import run_countermeasures
from .diagnostics import validate_input
from .io_json import load_input
from .newmark import run_newmark
from .report import html_report, sensitivity_text_report, text_report
from .search import run_all
from .sensitivity import run_sensitivity


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
    p_an.add_argument(
        "--sensitivity",
        action="store_true",
        help="入力の sensitivity 定義に基づき感度分析も実行する",
    )

    p_gui = sub.add_parser("gui", help="ブラウザ GUI を起動する")
    p_gui.add_argument(
        "input", nargs="?", help="初期表示する入力 JSON ファイル（省略可）"
    )
    p_gui.add_argument("--host", default="127.0.0.1", help="待受ホスト")
    p_gui.add_argument("--port", type=int, default=8765, help="待受ポート")

    p_bt = sub.add_parser("batch", help="複数断面をまとめて照査する")
    p_bt.add_argument("inputs", nargs="+", help="入力 JSON ファイル（複数）")
    p_bt.add_argument("--csv", metavar="FILE", help="縦断 Fs 一覧の CSV 出力先")
    p_bt.add_argument(
        "--html", metavar="FILE", help="HTML レポート（縦断グラフつき）の出力先"
    )
    p_bt.add_argument(
        "--details",
        action="store_true",
        help="HTML に断面ごとの臨界円図も含める",
    )
    p_bt.add_argument(
        "--quiet", action="store_true", help="テキスト結果を表示しない"
    )

    args = parser.parse_args(argv)

    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "gui":
        return _cmd_gui(args)
    if args.command == "batch":
        return _cmd_batch(args)
    parser.print_help()
    return 1


def _cmd_batch(args) -> int:
    from .batch import batch_csv, batch_html_report, batch_text_report, run_batch

    try:
        entries = run_batch(args.inputs)
    except FileNotFoundError as e:
        print(f"エラー: 入力ファイルが見つかりません: {e.filename}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"エラー: 入力の読み込みに失敗しました: {e}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(batch_text_report(entries))

    if args.csv:
        with open(args.csv, "w", encoding="utf-8") as f:
            f.write(batch_csv(entries))
        print(f"CSV を出力しました: {args.csv}")

    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(batch_html_report(entries, details=args.details))
        print(f"HTML レポートを出力しました: {args.html}")

    return 0 if all(e.all_ok for e in entries) else 1


def _cmd_gui(args) -> int:
    from .webapp import serve

    initial = None
    if args.input:
        try:
            with open(args.input, "r", encoding="utf-8") as f:
                initial = f.read()
        except OSError as e:
            print(f"エラー: 入力ファイルを読めません: {e}", file=sys.stderr)
            return 2
    serve(host=args.host, port=args.port, initial_input=initial)
    return 0


def _cmd_analyze(args) -> int:
    try:
        data = load_input(args.input)
    except FileNotFoundError:
        print(f"エラー: 入力ファイルが見つかりません: {args.input}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"エラー: 入力の読み込みに失敗しました: {e}", file=sys.stderr)
        return 2

    warnings = validate_input(data) or None
    if warnings:
        for w in warnings:
            print(f"警告: {w}", file=sys.stderr)

    results = run_all(data.section, data.cases, data.grid)
    nm = run_newmark(results, data.accel_series) or None
    cms = None
    if data.countermeasures:
        cms = run_countermeasures(
            data.section, data.cases, data.grid, data.countermeasures
        )

    sens = None
    if args.sensitivity:
        if not data.sensitivity:
            print(
                "警告: 入力に sensitivity 定義がないため感度分析をスキップします",
                file=sys.stderr,
            )
        else:
            sens = run_sensitivity(
                data.section, data.cases, data.grid, data.sensitivity
            )

    if not args.quiet:
        print(
            text_report(
                data.section,
                results,
                newmark=nm,
                countermeasures=cms,
                warnings=warnings,
            )
        )
        if sens:
            print()
            print(sensitivity_text_report(sens))

    if args.html:
        html = html_report(
            data.section,
            results,
            sensitivity=sens,
            newmark=nm,
            countermeasures=cms,
            warnings=warnings,
        )
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nHTML レポートを出力しました: {args.html}")

    # いずれかのケースが NG なら終了コード 1
    all_ok = all(r.ok for r in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
