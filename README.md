# CommodityMorningBrief 📊

**开盘前商品市场简报 — AI-powered morning briefing for precious metals, commodities & crude oil.**

Built for the [OpenClaw](https://openclaw.ai) agent platform. Collects financial news from Chinese sources, uses LLM to filter and analyze gold/silver/commodities/energy headlines, and delivers structured reports via email with live price snapshots.

## Features

- 📡 Dual-source news collection: [Yicai (第一财经)](https://www.yicai.com) + [Cailian Press (财联社)](https://www.cls.cn)
- 🤖 LLM-automated filtering, classification & market impact analysis
- 📧 HTML email delivery with embedded styling + full-data Excel attachment
- 📊 Overnight price snapshot (live vs last-close comparison)
- 🔄 Optional backtest & self-improvement framework

## Time Window Design

The report analyzes the **gap between domestic night-session close and morning open**:

| Asset | Night Session Close | Analysis Window | Why? |
|-------|-------------------|-----------------|------|
| Gold, Silver, Crude Oil | 02:30 CST | **02:30~08:30** | International spot/futures still moving |
| Copper, Base Metals | 01:00 CST | **01:00~08:30** | LME still trading after SHFE close |

News during the active night session (21:00~02:30) is already **priced in** by the market. The report focuses on the **post-settlement gap** where relevant information has not yet been reflected in domestic contracts. The window ends at 08:30, giving readers 30 minutes to review before the 09:00 open.

## Report Structure

```
📬 CommodityMorningBrief
├── 一、隔夜行情速览           Overnight price snapshot (live vs close)
├── 二、系统说明
├── 三、新闻概览               Raw candidates → LLM-filtered count
├── 四、重点新闻摘要            Top 10 by importance
├── 五、黄金影响分析
├── 六、白银影响分析
├── 七、原油与大宗商品影响分析
├── 八、今日关注因素            Dynamically extracted from news
├── 九、风险提示
📎 attachment: commodity_news.xlsx (all items, 14 fields)
```

## Coverage

### Assets
| Asset | Type | Domestic Contract | Intl Reference | Night Close |
|-------|------|-----------------|----------------|------------|
| Gold | Precious Metal | SHFE AU | COMEX GC / XAU | 02:30 |
| Silver | Precious Metal | SHFE AG | COMEX SI / XAG | 02:30 |
| Copper | Base Metal | SHFE CU | LME Copper | 01:00 |
| Crude Oil | Energy | INE SC | WTI / Brent | 02:30 |
| USD Index | Macro | — | DXY | — |

## Backtest & Self-Improvement (Optional)

### Rationale

The backtest framework is a **standalone quality-assurance tool** (not included in daily output). It validates whether LLM analysis aligns with actual market direction.

### How It Works

```
1. Fetch real market close data from Sina Finance API
2. Compare LLM judgment vs actual price move:
   - "bullish" → price up = ✅ correct
   - "bearish" → price down = ✅ correct
3. Calculate per-asset accuracy by direction
```

### Bias Detection

With accumulated data, `self_improve.py` detects systematic biases:

| Rule | Trigger | Example | 
|------|---------|--------|
| Direction bias | Bull vs bear accuracy gap > 30% | "Gold bullish 30% vs bearish 80% → over-optimistic" |
| Single direction | ≥3 samples at ≤30% accuracy | "Oil bearish 0/4 → review bearish logic" |
| Overall bias | ≥5 samples at <50% accuracy | "Silver 40% → strengthen analysis" |

### Usage

```bash
python3 scripts/backtest.py --date 20260603           # Run backtest
python3 scripts/self_improve.py                        # Analyze biases
python3 scripts/inject_calibration.py                  # Inject into prompt
```

## Pipeline

```bash
# 1. Collect raw news (window 02:30~08:00)
python3 scripts/multi_source.py --source all --date 2026-06-04

# 2. LLM filter & analyze → data/commodity_news.json [manual step]

# 3. Generate report + Excel
python3 scripts/generate_outputs.py --raw-candidates 77

# 4. Send email with attachment
python3 scripts/pushplus_notify.py --date 20260604 --email --no-push
```

## Project Structure

```
commodityreport/
├── SKILL.md                    # Skill documentation
├── manifest.json
├── .env                        # SMTP config (gitignored)
├── data/
│   ├── commodity_news.json     # LLM analysis results
│   ├── candidates.json         # Raw news from multi_source
│   ├── demo_news.json
│   └── backtest_calibration.json
├── output/
│   ├── morning_brief_*.md
│   ├── commodity_news_*.xlsx
│   ├── backtest_result_*.json
│   └── run_log.txt
├── scripts/
│   ├── multi_source.py         # News collector (Yicai + Cailian Press)
│   ├── generate_outputs.py     # Report + Excel generator
│   ├── pushplus_notify.py      # Email + PushPlus sender
│   ├── backtest.py             # Backtest engine (Sina Finance API)
│   ├── self_improve.py         # Bias analysis
│   └── inject_calibration.py   # Calibration prompt injection
├── prompts/
│   ├── news_filter.md
│   ├── impact_analyze.md       # Supports calibration injection
│   └── report_generation.md
```

## ⚠️ Disclaimer

**For educational and experimental purposes only.** Does not provide investment advice, execute trades, or offer price predictions. All analysis indicates possible impact directions based on news text.
