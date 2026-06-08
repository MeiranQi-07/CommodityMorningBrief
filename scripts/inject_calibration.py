#!/usr/bin/env python3
"""
inject_calibration.py — 将校准规则注入 LLM 分析 prompt

读取 impact_analyze.md 模板，将 {CALIBRATION_SECTION} 替换为
backtest_calibration.json 中最新的校准建议文本。

用法:
    python3 scripts/inject_calibration.py                          # 输出到终端
    python3 scripts/inject_calibration.py --prompt prompts/impact_analyze.md  # 指定模板
    python3 scripts/inject_calibration.py --output /tmp/analyze_prompt.md     # 写到文件
    python3 scripts/inject_calibration.py --quiet                              # 只输出有效内容
"""

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "scripts" else SCRIPT_DIR

# 默认路径
DEFAULT_PROMPT = os.path.join(BASE_DIR, "prompts", "impact_analyze.md")
DEFAULT_CALIBRATION = os.path.join(BASE_DIR, "data", "backtest_calibration.json")


def load_calibration(path=None):
    path = path or DEFAULT_CALIBRATION
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="注入校准规则到 LLM prompt")
    parser.add_argument("--prompt", type=str, default=DEFAULT_PROMPT,
                        help="prompt 模板路径")
    parser.add_argument("--calibration", type=str, default=DEFAULT_CALIBRATION,
                        help="校准规则 JSON 路径")
    parser.add_argument("--output", type=str, default="",
                        help="输出文件路径 (默认输出到终端)")
    parser.add_argument("--quiet", action="store_true",
                        help="只输出注入后的完整 prompt，不打印调试信息")
    args = parser.parse_args()

    # 读取 prompt 模板
    if not os.path.exists(args.prompt):
        print(f"❌ 未找到 prompt 模板: {args.prompt}", file=sys.stderr)
        sys.exit(1)

    with open(args.prompt, "r", encoding="utf-8") as f:
        template = f.read()

    # 加载校准数据
    calibration = load_calibration(args.calibration)
    if calibration:
        calibration_text = calibration.get("prompt_section", "")
        if not args.quiet:
            print(f"📌 已注入校准: {calibration.get('history_periods', 0)} 期回测数据", file=sys.stderr)
            has_bias = any(
                a.get("bias_found")
                for a in calibration.get("asset_analyses", {}).values()
            )
            if has_bias:
                print("⚠️  存在偏差资产，校准建议已加载", file=sys.stderr)
            else:
                print("✅ 未发现显著偏差，维持默认规则", file=sys.stderr)
    else:
        calibration_text = "校准数据暂不可用，请使用默认判断规则。"
        if not args.quiet:
            print("ℹ️  无校准数据，使用默认判断规则", file=sys.stderr)

    # 替换占位符
    injected = template.replace("{CALIBRATION_SECTION}", calibration_text)

    # 输出
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(injected)
        if not args.quiet:
            print(f"✅ 已写入: {args.output}", file=sys.stderr)
    else:
        print(injected)


if __name__ == "__main__":
    main()
