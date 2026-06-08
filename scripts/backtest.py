#!/usr/bin/env python3
"""
backtest.py — 历史回测：评估 LLM 新闻判断 vs 实际行情

设计说明：
本脚本由团队另一位同学（人B）使用 Codex 完成开发。
已提供完整框架和 JSON Schema，人B 只需填充具体的行情数据获取逻辑。

数据流：
  data/commodity_news.json  ← LLM 分析的新闻判断
  (行情历史数据)             ← 从免费 API 获取实际价格
  ↓
  backtest.py 对比分析
  ↓
  output/backtest_result.json  ← 准确率统计
  output/backtest_report.md    ← 可读报告

用法:
  python3 scripts/backtest.py                    # 分析最新一期
  python3 scripts/backtest.py --days 7           # 分析最近 7 天
  python3 scripts/backtest.py --from 20260501    # 从指定日期开始
"""

import argparse
import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timedelta

import akshare as ak

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "scripts" else SCRIPT_DIR
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ========== 行情数据获取 ==========

PRICE_ASSETS = {
    "gold": {
        "symbol": "GC",
        "name": "COMEX黄金连续",
        "kind": "akshare_hist",
    },
    "silver": {
        "symbol": "SI",
        "name": "COMEX白银连续",
        "kind": "akshare_hist",
    },
    "crude_oil": {
        "symbol": "CL",
        "name": "WTI原油连续",
        "kind": "akshare_hist",
    },
    "usd_index": {
        "symbol": "DINIW",
        "name": "美元指数",
        "kind": "sina_forex",
    },
}

_PRICE_SERIES_CACHE = {}


def _load_akshare_hist(symbol):
    """通过 akshare 获取外盘期货日K线"""
    df = ak.futures_foreign_hist(symbol=symbol)
    if df is None or df.empty:
        return {}
    result = {}
    for _, row in df.iterrows():
        d = row.get("date")
        if d is None:
            continue
        # Timestamp 转为 YYYY-MM-DD 字符串
        if hasattr(d, "strftime"):
            date_str = d.strftime("%Y-%m-%d")
        else:
            date_str = str(d)[:10]
        result[date_str] = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
    return result


def _load_sina_forex(symbol):
    """保留：美元指数（akshare 不覆盖）"""
    url = (
        "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/"
        f"var%20_{symbol}=/NewForexService.getDayKLine?symbol={symbol}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CommodityMorningBrief/1.0)",
        "Referer": "https://finance.sina.com.cn/",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception:
        cmd = ["curl", "-L", "-s", "--max-time", "20",
               "-H", "User-Agent: Mozilla/5.0",
               "-H", "Referer: https://finance.sina.com.cn/",
               url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"curl exited with {result.returncode}")
        raw = result.stdout

    match = re.search(r"=\((.*)\);\s*$", raw, re.S)
    if not match:
        raise ValueError("无法解析美元指数 JSONP 响应")
    payload = match.group(1).strip()
    if payload == "null":
        return {}

    rows_text = json.loads(payload)
    result = {}
    for row_text in rows_text.split("|"):
        parts = [part for part in row_text.split(",") if part]
        if len(parts) < 5:
            continue
        date_str, open_price, low_price, high_price, close_price = parts[:5]
        result[date_str] = {
            "open": float(open_price),
            "high": float(high_price),
            "low": float(low_price),
            "close": float(close_price),
        }
    return result


def _load_price_series(asset_config):
    symbol = asset_config["symbol"]
    cache_key = (asset_config["kind"], symbol)
    if cache_key in _PRICE_SERIES_CACHE:
        return _PRICE_SERIES_CACHE[cache_key]

    if asset_config["kind"] == "akshare_hist":
        data = _load_akshare_hist(symbol)
    elif asset_config["kind"] == "sina_forex":
        data = _load_sina_forex(symbol)
    else:
        raise ValueError(f"未知行情源: {asset_config['kind']}")

    _PRICE_SERIES_CACHE[cache_key] = data
    return data


def fetch_historical_price(asset, date):
    """
    获取指定资产在指定日期的实际涨跌幅

    参数:
        asset: str — 'gold', 'silver', 'crude_oil', 'usd_index'
        date: str — 'YYYYMMDD' 格式日期

    返回:
        dict — {'change_pct': float, 'close_price': float, 'open_price': float}
        或 None (数据不可用)
    """
    try:
        asset_config = PRICE_ASSETS.get(asset)
        if not asset_config:
            print(f"  ⚠️  未支持的资产: {asset}")
            return None

        target_date = datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")
        series = _load_price_series(asset_config)
        row = series.get(target_date)
        if not row:
            return None

        open_price = row["open"]
        close_price = row["close"]
        if open_price == 0:
            return None

        change_pct = (close_price - open_price) / open_price * 100
        return {
            "change_pct": round(change_pct, 4),
            "close_price": close_price,
            "open_price": open_price,
            "high_price": row["high"],
            "low_price": row["low"],
            "trade_date": target_date,
            "symbol": asset_config["symbol"],
            "source": f"新浪财经 - {asset_config['name']}",
        }

    except Exception as e:
        print(f"  ⚠️  获取 {asset} {date} 行情失败: {e}")
        return None


def fetch_multiday_prices(assets, start_date, days):
    """
    [人B 可选实现] 批量获取多日行情数据，减少 API 调用次数
    """
    results = {}
    for asset in assets:
        results[asset] = {}
        for i in range(days):
            d = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=i)).strftime("%Y%m%d")
            price = fetch_historical_price(asset, d)
            if price:
                results[asset][d] = price
    return results


# ========== 核心分析逻辑 ==========

def load_news(date_str):
    """加载指定日期的新闻 JSON"""
    path = os.path.join(DATA_DIR, "commodity_news.json")
    if not os.path.exists(path):
        # 尝试按日期查找历史文件
        alt_path = os.path.join(DATA_DIR, f"commodity_news_{date_str}.json")
        if os.path.exists(alt_path):
            path = alt_path
        else:
            # 使用最新的 JSON
            if os.path.exists(path):
                print(f"  使用最新 data/commodity_news.json (非特定日期)")
            else:
                print(f"  ❌ 未找到新闻数据: {path}")
                return None

    with open(path, "r", encoding="utf-8") as f:
        news = json.load(f)

    if not isinstance(news, list):
        print(f"  ⚠️  JSON 格式错误, 期望数组")
        return None

    return news


def analyze_asset_accuracy(news_list, asset, date_str=None):
    """分析单一资产的 LLM 判断准确率"""
    related = []
    for n in news_list:
        assets = n.get("related_assets", [])
        if isinstance(assets, list) and asset in assets:
            related.append(n)

    if not related:
        return {
            "asset": asset,
            "count": 0,
            "judgeable": 0,
            "correct": 0,
            "accuracy": None,
            "actual_change_pct": None,
            "actual_trade_date": None,
            "detail": [],
        }

    # 获取实际行情 (需要日期)
    price_date = date_str or datetime.now().strftime("%Y%m%d")
    actual = fetch_historical_price(asset, price_date)

    detail = []
    correct = 0
    for n in related:
        direction = n.get("impact_direction", "neutral")
        # 判断规则:
        #   bullish → 实际涨 → 正确
        #   bearish → 实际跌 → 正确
        #   neutral/mixed → 视为中性, 不纳入准确率统计
        is_correct = None
        if actual and actual.get("change_pct") is not None:
            change = actual["change_pct"]
            if direction == "bullish":
                is_correct = change > 0
            elif direction == "bearish":
                is_correct = change < 0
            # mixed/neutral 不判断对错

        if is_correct is True:
            correct += 1
        elif is_correct is False:
            pass

        detail.append({
            "news_id": n.get("news_id", ""),
            "direction": direction,
            "actual_change": actual["change_pct"] if actual else None,
            "is_correct": is_correct,
        })

    # 计算准确率 (只统计 bullish/bearish 的判断)
    judgeable = [d for d in detail if d["is_correct"] is not None]
    accuracy = round(correct / len(judgeable), 4) if judgeable else None

    return {
        "asset": asset,
        "count": len(related),
        "judgeable": len(judgeable),
        "correct": correct,
        "accuracy": accuracy,
        "actual_change_pct": actual["change_pct"] if actual else None,
        "actual_open_price": actual["open_price"] if actual else None,
        "actual_close_price": actual["close_price"] if actual else None,
        "actual_trade_date": actual["trade_date"] if actual else None,
        "detail": detail,
    }


def run_backtest(date_str=None, days=1):
    """运行回测"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    print(f"📊 运行回测: 日期={date_str}")
    print()

    # 1. 加载新闻
    print("📰 加载新闻数据...")
    news = load_news(date_str)
    if not news:
        print("❌ 回测中止: 无有效新闻数据")
        return
    print(f"   ✅ 加载 {len(news)} 条新闻")

    # 2. 按资产分析
    print("📈 分析各资产预测准确率...")
    assets = ["gold", "silver", "crude_oil", "usd_index"]
    results = {}
    for asset in assets:
        print(f"   分析 {asset}...")
        result = analyze_asset_accuracy(news, asset, date_str)
        results[asset] = result
        count = result["count"]
        acc = result["accuracy"]
        if acc is not None:
            print(f"      {count} 条相关, 准确率: {acc:.1%}")
        elif count > 0:
            print(f"      {count} 条相关, 暂无法判断准确率")

    # 3. 生成汇总
    total_judgeable = sum(r["judgeable"] for r in results.values())
    total_correct = sum(r["correct"] for r in results.values())
    overall_accuracy = round(total_correct / total_judgeable, 4) if total_judgeable > 0 else None

    summary = {
        "backtest_date": date_str,
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_news": len(news),
        "total_judgeable": total_judgeable,
        "total_correct": total_correct,
        "overall_accuracy": overall_accuracy,
        "asset_results": results,
    }

    # 4. 保存
    result_path = os.path.join(OUTPUT_DIR, f"backtest_result_{date_str}.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 回测结果已保存: {result_path}")

    # 5. 输出摘要
    print(f"\n{'='*50}")
    print(f"📋 回测摘要")
    print(f"{'='*50}")
    print(f"   日期: {date_str}")
    print(f"   新闻总数: {len(news)}")
    print(f"   可判断: {total_judgeable} 条")
    print(f"   判断正确: {total_correct} 条")
    if overall_accuracy is not None:
        print(f"   整体准确率: {overall_accuracy:.1%}")
    print()

    return summary


def main():
    parser = argparse.ArgumentParser(description="CommodityMorningBrief 历史回测工具")
    parser.add_argument("--date", type=str, help="分析日期 YYYYMMDD, 默认今天")
    parser.add_argument("--days", type=int, default=1, help="回看天数, 默认1")
    parser.add_argument("--from", dest="from_date", type=str, help="起始日期 YYYYMMDD")
    args = parser.parse_args()

    if args.from_date:
        from_date = args.from_date
        days = args.days or 7
        print(f"📊 批量回测: {from_date} 起 {days} 天")
        for i in range(days):
            d = (datetime.strptime(from_date, "%Y%m%d") + timedelta(days=i)).strftime("%Y%m%d")
            print(f"\n--- 回测日期: {d} ---")
            run_backtest(date_str=d)
    else:
        run_backtest(date_str=args.date, days=args.days)


if __name__ == "__main__":
    main()
