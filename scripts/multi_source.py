#!/usr/bin/env python3
"""
multi_source.py — 多数据源新闻采集

设计说明：
本脚本由团队另一位同学（人B）使用 Codex 完成开发。
已提供完整框架，人B 只需实现各数据源的具体抓取逻辑。

目标：聚合多个新闻源，输出统一格式的 JSON，与 commodityreport 兼容。

数据源 (人B 可增删):
  1. 第一财经快讯 API (已有, 保留)
  2. 财联社快讯 (cls.cn)
  3. 金十数据 (jin10.com) [需人B 实现, 可选]
  4. 华尔街见闻 (wallstreetcn.com) [需人B 实现, 可选]

输出格式:
  [
    {
      "news_id": "src_001",
      "source": "财联社",
      "publish_time": "2026-05-19 06:30",
      "title": "...",
      "url": "https://...",
      "content": "...",
      "is_important": true
    },
    ...
  ]

用法:
  python3 scripts/multi_source.py                           # 使用默认时间窗口
  python3 scripts/multi_source.py --window_start "2026-05-1803:00"
  python3 scripts/multi_source.py --source cls              # 只抓财联社
  python3 scripts/multi_source.py --output data/candidates.json
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "scripts" else SCRIPT_DIR
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ========== 公共工具 ==========

def fetch_url(url, timeout=15, headers=None):
    """通用 GET 请求"""
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.yicai.com/",
    }
    if headers:
        request_headers.update(headers)

    req = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        cmd = ["curl", "-L", "-s", "--max-time", str(timeout)]
        for key, value in request_headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
        cmd.append(url)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
            if result.returncode == 0 and result.stdout:
                return result.stdout
            print(f"  ⚠️  {url} → {result.stderr.strip() or e}")
        except Exception as curl_error:
            print(f"  ⚠️  {url} → {e}; curl兜底失败: {curl_error}")
        return None


def parse_time_window(args):
    """计算时间窗口"""
    now = datetime.now()
    report_date = args.date or now.strftime("%Y-%m-%d")
    rd = datetime.strptime(report_date, "%Y-%m-%d")

    if args.window_start and args.window_end:
        ws = datetime.strptime(args.window_start, "%Y-%m-%d %H:%M")
        we = datetime.strptime(args.window_end, "%Y-%m-%d %H:%M")
    else:
        # 夜盘收盘后至早上开盘前：分析这个 gap 里的国际盘变化
        ws = rd.replace(hour=2, minute=30, second=0)  # 当日 02:30（沪金夜盘收盘）
        we = rd.replace(hour=8, minute=30, second=0)  # 当日 08:30（留30min看报告）

    return ws, we


# ========== 新闻源 1: 第一财经快讯 API (已有, 保留) ==========

def fetch_yicai(window_start, window_end, max_pages=100):
    """
    第一财经快讯 API
    URL: https://www.yicai.com/api/ajax/getbrieflist?page=N&count=100
    已实现, 保留
    """
    print("  📡 第一财经快讯...")
    all_items = []
    base_url = "https://www.yicai.com/api/ajax/getbrieflist"

    for page in range(1, max_pages + 1):
        url = f"{base_url}?page={page}&count=100"
        raw = fetch_url(url)
        if not raw:
            break

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            break

        items = data if isinstance(data, list) else data.get("list", data.get("data", []))
        if not items or not isinstance(items, list):
            break

        found_old = False
        for item in items:
            date_str = item.get("datekey", "")
            time_str = item.get("hm", "")
            if not date_str or not time_str:
                continue

            # datekey 格式: "2026.05.21" → "2026-05-21"
            date_str = date_str.replace(".", "-")
            try:
                pub_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue

            if pub_time > window_end:
                continue
            if pub_time < window_start:
                found_old = True
                continue

            content = item.get("LiveContent", "")
            # 清理 HTML 标签
            content = re.sub(r"<[^>]+>", "", content).strip()
            title = item.get("LiveTitle", "").strip() or content[:60]

            all_items.append({
                "news_id": f"yicai_{item.get('id', f'p{page}_{len(all_items)}')}",
                "source": "第一财经",
                "publish_time": pub_time.strftime("%Y-%m-%d %H:%M"),
                "title": title,
                "url": "",
                "content": content,
                "is_important": item.get("IsImportant", False),
            })

        if found_old:
            break

    print(f"     ✅ 获取 {len(all_items)} 条")
    return all_items


# ========== 新闻源 2: 财联社快讯 ==========

def cls_sort_key(key):
    """复刻财联社前端的参数排序：按大写字符串排序。"""
    return str(key).upper()


def cls_flatten_param(key, value):
    if value is None:
        return ""

    if isinstance(value, bool):
        return f"{key}={str(value).lower()}"

    if isinstance(value, (str, int, float)):
        return f"{key}={value}"

    if isinstance(value, list):
        if not value:
            return f"{key}[]"
        parts = []
        for index, item in enumerate(value):
            parts.append(cls_flatten_param(f"{key}[{index}]", item))
        return "&".join(part for part in parts if part)

    if isinstance(value, dict):
        parts = []
        for sub_key in sorted(value, key=cls_sort_key):
            parts.append(cls_flatten_param(f"{key}[{sub_key}]", value[sub_key]))
        return "&".join(part for part in parts if part)

    return f"{key}={value}"


def cls_sign(params):
    parts = []
    for key in sorted(params, key=cls_sort_key):
        parts.append(cls_flatten_param(key, params[key]))
    query = "&".join(part for part in parts if part)
    sha1_hex = hashlib.sha1(query.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1_hex.encode("utf-8")).hexdigest()


def build_cls_url(path, params):
    signed_params = dict(params)
    signed_params.setdefault("os", "web")
    signed_params.setdefault("sv", "8.7.9")
    signed_params.setdefault("app", "CailianpressWeb")
    signed_params["sign"] = cls_sign(signed_params)
    return "https://www.cls.cn" + path + "?" + urllib.parse.urlencode(signed_params)


def clean_cls_text(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_cls(window_start, window_end):
    """
    财联社快讯抓取

    财联社快讯页面: https://www.cls.cn/telegraph
    API 接口(可能需要抓包):
      https://www.cls.cn/api/sw?app=CailianpressWeb&os=web&sv=8.6.0&...
      或 https://www.cls.cn/v1/roll/get_roll_list?...

    实现提示:
      1. 尝试用 web_fetch 获取页面内容
      2. 或者使用 curl 调用财联社 API
      3. 财联社页面是动态加载的, 需找到真实 API 接口
      4. 注意反爬策略 (headers/cookie)

    Codex prompt 建议:
        "Write a Python function to fetch financial news headlines
         from cls.cn (Cailianshe) for a given time window.
         Use requests library with proper headers.
         Return a list of dicts with keys: news_id, source, publish_time,
         title, url, content, is_important."

    返回: list[dict] 统一格式
    """
    print("  📡 财联社快讯...")
    all_items = []
    page_size = 20
    max_pages = 20
    last_time = int(window_end.timestamp())

    for page in range(1, max_pages + 1):
        url = build_cls_url("/v1/roll/get_roll_list", {
            "refresh_type": 1,
            "rn": page_size,
            "last_time": last_time,
        })
        raw = fetch_url(url, headers={"Referer": "https://www.cls.cn/telegraph"})
        if not raw:
            break

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print("     ⚠️ 财联社返回非 JSON")
            break

        if str(data.get("errno")) not in ("0", "200"):
            print(f"     ⚠️ 财联社接口错误: {data.get('errno')} {data.get('msg')}")
            break

        rows = data.get("data", {}).get("roll_data", [])
        if not isinstance(rows, list) or not rows:
            break

        found_old = False
        oldest_ctime = last_time
        for item in rows:
            ctime = item.get("ctime")
            if not ctime:
                continue

            pub_time = datetime.fromtimestamp(int(ctime))
            oldest_ctime = min(oldest_ctime, int(ctime))
            if pub_time > window_end:
                continue
            if pub_time < window_start:
                found_old = True
                continue

            item_id = item.get("id", f"{int(ctime)}_{len(all_items)}")
            content = clean_cls_text(item.get("content") or item.get("brief") or "")
            title = clean_cls_text(item.get("title") or item.get("brief") or content[:60])
            level = str(item.get("level", "")).upper()
            url = item.get("shareurl") or f"https://www.cls.cn/detail/{item_id}"

            all_items.append({
                "news_id": f"cls_{item_id}",
                "source": "财联社",
                "publish_time": pub_time.strftime("%Y-%m-%d %H:%M"),
                "title": title,
                "url": url,
                "content": content,
                "is_important": level in ("A", "B") or bool(item.get("bold")),
            })

        if found_old or oldest_ctime >= last_time:
            break
        last_time = oldest_ctime

    print(f"     ✅ 获取 {len(all_items)} 条")
    return all_items


# ========== 新闻源 3: 金十数据 [TODO 人B, 可选] ==========

def fetch_jin10(window_start, window_end):
    """
    [TODO 人B 可选] 金十数据快讯

    金十数据: https://www.jin10.com/
    API (可能): https://cdn-ali.jin10.com/...

    可选实现, 非必需
    """
    return []


# ========== 主流程 ==========

SOURCES = {
    "yicai": ("第一财经", fetch_yicai),
    "cls": ("财联社", fetch_cls),
    "jin10": ("金十数据", fetch_jin10),
}


def main():
    parser = argparse.ArgumentParser(description="多数据源新闻采集")
    parser.add_argument("--date", type=str, help="报告日期 YYYY-MM-DD")
    parser.add_argument("--window_start", type=str, help="时间窗口开始 YYYY-MM-DD HH:MM")
    parser.add_argument("--window_end", type=str, help="时间窗口结束 YYYY-MM-DD HH:MM")
    parser.add_argument("--source", type=str, default="all",
                        help="数据源: yicai/cls/jin10/all (默认所有)")
    parser.add_argument("--output", type=str, default="data/candidates.json",
                        help="输出路径")
    args = parser.parse_args()

    ws, we = parse_time_window(args)
    print(f"📡 多数据源新闻采集")
    print(f"   时间窗口: {ws} ~ {we}")
    print()

    all_news = []
    sources_to_run = list(SOURCES.keys()) if args.source == "all" else [args.source]

    for src in sources_to_run:
        if src not in SOURCES:
            print(f"  ⚠️ 未知数据源: {src}, 可选: {list(SOURCES.keys())}")
            continue
        name, fetcher = SOURCES[src]
        print(f"正在抓取 {name}...")
        try:
            news = fetcher(ws, we)
            all_events = len(news)
            print(f"  ✅ {name}: {all_events} 条")
            all_news.extend(news)
        except Exception as e:
            print(f"  ❌ {name} 抓取失败: {e}")

    # 按时间排序 (从新到旧)
    all_news.sort(key=lambda x: x.get("publish_time", ""), reverse=True)

    # 去重 (标题相似则去重)
    seen_titles = set()
    deduped = []
    for n in all_news:
        title_key = n.get("title", "")[:30]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            deduped.append(n)

    print(f"\n📊 汇总: {len(all_news)} 条原始 -> {len(deduped)} 条去重后")

    # 保存
    output_path = os.path.join(BASE_DIR, args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存: {output_path}")

    return deduped


if __name__ == "__main__":
    main()
