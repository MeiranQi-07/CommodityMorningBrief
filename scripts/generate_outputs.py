import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "commodity_news.json")
DEMO_PATH = os.path.join(BASE_DIR, "data", "demo_news.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(OUTPUT_DIR, exist_ok=True)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--news_limit", type=int, default=20)
    parser.add_argument("--use_demo_news", type=str, default="false")
    parser.add_argument("--output_format", type=str, default="excel_markdown")
    parser.add_argument("--raw-candidates", type=int, default=0,
                        help="原始候选快讯总数（来自 multi_source.py）")
    return parser.parse_args()

def load_news(use_demo_news):
    path = DATA_PATH

    if (not os.path.exists(path)) and use_demo_news:
        path = DEMO_PATH

    if not os.path.exists(path):
        raise FileNotFoundError(f"未找到新闻数据文件：{path}")

    with open(path, "r", encoding="utf-8") as f:
        news = json.load(f)

    if not isinstance(news, list) or len(news) == 0:
        if use_demo_news and os.path.exists(DEMO_PATH):
            with open(DEMO_PATH, "r", encoding="utf-8") as f:
                news = json.load(f)
        else:
            raise ValueError("新闻 JSON 为空或格式不正确")

    return news

def save_excel(all_news, today):
    """Excel 输出所有相关新闻，不过滤数量"""
    rows = []

    for n in all_news:
        rows.append({
            "新闻ID": n.get("news_id", ""),
            "来源": n.get("source", ""),
            "发布时间": n.get("publish_time", ""),
            "标题": n.get("title", ""),
            "摘要": n.get("summary", ""),
            "地区": n.get("region", ""),
            "类别": n.get("category", ""),
            "相关资产": ",".join(n.get("related_assets", [])) if isinstance(n.get("related_assets", []), list) else n.get("related_assets", ""),
            "影响方向": n.get("impact_direction", ""),
            "影响强度": n.get("impact_strength", ""),
            "置信度": n.get("confidence", ""),
            "判断理由": n.get("reason", ""),
            "风险提示": n.get("risk_note", ""),
            "链接": n.get("url", "")
        })

    df = pd.DataFrame(rows)
    excel_path = os.path.join(OUTPUT_DIR, f"commodity_news_{today}.xlsx")
    df.to_excel(excel_path, index=False)
    return excel_path

def direction_label(direction):
    mapping = {
        "bullish": "可能偏多",
        "bearish": "可能偏空",
        "neutral": "中性",
        "mixed": "多空交织"
    }
    return mapping.get(direction, "中性")

def asset_name(asset):
    mapping = {
        "gold": "黄金",
        "silver": "白银",
        "crude_oil": "原油",
        "usd_index": "美元指数",
        "bond_yield": "美债收益率",
        "copper": "铜"
    }
    return mapping.get(asset, asset)

def load_backtest(today):
    """加载已有的回测结果，没有则返回 None
    优先精确匹配，匹配不上时找最近的一期。
    """
    # 先精确匹配
    for candidate in [today]:
        result_path = os.path.join(OUTPUT_DIR, f"backtest_result_{candidate}.json")
        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as f:
                return json.load(f)
    # 匹配不上时，从 output/ 找最新的 backtest_result_*.json
    import glob
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "backtest_result_*.json")), reverse=True)
    if files:
        with open(files[0], "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def load_calibration(today):
    """加载最新的校准规则"""
    cal_path = os.path.join(DATA_DIR, "backtest_calibration.json")
    if os.path.exists(cal_path):
        with open(cal_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def build_calibration_section(calibration):
    """将校准规则格式化为 Markdown 板块"""
    if not calibration:
        return []

    analyses = calibration.get("asset_analyses", {})
    has_bias = any(a.get("bias_found") for a in analyses.values())
    if not has_bias:
        return []

    lines = []
    lines.append("## 模型自我复盘")
    lines.append("")
    lines.append(f"基于 {calibration.get('history_periods', 0)} 期回测数据（{calibration.get('total_judgeable', 0)} 次可判断样本）：")
    lines.append("")

    for asset_key in ["gold", "silver", "crude_oil", "usd_index"]:
        a = analyses.get(asset_key)
        if a and a.get("bias_found"):
            lines.append(f"- **{a['asset_name']}** ⚠️ {a['calibration']}")

    lines.append("")
    lines.append("以上偏差规则将在下次分析新闻时自动注入 LLM 判断逻辑。")
    lines.append("")

    return lines


def build_backtest_section(backtest_result):
    """将回测结果格式化为 Markdown 板块"""
    if not backtest_result:
        return []

    lines = []
    lines.append("## 回测验证")
    lines.append("")
    lines.append("基于新浪财经公开行情数据，对上一交易日新闻判断进行回测验证：")
    lines.append("")

    # 整体指标
    overall_acc = backtest_result.get("overall_accuracy")
    acc_text = f"{overall_acc:.1%}" if overall_acc is not None else "暂无数据"
    total_judge = backtest_result.get("total_judgeable", 0)
    total_correct = backtest_result.get("total_correct", 0)
    total_news = backtest_result.get("total_news", 0)

    lines.append(f"- **回测日期**：{backtest_result.get('backtest_date', '未知')}")

    lines.append("")
    lines.append("### 整体准确率")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"| --- | --- |")
    lines.append(f"| 新闻总数 | {total_news} 条 |")
    lines.append(f"| 可判断新闻 | {total_judge} 条 |")
    lines.append(f"| 判断正确 | {total_correct} 条 |")
    lines.append(f"| **整体准确率** | **{acc_text}** |")

    # 逐资产明细
    asset_results = backtest_result.get("asset_results", {})
    if asset_results:
        lines.append("")
        lines.append("### 各资产回测明细")
        lines.append("")
        lines.append("| 资产 | 昨开 | 昨收 | 涨跌幅 | 可判断 | 正确 | 准确率 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")

        name_map = {"gold": "黄金", "silver": "白银", "crude_oil": "原油", "usd_index": "美元指数"}
        for asset_key in ["gold", "silver", "crude_oil", "usd_index"]:
            ar = asset_results.get(asset_key, {})
            if ar and ar.get("count", 0) > 0:
                acc_ar = ar.get("accuracy")
                acc_ar_text = f"{acc_ar:.1%}" if acc_ar is not None else "-"
                open_p = ar.get("actual_open_price")
                close_p = ar.get("actual_close_price")
                change = ar.get("actual_change_pct")
                open_text = f"{open_p:.2f}" if open_p else "-"
                close_text = f"{close_p:.2f}" if close_p else "-"
                change_text = f"{change:+.2f}%" if change is not None else "-"
                lines.append(
                    f"| {name_map.get(asset_key, asset_key)} | {open_text} | "
                    f"{close_text} | {change_text} | "
                    f"{ar.get('judgeable', 0)} | {ar.get('correct', 0)} | "
                    f"{acc_ar_text} |"
                )

    lines.append("")
    lines.append("数据来源：新浪财经（COMEX黄金/白银、WTI原油、美元指数）")
    lines.append("")

    return lines


def build_asset_summary(news_list, asset):
    related = []

    for n in news_list:
        assets = n.get("related_assets", [])
        if isinstance(assets, list) and asset in assets:
            related.append(n)

    name = asset_name(asset)

    if not related:
        return f"当前新闻中未发现对{name}的明显直接影响，需继续观察美元、利率和避险情绪变化。"

    bullish = sum(1 for n in related if n.get("impact_direction") == "bullish")
    bearish = sum(1 for n in related if n.get("impact_direction") == "bearish")
    mixed = sum(1 for n in related if n.get("impact_direction") == "mixed")

    if bullish > bearish:
        tendency = "整体可能偏多"
    elif bearish > bullish:
        tendency = "整体可能偏空"
    elif mixed > 0:
        tendency = "多空交织"
    else:
        tendency = "整体中性"

    key_reasons = [n.get("reason", "") for n in related[:3] if n.get("reason")]
    reason_text = "；".join(key_reasons) if key_reasons else "相关新闻影响方向尚不明确。"

    return f"{name}相关快讯共 {len(related)} 条，{tendency}。主要依据：{reason_text}"

def fetch_overnight_prices():
    """获取隔夜行情数据 — 统一通过 akshare"""
    rows = []

    import akshare as ak

    # 核心品种定义 (akshare symbol)
    ASSETS = [
        {"key": "gold",     "name": "伦敦金",   "unit": "美元/盎司", "close_hour": "02:30", "ak_symbol": "GC"},
        {"key": "silver",   "name": "伦敦银",   "unit": "美元/盎司", "close_hour": "02:30", "ak_symbol": "SI"},
        {"key": "crude_oil","name": "布伦特原油","unit": "美元/桶",   "close_hour": "02:30", "ak_symbol": "OIL"},
        {"key": "copper",   "name": "伦敦铜",   "unit": "美元/吨",   "close_hour": "01:00", "ak_symbol": "CAD"},
        {"key": "usd_index","name": "美元指数",  "unit": "",        "close_hour": "",     "ak_symbol": None},
    ]

    for a in ASSETS:
        last_close = None
        current = None

        if a["ak_symbol"]:
            try:
                df = ak.futures_foreign_commodity_realtime(symbol=a["ak_symbol"])
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    # akshare 返回: 名称, 最新价, 涨跌额, 涨跌幅, 开盘价, 最高价, 最低价, 昨日结算价, ...
                    current = float(row["最新价"])
                    # 昨收 = 昨日结算价
                    prev_close = row.get("昨日结算价")
                    if prev_close is not None and prev_close != "":
                        last_close = float(prev_close)
            except Exception:
                pass

        a["last_close"] = last_close
        a["current"] = current

        # 计算涨跌幅
        change_pct = None
        if last_close and current:
            change_pct = round((current - last_close) / last_close * 100, 2)

        # 距夜盘收盘时长
        hours_ago = ""
        if a["close_hour"]:
            try:
                h, m = a["close_hour"].split(":")
                close_dt = datetime.now().replace(hour=int(h), minute=int(m), second=0)
                if close_dt > datetime.now():
                    close_dt -= timedelta(days=1)
                diff = datetime.now() - close_dt
                hours_ago = f"{int(diff.total_seconds() // 3600)}h"
            except:
                pass

        rows.append({
            "name": a["name"],
            "unit": a["unit"],
            "last_close": last_close,
            "current": current,
            "change_pct": change_pct,
            "hours_ago": hours_ago,
            "close_hour": a["close_hour"],
        })

    return rows


def build_overnight_table(price_rows):
    """渲染隔夜行情速览 Markdown 表格"""
    if not price_rows:
        return []

    lines = []
    lines.append("## 一、隔夜行情速览")
    lines.append("")
    lines.append(f"数据时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}（北京时间）")
    lines.append("")
    lines.append("| 品种 | 昨收 | 最新 | 涨跌幅 | 距夜盘收盘 |")
    lines.append("| --- | --- | --- | --- | --- |")

    for r in price_rows:
        name = r["name"]
        last = f"{r['last_close']:.2f}" if r["last_close"] is not None else "—"
        curr = f"{r['current']:.2f}" if r["current"] is not None else "—"
        if r["change_pct"] is not None:
            icon = "🔺" if r["change_pct"] > 0 else "🔻"
            change = f"{icon} {r['change_pct']:+.2f}%"
        else:
            change = "—"
        gap = f"{r['hours_ago']}（{r['close_hour']}收）" if r["hours_ago"] else "—"

        lines.append(f"| {name} | {last} | {curr} | {change} | {gap} |")

    lines.append("")
    lines.append("注：昨收为国内夜盘收盘时对应国际合约的结算价；最新价为当前国际现货/期货报价。")
    lines.append("")

    return lines


def build_focus_section(all_news):
    """从新闻中提取今日关注因素（动态生成，替代静态文案）"""
    lines = []
    lines.append("## 今日关注因素")
    lines.append("")

    # 提取新闻中的关键宏观事件
    event_keywords = [
        ("美联储|褐皮书|鲍威尔|利率决议", "美联储政策动向"),
        ("非农|ADP|就业|CPI|PPI|通胀", "宏观经济数据"),
        ("伊朗|中东|霍尔木兹|封锁|制裁|冲突", "地缘政治风险"),
        ("OPEC|原油|EIA|库存", "原油供需变化"),
        ("谈判|协议|停火|关税|贸易", "谈判与政策进展"),
    ]

    from collections import Counter
    cat_hits = Counter()
    for n in all_news:
        text = n.get("title", "") + " " + n.get("summary", "")
        for pattern, label in event_keywords:
            import re
            if re.search(pattern, text):
                cat_hits[label] += 1

    if cat_hits:
        lines.append("本报告期间市场关注以下方向：")
        lines.append("")
        for label, count in cat_hits.most_common():
            if count >= 2:
                lines.append(f"- **{label}** — {count} 条相关快讯")

    # 提取每日的关键数据/事件时间点
    calendar_items = []
    for n in all_news:
        summary = n.get("summary", "") + " " + n.get("title", "")
        if "重点关注" in summary or "关注财经事件" in summary or "关键数据" in summary:
            # 提取具体事件
            parts = [p.strip() for p in summary.split("；") if "美联储" in p or "利率" in p or "数据" in p or "讲话" in p]
            calendar_items.extend(parts[:3])

    if calendar_items:
        lines.append("")
        lines.append("今日将公布的关注事件：")
        lines.append("")
        for item in calendar_items[:3]:
            lines.append(f"- {item[:80]}")

    # 风险等级评估
    bullish_assets = set()
    bearish_assets = set()
    for n in all_news:
        if n.get("impact_direction") == "bullish":
            bullish_assets.update(n.get("related_assets", []))
        elif n.get("impact_direction") == "bearish":
            bearish_assets.update(n.get("related_assets", []))

    lines.append("")
    risk_items = []
    if "crude_oil" in bullish_assets:
        risk_items.append("原油供给风险偏高（地缘冲突 + 库存下降 + 海峡封锁）")
    if "crude_oil" in bearish_assets:
        risk_items.append("原油下行风险（美伊谈判进展 + 封锁解除预期）")
    if "gold" in bullish_assets and "gold" in bearish_assets:
        risk_items.append("黄金多空分歧加大（避险支撑 vs 强美元利率压制）")
    if risk_items:
        lines.append("需重点关注：")
        for item in risk_items[:3]:
            lines.append(f"- {item}")

    lines.append("")
    return lines


def importance_score(news):
    """综合 impact_strength + confidence 打分，用于排序"""
    strength_map = {"high": 10, "medium": 5, "low": 1}
    conf_map = {"high": 1.0, "medium": 0.85, "low": 0.6}
    s = strength_map.get(news.get("impact_strength", "low"), 1)
    c = conf_map.get(news.get("confidence", "low"), 0.6)
    return s * c


def build_report(all_news, today, use_demo_news, raw_candidates=0):
    """报告只取前10条最重要的新闻，按综合评分排序"""
    sorted_news = sorted(all_news, key=importance_score, reverse=True)
    top_news = sorted_news[:10]
    total = len(all_news)
    domestic = sum(1 for n in top_news if n.get("region") == "domestic")
    international = sum(1 for n in top_news if n.get("region") == "international")

    assets = set()
    for n in top_news:
        related_assets = n.get("related_assets", [])
        if isinstance(related_assets, list):
            assets.update(related_assets)

    directions = [n.get("impact_direction", "neutral") for n in top_news]
    bullish = directions.count("bullish")
    bearish = directions.count("bearish")
    mixed = directions.count("mixed")

    if bullish > bearish:
        overall = "整体可能偏多"
    elif bearish > bullish:
        overall = "整体可能偏空"
    elif mixed > 0:
        overall = "多空交织"
    else:
        overall = "整体中性"

    lines = []
    lines.append("# 金银贵金属与大宗商品开盘前简报")
    lines.append("")

    # 隔夜行情速览（置顶显示）
    price_rows = fetch_overnight_prices()
    ov_lines = build_overnight_table(price_rows)
    if ov_lines:
        lines.extend(ov_lines)

    lines.append("## 系统说明")
    lines.append("")
    lines.append("本报告由 CommodityMorningBrief Skill 自动生成。系统基于第一财经、财联社等公开新闻 API，LLM 与 Python 脚本，采集沪金/沪银夜盘收盘后（02:30）至早间开盘前（08:30）的国际市场变化和黄金、白银、铜、原油等大宗商品相关新闻，结合新浪财经行情数据进行对比分析，并附带历史回测校准框架。本报告仅用于课程实验展示，不构成投资建议。")

    if use_demo_news:
        lines.append("")
        lines.append("数据说明：本次使用演示新闻数据完成流程，结果主要用于展示系统运行逻辑。")

    lines.append("")
    lines.append("## 二、新闻概览")
    lines.append("")
    if raw_candidates:
        lines.append(f"- 候选快讯总数：{raw_candidates} 条原始快讯 → LLM 筛选 **{total} 条**商品相关快讯（全部见 Excel 附件）")
    else:
        lines.append(f"- 候选快讯总数：{total} 条（全部相关快讯见 Excel 附件）")
    lines.append(f"- 重点新闻：10 条")
    lines.append(f"- 国内新闻：{domestic} 条")
    lines.append(f"- 国际新闻：{international} 条")
    lines.append(f"- 涉及资产：{'、'.join(asset_name(a) for a in sorted(assets)) if assets else '暂无'}")
    lines.append(f"- 整体影响倾向：{overall}")
    lines.append("")
    lines.append(f"## 三、重点新闻摘要（共{total}条相关快讯，以下为10条最重要的）")
    lines.append("")

    for n in top_news:
        assets_text = "、".join(asset_name(a) for a in n.get("related_assets", [])) if isinstance(n.get("related_assets", []), list) else ""
        lines.append(
            f"- 【{n.get('source', '未知来源')}｜{direction_label(n.get('impact_direction'))}｜{assets_text}】"
            f"{n.get('title', '未命名新闻')}：{n.get('summary', '')}"
        )

    lines.append("")
    lines.append("## 四、黄金影响分析")
    lines.append("")
    lines.append(build_asset_summary(all_news, "gold"))
    lines.append("")
    lines.append("## 五、白银影响分析")
    lines.append("")
    lines.append(build_asset_summary(all_news, "silver"))
    lines.append("")
    lines.append("## 六、原油与大宗商品影响分析")
    lines.append("")
    lines.append(build_asset_summary(all_news, "crude_oil"))
    # 动态今日关注板块
    focus_lines = build_focus_section(all_news)
    lines.append("")
    lines.extend(focus_lines)

    # 回测验证板块（昨日数据）
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    bt_result = load_backtest(yesterday)
    bt_lines = build_backtest_section(bt_result)
    if bt_lines:
        lines.append("")
        lines.extend(bt_lines)

    # 模型自我复盘板块
    calibration = load_calibration(today)
    cal_lines = build_calibration_section(calibration)
    if cal_lines:
        lines.append("")
        lines.extend(cal_lines)

    lines.append("## 风险提示")
    lines.append("")
    lines.append("本报告仅基于公开新闻和 LLM 文本分析生成，未接入真实交易账户，也不执行任何自动化交易。新闻影响倾向不等同于价格预测，相关结果仅用于课程实验展示和市场观察，不构成投资建议。")



    report_path = os.path.join(OUTPUT_DIR, f"morning_brief_{today}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return report_path

def main():
    args = parse_args()
    today = datetime.now().strftime("%Y%m%d")
    use_demo = args.use_demo_news.lower() == "true"

    all_news = load_news(use_demo_news=use_demo)

    # Excel: 输出所有相关新闻
    excel_path = save_excel(all_news, today)

    # 报告: 只取前10条最重要的
    report_path = build_report(all_news, today, use_demo_news=use_demo,
                                raw_candidates=args.raw_candidates)

    log_path = os.path.join(OUTPUT_DIR, "run_log.txt")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"运行时间：{datetime.now()}\n")
        f.write(f"候选快讯总数：{len(all_news)}\n")
        f.write(f"Excel 输出（全部）：{excel_path}\n")
        f.write(f"简报输出（10条最重要）：{report_path}\n")

    print("金银商品早报生成完成")
    print(f"Excel 文件（全部{len(all_news)}条）：{excel_path}")
    print(f"简报文件（10条最重要）：{report_path}")
    print(f"运行日志：{log_path}")

if __name__ == "__main__":
    main()
