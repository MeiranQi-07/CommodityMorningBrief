#!/usr/bin/env python3
"""
llm_analyze.py — 将原始候选新闻 (candidates.json) 经过 LLM 筛选+分析,
输出结构化 commodity_news.json

这是 run_morning_brief.sh 中缺失的第 4.5 步。
通过 openclaw infer model run 调用 LLM。
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CANDIDATES_PATH = os.path.join(DATA_DIR, "candidates.json")
COMMODITY_NEWS_PATH = os.path.join(DATA_DIR, "commodity_news.json")
FILTER_PROMPT_PATH = os.path.join(BASE_DIR, "prompts", "news_filter.md")
ANALYZE_PROMPT_PATH = os.path.join(BASE_DIR, "prompts", "impact_analyze.md")
CALIBRATION_PATH = os.path.join(DATA_DIR, "backtest_calibration.json")

MODEL = "deepseek/deepseek-v4-flash"
MAX_RETRIES = 3


def log(msg):
    print(msg, flush=True)


def load_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"  ✅ 已保存: {path}")


def llm_call(prompt, max_retries=MAX_RETRIES):
    """调用 openclaw infer model run 做一次 LLM 推理"""
    for attempt in range(1, max_retries + 1):
        try:
            result = subprocess.run(
                [
                    "openclaw", "infer", "model", "run",
                    "--model", MODEL,
                    "--prompt", prompt,
                    "--json",
                ],
                capture_output=True, text=True, timeout=180
            )
            if result.returncode != 0:
                log(f"  ⚠️ LLM 调用失败(attempt {attempt}): {result.stderr[:200]}")
                time.sleep(3)
                continue

            parsed = json.loads(result.stdout)
            texts = parsed.get("outputs", [])
            if not texts:
                log(f"  ⚠️ LLM 返回空(attempt {attempt})")
                time.sleep(3)
                continue

            output = texts[0].get("text", "")
            extracted = extract_json(output)
            if extracted is not None:
                return extracted

            log(f"  ⚠️ 未从 LLM 输出中提取到 JSON, 重试(attempt {attempt})")
            log(f"  输出预览: {output[:300]}")

        except subprocess.TimeoutExpired:
            log(f"  ⚠️ LLM 超时(attempt {attempt})")
            time.sleep(5)
        except Exception as e:
            log(f"  ⚠️ LLM 异常(attempt {attempt}): {e}")
            time.sleep(3)

    return None


def extract_json(text):
    """从 LLM 输出中提取 JSON 数组或对象"""
    text = text.strip()

    # 尝试解析整个输出
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # 尝试从 ```json ``` 中提取
    m = re.search(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 找第一个 [ 到最后一个 ]
    if "[" in text and "]" in text:
        start = text.index("[")
        end = text.rindex("]") + 1
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return None


def load_calibration():
    if os.path.exists(CALIBRATION_PATH):
        try:
            with open(CALIBRATION_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def format_calibration_for_prompt(calibration):
    if not calibration:
        return ""
    analyses = calibration.get("asset_analyses", {})
    has_bias = any(a.get("bias_found") for a in analyses.values())
    if not has_bias:
        return ""
    lines = ["## 历史回测校准（本轮生效）"]
    for asset_key in ["gold", "silver", "crude_oil", "usd_index"]:
        a = analyses.get(asset_key)
        if a and a.get("bias_found"):
            lines.append(f"- {a['asset_name']}: {a['calibration']}")
    return "\n".join(lines)


# 中文资产名 → 英文 key 映射（commodity_news.json 规范要求英文）
CHINESE_TO_ENGLISH = {
    "黄金": "gold",
    "白银": "silver",
    "原油": "crude_oil",
    "铜": "copper",
    "伦敦金": "gold",
    "伦敦银": "silver",
    "布伦特原油": "crude_oil",
    "WTI原油": "crude_oil",
    "WTI": "crude_oil",
    "美元指数": "usd_index",
    "美元": "usd_index",
    "美债收益率": "bond_yield",
    "美债": "bond_yield",
    "美股": "us_stocks",
    "日元": "jpy",
    "日本国债": "jgb",
    "韩元": "krw",
    "农产品": "agriculture",
}

def normalize_assets(assets):
    """将中文资产名转为英文 key"""
    if not isinstance(assets, list):
        return []
    result = []
    for a in assets:
        if a in CHINESE_TO_ENGLISH:
            result.append(CHINESE_TO_ENGLISH[a])
        elif a not in result:
            result.append(a)  # 保留未知的英文名
    return result


def format_news_for_prompt(news_list):
    """将新闻列表格式化为 LLM 可读文本"""
    lines = []
    for i, c in enumerate(news_list, 1):
        title = c.get("title", "").strip()
        content = c.get("content", "").strip()
        source = c.get("source", "")
        pub_time = c.get("publish_time", "")
        # 截断长内容
        if len(content) > 250:
            content = content[:250] + "..."
        important = "★" if c.get("is_important") else " "
        lines.append(
            f"[{i}] {important} [{source}] {pub_time}\n"
            f"标题: {title}\n"
            f"内容: {content}\n"
        )
    return "\n".join(lines)


def main():
    log("=" * 60)
    log("LLM 新闻筛选与分析")
    log(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    # 1. 读取候选新闻
    if not os.path.exists(CANDIDATES_PATH):
        log(f"❌ 未找到候选新闻: {CANDIDATES_PATH}")
        return 1

    candidates = json.load(open(CANDIDATES_PATH, "r", encoding="utf-8"))
    log(f"📥 候选新闻: {len(candidates)} 条")

    if len(candidates) == 0:
        log("❌ 候选新闻为空，跳过 LLM 分析")
        return 1

    # 2. LLM 筛选 — 整个候选列表一次性处理
    log("\n[LLM 筛选] 从候选新闻中筛选商品相关新闻...")
    filter_template = load_file(FILTER_PROMPT_PATH)
    
    # 如果候选太多，分批处理（每批最多 30 条）
    BATCH_SIZE = 30
    all_filtered = []
    total = len(candidates)
    
    for batch_start in range(0, total, BATCH_SIZE):
        batch = candidates[batch_start:batch_start + BATCH_SIZE]
        batch_end = min(batch_start + BATCH_SIZE, total)
        log(f"  批次 {batch_start+1}-{batch_end}/{total} ({len(batch)} 条)...")

        formatted = format_news_for_prompt(batch)
        prompt = (
            f"{filter_template}\n\n"
            f"以下为待筛选新闻（共{len(batch)}条）：\n\n"
            f"{formatted}\n\n"
            f"请逐条判断是否保留，输出 JSON 数组。"
        )
        
        result = llm_call(prompt)
        if result is None:
            log(f"  ⚠️ 批次 {batch_start+1} LLM 筛选失败，跳过该批次")
            continue

        decisions = result if isinstance(result, list) else [result]
        
        batch_filtered = 0
        for i, decision in enumerate(decisions):
            if i >= len(batch):
                break
            if isinstance(decision, dict) and decision.get("keep", False):
                news = dict(batch[i])
                news["category"] = decision.get("category", "")
                news["related_assets"] = decision.get("related_assets", [])
                all_filtered.append(news)
                batch_filtered += 1
        log(f"    该批次保留: {batch_filtered} 条")
    
    log(f"  ✅ 筛选完成: {len(all_filtered)}/{total} 条保留")

    if len(all_filtered) == 0:
        log("⚠️ 无商品相关新闻，保留原始数据不做覆盖")
        return 1
    
    # 保存中间结果（调试用）
    filtered_path = os.path.join(DATA_DIR, "filtered_news.json")
    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(all_filtered, f, ensure_ascii=False, indent=2)

    # 3. LLM 影响分析
    log("\n[LLM 分析] 分析新闻对黄金/白银/原油/铜的影响...")
    analyze_template = load_file(ANALYZE_PROMPT_PATH)
    calibration = load_calibration()
    cal_section = format_calibration_for_prompt(calibration)
    
    if cal_section:
        analyze_template = analyze_template.replace("{CALIBRATION_SECTION}", cal_section)
    else:
        analyze_template = analyze_template.replace("{CALIBRATION_SECTION}", "无历史校准数据")

    analyzed = []
    total_filtered = len(all_filtered)
    
    for batch_start in range(0, total_filtered, BATCH_SIZE):
        batch = all_filtered[batch_start:batch_start + BATCH_SIZE]
        batch_end = min(batch_start + BATCH_SIZE, total_filtered)
        log(f"  批次 {batch_start+1}-{batch_end}/{total_filtered} ({len(batch)} 条)...")

        formatted = format_news_for_prompt(batch)
        prompt = (
            f"{analyze_template}\n\n"
            f"以下为待分析新闻（共{len(batch)}条）：\n\n"
            f"{formatted}\n\n"
            f"请逐条分析输出 JSON 数组。"
        )
        
        result = llm_call(prompt)
        if result is None:
            log(f"  ⚠️ 批次 {batch_start+1} LLM 分析失败，该批次使用简化分析")
            for news in batch:
                analysis = {
                    "summary": news.get("content", "")[:200],
                    "region": "international",
                    "category": news.get("category", ""),
                    "related_assets": news.get("related_assets", []),
                    "impact_direction": "neutral",
                    "impact_strength": "medium",
                    "confidence": "low",
                    "reason": "LLM 分析未返回结果，使用默认中性判断",
                    "risk_note": "",
                }
                merged = dict(news)
                merged.update(analysis)
                merged.pop("content", None)
                merged.pop("is_important", None)
                analyzed.append(merged)
            continue

        analyses = result if isinstance(result, list) else [result]
        
        for i, analysis in enumerate(analyses):
            if i >= len(batch):
                break
            if not isinstance(analysis, dict):
                merged = dict(batch[i])
                merged.pop("content", None)
                merged.pop("is_important", None)
                analyzed.append(merged)
                continue

            merged = dict(batch[i])
            for key in ["summary", "region", "category", "related_assets",
                        "impact_direction", "impact_strength", "confidence",
                        "reason", "risk_note", "url"]:
                if key in analysis and analysis[key]:
                    merged[key] = analysis[key]
            
            # 标准化相关资产名：中文 → 英文 key
            if "related_assets" in merged:
                merged["related_assets"] = normalize_assets(merged["related_assets"])
            
            merged.setdefault("summary", merged.get("content", "")[:200])
            merged.setdefault("region", "international")
            merged.setdefault("impact_direction", "neutral")
            merged.setdefault("impact_strength", "medium")
            merged.setdefault("confidence", "low")
            merged.setdefault("reason", "")
            merged.pop("content", None)
            merged.pop("is_important", None)
            
            analyzed.append(merged)
    
    log(f"  ✅ 分析完成: {len(analyzed)} 条")

    # 4. 保存 commodity_news.json
    save_file(COMMODITY_NEWS_PATH, analyzed)
    
    log(f"\n🎉 LLM 分析完成: {len(candidates)} 候选 → {len(all_filtered)} 筛选 → {len(analyzed)} 分析")
    return 0


if __name__ == "__main__":
    sys.exit(main())
