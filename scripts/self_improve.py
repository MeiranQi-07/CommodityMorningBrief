#!/usr/bin/env python3
"""
self_improve.py — 自动复盘：分析回测历史，识别系统性偏差，生成校准规则

设计说明：
本脚本读取 output/ 下所有 backtest_result_*.json 文件，
统计各资产、各方向的长期准确率，检测 LLM 判断中的系统性偏差，
输出校准规则供后续分析时注入 prompt。

用法:
    python3 scripts/self_improve.py                              # 分析全部历史
    python3 scripts/self_improve.py --days 30                    # 只分析近30天
    python3 scripts/self_improve.py --output data/backtest_calibration.json
"""

import argparse
import glob
import json
import os
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "scripts" else SCRIPT_DIR
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

ASSET_NAMES = {
    "gold": "黄金",
    "silver": "白银",
    "crude_oil": "原油",
    "usd_index": "美元指数",
}

DIRECTION_NAMES = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "mixed": "多空交织",
}


def load_backtest_history(days=None):
    """加载所有回测结果，按日期排序"""
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "backtest_result_*.json")))
    if not files:
        print("❌ 未找到回测结果文件 (output/backtest_result_*.json)")
        return []

    cutoff = None
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    history = []
    for fpath in files:
        # 从文件名提取日期: backtest_result_20260603.json
        basename = os.path.basename(fpath)
        date_str = basename.replace("backtest_result_", "").replace(".json", "")
        if cutoff and date_str < cutoff:
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["_date"] = date_str
            history.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ⚠️  跳过 {basename}: {e}")

    history.sort(key=lambda x: x["_date"])
    return history


def analyze_asset_bias(history, asset):
    """
    分析单一资产的判断偏差

    返回:
        {
            "asset": "gold",
            "total": N,           # 该资产总判断次数
            "overall_accuracy": 0.75,
            "by_direction": {
                "bullish": { "count": 4, "correct": 3, "accuracy": 0.75 },
                "bearish": { "count": 2, "correct": 1, "accuracy": 0.50 }
            },
            "trend": [...],       # 每日准确率趋势
            "bias_found": bool,   # 是否存在需要关注的偏差
            "calibration": str,   # 校准建议文本
        }
    """
    name = ASSET_NAMES.get(asset, asset)
    direction_stats = {"bullish": {"count": 0, "correct": 0},
                       "bearish": {"count": 0, "correct": 0}}
    trend = []
    total_judgeable = 0
    total_correct = 0

    for day in history:
        ar = day.get("asset_results", {}).get(asset, {})
        if not ar or ar.get("judgeable", 0) == 0:
            continue

        total_judgeable += ar.get("judgeable", 0)
        total_correct += ar.get("correct", 0)
        day_acc = ar.get("accuracy")

        day_breakdown = {"date": day["_date"],
                         "accuracy": day_acc,
                         "change_pct": ar.get("actual_change_pct")}
        trend.append(day_breakdown)

        # 按方向拆分
        for detail in ar.get("detail", []):
            is_correct = detail.get("is_correct")
            direction = detail.get("direction")
            if is_correct is not None and direction in direction_stats:
                direction_stats[direction]["count"] += 1
                if is_correct:
                    direction_stats[direction]["correct"] += 1

    overall_acc = round(total_correct / total_judgeable, 4) if total_judgeable > 0 else None

    # 计算各方向准确率
    by_direction = {}
    for d, stats in direction_stats.items():
        if stats["count"] > 0:
            by_direction[d] = {
                "count": stats["count"],
                "correct": stats["correct"],
                "accuracy": round(stats["correct"] / stats["count"], 4),
            }

    # === 偏差识别逻辑 ===
    bias_found = False
    calibration_parts = []

    # 偏差规则 1: bullish 和 bearish 准确率差距过大
    if "bullish" in by_direction and "bearish" in by_direction:
        b_accuracy = by_direction["bullish"]["accuracy"]
        be_accuracy = by_direction["bearish"]["accuracy"]
        gap = b_accuracy - be_accuracy

        if by_direction["bullish"]["count"] >= 2 and by_direction["bearish"]["count"] >= 2:
            if gap < -0.3:
                bias_found = True
                calibration_parts.append(
                    f"{name}利多判断准确率({b_accuracy:.0%})显著低于利空判断({be_accuracy:.0%})，"
                    f"模型对该资产存在过度乐观倾向。建议对利多新闻要求更高证据强度。"
                )
            elif gap > 0.3:
                bias_found = True
                calibration_parts.append(
                    f"{name}利空判断准确率({be_accuracy:.0%})显著低于利多判断({b_accuracy:.0%})，"
                    f"模型对该资产存在过度悲观倾向。建议对利空新闻要求更高证据强度。"
                )

    # 偏差规则 2: 单方向样本太少但准确率极端
    for d in ["bullish", "bearish"]:
        if d in by_direction:
            ds = by_direction[d]
            if ds["count"] >= 3 and ds["accuracy"] <= 0.3:
                bias_found = True
                dir_label = DIRECTION_NAMES.get(d, d)
                calibration_parts.append(
                    f"{name}{dir_label}判断近{ds['count']}次仅{ds['correct']}次正确({ds['accuracy']:.0%})，"
                    f"建议对该方向的判断逻辑进行审查。"
                )

    # 偏差规则 3: 整体准确率偏低
    if overall_acc is not None and total_judgeable >= 5 and overall_acc < 0.5:
        bias_found = True
        calibration_parts.append(
            f"{name}整体判断准确率仅{overall_acc:.0%}（{total_judgeable}次），"
            f"建议加强对该资产的因果关系推理。"
        )

    calibration = "；".join(calibration_parts) if calibration_parts else "未发现显著偏差，维持现有判断标准。"

    return {
        "asset": asset,
        "asset_name": name,
        "total_samples": total_judgeable,
        "overall_accuracy": overall_acc,
        "by_direction": by_direction,
        "trend": trend,
        "bias_found": bias_found,
        "calibration": calibration,
    }


def build_prompt_section(asset_analyses, total_judgeable, history_days):
    """
    生成可直接注入 prompt 的校准文本

    返回格式化的 markdown 文本，供放入 prompt 开头
    """
    lines = []
    lines.append("## 历史回测校准（自动生成）")
    lines.append("")

    has_bias = any(a["bias_found"] for a in asset_analyses.values())
    if not has_bias:
        lines.append("近期回测未发现显著系统性偏差，现有判断规则仍适用。")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"以下校准建议基于最近 {history_days} 天的回测数据（共 {total_judgeable} 次可判断样本），")
    lines.append("请在本轮分析中参考：")
    lines.append("")

    for asset_key in ["gold", "silver", "crude_oil", "usd_index"]:
        a = asset_analyses.get(asset_key)
        if not a or not a["bias_found"]:
            continue

        lines.append(f"- **{a['asset_name']}**：{a['calibration']}")

    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="CommodityMorningBrief 自动复盘校准")
    parser.add_argument("--days", type=int, default=30, help="回溯天数, 默认30")
    parser.add_argument("--output", type=str, default="data/backtest_calibration.json",
                        help="输出路径")
    args = parser.parse_args()

    history = load_backtest_history(days=args.days)
    if not history:
        print("❌ 无回测数据，无法生成校准规则")
        return

    print(f"📊 自动复盘：加载 {len(history)} 期回测数据")
    print()

    # 分析各资产
    asset_analyses = {}
    total_judgeable = 0
    for asset_key in ASSET_NAMES:
        analysis = analyze_asset_bias(history, asset_key)
        asset_analyses[asset_key] = analysis
        total_judgeable += analysis["total_samples"]

        acc = analysis["overall_accuracy"]
        acc_text = f"{acc:.1%}" if acc is not None else "N/A"
        bias_mark = " ⚠️偏差" if analysis["bias_found"] else " ✅"
        print(f"  {ASSET_NAMES[asset_key]:　<5}  {analysis['total_samples']:>3}次  {acc_text:>6}  {bias_mark}")

    # 生成可注入的 prompt 文本
    prompt_section = build_prompt_section(asset_analyses, total_judgeable, args.days)

    # 构建输出
    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "history_days": args.days,
        "history_periods": len(history),
        "total_judgeable": total_judgeable,
        "asset_analyses": {
            k: {
                "asset_name": v["asset_name"],
                "total_samples": v["total_samples"],
                "overall_accuracy": v["overall_accuracy"],
                "by_direction": v["by_direction"],
                "bias_found": v["bias_found"],
                "calibration": v["calibration"],
            }
            for k, v in asset_analyses.items()
        },
        "prompt_section": prompt_section,
    }

    output_path = os.path.join(BASE_DIR, args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 校准规则已保存: {output_path}")
    print()
    print("=" * 50)
    print("📝 可注入 Prompt 文本")
    print("=" * 50)
    print(prompt_section)


if __name__ == "__main__":
    main()
