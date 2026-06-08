---
name: commodityreport
description: 使用 OpenClaw 的 web_fetch、agent-browser、LLM、文件读写和 Python 脚本能力,生成黄金、白银、铜、原油等大宗商品开盘前新闻影响简报。
---

# Commodity Report

## 一、功能目标

本 Skill 用于生成金银贵金属与大宗商品开盘前新闻影响简报。系统每天早上 08:00 定时运行,自动获取沪金/沪银夜盘收盘后（02:30）至早间开盘前（08:30）的国际市场变化和财经快讯,重点关注黄金、白银、贵金属、大宗商品、原油、美元指数、利率预期、通胀数据和地缘政治事件。

系统通过调用第一财经快讯公开 API（https://www.yicai.com/api/ajax/getbrieflist）获取快讯数据。该 API 返回 JSON 格式，无需认证。从当前页面开始逐页翻取，直到覆盖完整时间窗口。基于获取到的候选快讯，调用 LLM 进行筛选、摘要、分类和影响分析。

系统调用 LLM 对新闻进行筛选、摘要、分类和影响分析,并通过 Python 脚本生成每日 Excel 新闻表和 Markdown 简报。如果用户提供收件邮箱,系统还可以调用邮件脚本将简报正文和 Excel 附件发送至指定邮箱。

本 Skill 的输出仅用于课程实验展示和市场信息整理,不构成投资建议。

## 二、适用场景

当用户提出以下需求时,使用本 Skill:

- 生成今日金银早报
- 查看黄金白银相关新闻
- 分析贵金属市场开盘前情绪
- 生成大宗商品新闻简报
- 分析原油、美元、利率对金银价格的影响
- 推送每日 08:00 商品市场早报
- 将商品市场简报发送到指定邮箱

## 三、时间窗口
本 Skill 默认生成"开盘前简报"。系统只分析**沪金/沪银夜盘收盘后至上午开盘前**这段国际市场仍在波动、但国内市场尚未反应的窗口。

默认规则如下:

    report_date = 当前日期
    window_start = report_date 当日 02:30  (沪金/沪银夜盘收盘)
    window_end   = report_date 当日 08:30  (开盘前)

设计逻辑:

- 夜盘时段（21:00~02:30）的新闻已经反映在沪金/沪银价格中，不再重复分析。
- 真正需要分析的是 **02:30 之后国际盘的变化**，这些变化尚未被国内定价。
- 以 02:30~08:30 为窗口（留30分钟阅读时间），帮助交易者在 09:00 开盘前了解市场状况。

如果用户明确指定报告日期,例如 `report_date=2026-06-04`,则系统应使用:

    window_start = 2026-06-04 02:30
    window_end   = 2026-06-04 08:30

## 四、新闻源

系统当前版本默认使用以下主新闻源：

1. 第一财经快讯 API：https://www.yicai.com/api/ajax/getbrieflist

第一财经快讯是本项目的主新闻源。该 API 为公开接口，返回 JSON 格式数据，无需认证或浏览器环境。

获取方式：
1. 从 `page=1` 开始，逐页请求 `count=100` 条快讯；
2. 每页返回最多 10 条快讯数据；
3. 持续翻页直到获取到发布时间早于 `window_start` 的新闻为止；
4. 从所有获取的快讯中只保留 `window_start <= publish_time <= window_end` 的候选快讯；
5. 快讯数据中的 `datekey`（日期，如"2026.05.21"）和 `hm`（时间，如"15:30"）拼接后即为发布时间。

注意：
- API 返回的 `LiveContent` 可能含 HTML 标签，使用前需清理。
- API 返回的 `LiveTitle` 为空时，可从 `LiveContent` 中提取标题或摘要。
- `IsImportant` 字段标记是否为重要快讯。
- 此 API 无需浏览器环境，`web_fetch` 或 `curl` 即可直接调用。


## 五、数据获取方式

本 Skill 获取快讯数据的方式：

1. **第一财经快讯 API**：使用 `web_fetch` 或 `curl` 调用 `https://www.yicai.com/api/ajax/getbrieflist?page=N&count=100` 获取 JSON 数据。这是主要且唯一的数据源。
2. **`data/demo_news.json`**：仅当 API 无法返回有效数据，或获取到的相关新闻少于 3 条时使用。

不再依赖浏览器环境（agent-browser / chromium）。

## 六、新闻筛选范围

优先保留以下主题相关新闻:

- 黄金
- 白银
- 贵金属
- 大宗商品
- 原油
- 美元指数
- 美联储
- 利率
- 通胀
- CPI / PPI / 非农就业
- 地缘政治
- 避险情绪
- 央行购金
- COMEX 黄金 / 白银
- 伦敦金 / 伦敦银
- 上金所
- 沪金 / 沪银
- 国际油价
- OPEC

不纳入与主题无关的普通股票新闻、公司公告、娱乐新闻、广告、行情噪声和重复快讯。

## 七、整体执行流程

本 Skill 按以下顺序执行：

    定时触发或用户手动触发
    → 确定 report_date 和固定新闻时间窗口
    → 调用第一财经快讯 API 逐页获取快讯
    → 采集时间窗口内所有候选快讯
    → LLM 筛选金银与商品相关新闻
    → LLM 分析价格影响方向
    → 所有相关新闻写入 Excel，另从其中选10条最重要的写入 Markdown 报告
    → 保存结构化 JSON
    → 生成 Excel 新闻表（全部相关新闻）
    → 生成 Markdown 简报（10条最重要）
    → 如提供邮箱则发送邮件
    → Dashboard 展示结果

具体步骤如下：

1. 当用户在 Dashboard 请求"生成商品报告"或定时任务在每天 08:00 触发时，启动本 Skill。
2. 首先确定报告日期 `report_date`。默认情况下，`report_date` 为当前日期；如果用户明确指定日期，则使用用户指定日期。
3. 根据 `report_date` 计算新闻时间窗口（仅分析夜盘收盘后至开盘前）：

       window_start = report_date 当日 02:30   (沪金/沪银夜盘收盘)
       window_end   = report_date 当日 08:30   (早间开盘前，留30min看报告)

4. 调用第一财经快讯 API：`https://www.yicai.com/api/ajax/getbrieflist?page=N&count=100`
   - 从 `page=1` 开始逐页请求
   - 每页返回最多 10 条快讯数据
   - 持续翻页直到获取到的快讯发布时间早于 `window_start`
5. 从所有获取的快讯中，只保留 `window_start <= 发布时间 <= window_end` 的候选快讯。发布时间由 `datekey`（日期，如"2026.05.21"）和 `hm`（时间，如"15:30"）拼接计算。
6. 调用 LLM 从候选快讯中筛选与黄金、白银、贵金属、大宗商品、原油、美元指数、美联储、利率、通胀、CPI、PPI、非农就业和地缘政治有关的新闻。
7. 调用 LLM 对筛选后的新闻进行摘要、资产关联、影响方向、影响强度、置信度和判断理由分析。
8. 将结构化结果覆盖保存为：

       data/commodity_news.json

9. 调用 Python 脚本：

       python3 scripts/generate_output.py --use_demo_news false --output_format excel_markdown

   - **Excel**：输出所有相关新闻（不过滤数量）
   - **Markdown 报告**：只选 10 条最重要的新闻进入报告

10. 如果用户提供收件邮箱，调用邮件脚本发送报告：

        python3 scripts/send_email.py --to 用户邮箱

11. 只有当 API 无法返回有效数据，或真实相关新闻少于 3 条时，才读取 `data/demo_news.json`。
12. 如果使用了 demo 数据，必须在最终报告和 Dashboard 回复中明确说明。

## 八、结构化字段

每条新闻统一整理为以下字段:

    news_id
    source
    publish_time
    title
    url
    summary
    region
    category
    related_assets
    impact_direction
    impact_strength
    confidence
    reason
    risk_note

字段说明:

    region:
    domestic = 国内
    international = 国际

    category:
    precious_metals = 贵金属
    gold = 黄金
    silver = 白银
    crude_oil = 原油
    macro = 宏观
    geopolitics = 地缘政治
    usd_rates = 美元与利率
    commodities = 大宗商品

    related_assets:
    可包含 gold, silver, crude_oil, copper, usd_index, bond_yield 等

    impact_direction:
    bullish = 可能偏多
    bearish = 可能偏空
    neutral = 中性或影响不明确
    mixed = 多空交织

    impact_strength:
    high = 高影响
    medium = 中等影响
    low = 低影响

    confidence:
    high / medium / low

## 九、影响分析规则

LLM 分析新闻影响时应遵循以下基本逻辑:

1. 美元走强、美债收益率上行、实际利率上升,通常对黄金和白银偏空。
2. 美元走弱、美债收益率下行、降息预期升温,通常对黄金和白银偏多。
3. 地缘政治风险上升、避险情绪升温,通常对黄金偏多。
4. 通胀超预期可能通过抗通胀逻辑支撑黄金,但如果同时推升加息预期,也可能形成压制,应判断为 mixed。
5. 原油上涨可能推升通胀预期,从而间接影响贵金属。
6. 白银兼具贵金属和工业品属性,需同时考虑避险需求和工业需求。
7. 央行购金、黄金 ETF 流入、避险资产配置需求上升,通常对黄金偏多。
8. 不得输出确定性价格预测。
9. 不得给出直接交易建议。

## 十、输出文件

系统输出以下文件:

    data/commodity_news.json
    output/commodity_news_YYYYMMDD.xlsx
    output/morning_brief_YYYYMMDD.md
    output/run_log.txt

其中:

    commodity_news.json = LLM 分析后的结构化新闻
    commodity_news_YYYYMMDD.xlsx = 每日新闻 Excel 表
    morning_brief_YYYYMMDD.md = 每日简报
    run_log.txt = 运行日志

如果用户提供邮箱地址,系统额外执行邮件发送,但不在代码中固定收件人。邮件发送模块采用"统一服务发件邮箱 + 运行时指定收件人"的设计:

    python3 scripts/send_email.py --to 用户邮箱

SMTP 发件邮箱配置保存在服务器本地 `.env` 文件中,不应写入报告正文或公开代码。

## 十一、邮件发送规则

当用户明确要求发送邮件,或定时任务中包含收件邮箱时,系统在生成 Excel 和 Markdown 简报后调用:

    python3 scripts/send_email.py --to 用户邮箱

要求:

1. 收件邮箱由用户运行时提供。
2. 支持多个收件邮箱,邮箱之间用英文逗号分隔。
3. 不得要求用户提供自己的邮箱 SMTP 授权码。
4. 系统统一使用服务器本地 `.env` 中配置的服务发件邮箱。
5. 如果邮件发送失败,应保留已生成的 Excel 和 Markdown 文件,并在 Dashboard 回复中说明失败原因。

## 十二、降级策略

如果网页获取失败、新闻数量不足或 LLM 输出不完整,系统可以读取 `data/demo_news.json` 中的演示数据继续执行。但必须满足以下条件之一:

- `web_fetch`、`agent-browser` 和 `browser` 均无法获取有效新闻;
- 四个新闻源均无法返回有效文本;
- 页面出现登录、验证码、反爬或访问限制,且无法继续提取;
- 提取到的真实相关新闻少于 3 条;
- LLM 输出无法整理为有效 JSON。

如果仅 `browser` 不可用,但 `web_fetch` 可以获取页面内容,不应触发 demo 降级。

使用 demo 数据时,最终报告中必须说明:

    由于网页获取失败或新闻源访问不稳定,本次使用 data/demo_news.json 中的演示新闻数据完成流程。该结果主要用于展示 OpenClaw 的任务编排逻辑和系统运行效果。

## 十三、安全边界

本 Skill 不提供任何确定性的交易建议,不输出"买入、卖出、做多、做空、止盈、止损"等直接操作指令。

禁止输出:

- 确定性买入建议;
- 确定性卖出建议;
- 做多、做空指令;
- 止盈、止损价格;
- 收益承诺;
- 对未来价格的确定性预测;
- 自动交易指令。

允许输出:

- 可能偏多;
- 可能偏空;
- 多空交织;
- 中性;
- 需观察美元、利率、原油和避险情绪变化。

所有趋势判断仅表示基于新闻文本的影响倾向,用于课程实验展示和市场观察,不构成投资建议。

---

## 十四、回测校准工具（可选能力）

系统额外提供**回测与自我复盘**脚本，可作为独立分析工具使用，**不纳入每日自动简报**。

### 可用脚本

1. **`scripts/backtest.py`** — 拉取新浪财经真实行情数据，对比 LLM 历史判断准确率
2. **`scripts/self_improve.py`** — 分析全部回测历史，检测系统性偏差
3. **`scripts/inject_calibration.py`** — 将偏差校准规则注入 LLM 分析 prompt

### 偏差识别规则

| 规则 | 条件 | 触发示例 |
| --- | --- | --- |
| 多空方向偏差 | bullish vs bearish 准确率差距 > 30% | 黄金bullish 30% vs bearish 80% → 过度乐观 |
| 单方向偏差 | 某方向 >= 3 次且准确率 <= 30% | 原油bearish 0/4 → 对该方向判断逻辑需审查 |
| 整体偏差 | 总样本 >= 5 且准确率 < 50% | 白银整体 40% → 需加强因果关系推理 |

### 使用方式

```bash
# 手动运行回测复盘闭环
python3 scripts/backtest.py --date YYYYMMDD           # 回测
python3 scripts/self_improve.py                        # 复盘分析
python3 scripts/inject_calibration.py --output /tmp/p.md  # 注入prompt
```

### 注意事项

- 校准质量随回测期数增加而提升，初期样本少时偏差检测较为敏感
- 偏差检测阈值可根据实际运行情况调整
- 这些脚本独立于每日简报流程，按需使用
