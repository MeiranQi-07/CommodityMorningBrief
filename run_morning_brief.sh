#!/bin/bash
# CommodityMorningBrief 每日开盘前简报 + 回测复盘自动化脚本
# 由 cron 在 08:30 (Asia/Shanghai) 触发
#
# 执行顺序：
#   ① 回测 ← 此时 commodity_news.json 仍是昨日数据
#   ② 自我复盘 ← 分析全部历史回测
#   ③ 校准注入 ← 更新 LLM prompt
#   ④ 采集今日新闻
#   ⑤ 生成报告 + Excel
#   ⑥ 邮件推送

set -e
cd "$(dirname "$0")"

REPORT_DATE=$(TZ=Asia/Shanghai date +%Y-%m-%d)
REPORT_DATE_COMPACT=$(TZ=Asia/Shanghai date +%Y%m%d)
YESTERDAY_COMPACT=$(TZ=Asia/Shanghai date -d 'yesterday' +%Y%m%d 2>/dev/null || \
    TZ=Asia/Shanghai date -v-1d +%Y%m%d)
LOG="output/run_log.txt"

echo "[$(TZ=Asia/Shanghai date '+%H:%M:%S')] === CommodityMorningBrief 每日简报 ===" | tee -a "$LOG"
echo "报告日期: $REPORT_DATE" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── Step 0: 保存 commodity_news.json 快照（供后续回测参考） ──
if [ -f data/commodity_news.json ]; then
    cp data/commodity_news.json "output/commodity_news_${REPORT_DATE_COMPACT}.json" 2>/dev/null
fi

# ── Step 1: 回测（对比昨日 LLM 判断 vs 实际行情） ──
echo "[1/6] 回测验证（昨日 $YESTERDAY_COMPACT）..." | tee -a "$LOG"
if python3 scripts/backtest.py --date "$YESTERDAY_COMPACT" 2>&1 | tee -a "$LOG"; then
    echo "  ✅ 回测完成" | tee -a "$LOG"
else
    echo "  ⚠️  回测跳过（可能无昨日 LLM 数据）" | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# ── Step 2: 自我复盘（分析全部历史回测结果，检测偏差） ──
echo "[2/6] 自我复盘..." | tee -a "$LOG"
if python3 scripts/self_improve.py 2>&1 | tee -a "$LOG"; then
    echo "  ✅ 复盘完成" | tee -a "$LOG"
else
    echo "  ⚠️  复盘跳过（回测数据不足）" | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# ── Step 3: 校准注入（将偏差校准规则写入 LLM prompt） ──
echo "[3/6] 校准注入..." | tee -a "$LOG"
if python3 scripts/inject_calibration.py --quiet 2>&1 | tee -a "$LOG"; then
    echo "  ✅ 校准注入完成" | tee -a "$LOG"
else
    echo "  ⚠️  校准跳过" | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# ── Step 4: 多源新闻采集 ──
echo "[4/6] 采集新闻..." | tee -a "$LOG"
python3 scripts/multi_source.py --date "$REPORT_DATE" 2>&1 | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── Step 4.5: LLM 筛选 + 分析（将 candidates.json → commodity_news.json） ──
echo "[4.5/6] LLM 新闻筛选与影响分析..." | tee -a "$LOG"
python3 scripts/llm_analyze.py 2>&1 | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── Step 5: 生成简报 ──
echo "[5/6] 生成简报..." | tee -a "$LOG"
RAW_COUNT=$(python3 -c "import json; print(len(json.load(open('data/candidates.json'))))" 2>/dev/null || echo 0)
python3 scripts/generate_outputs.py --raw-candidates "$RAW_COUNT" 2>&1 | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── Step 6: 邮件推送 ──
echo "[6/6] 发送邮件..." | tee -a "$LOG"
python3 scripts/pushplus_notify.py --date "$REPORT_DATE_COMPACT" --email --no-push 2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "[$(TZ=Asia/Shanghai date '+%H:%M:%S')] === 全部完成 ===" | tee -a "$LOG"
