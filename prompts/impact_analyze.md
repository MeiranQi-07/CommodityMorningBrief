# 金银贵金属与商品价格影响分析任务

请基于输入新闻，分析其对黄金、白银、原油及相关大宗商品价格的可能影响。

## 📊 历史回测校准

{CALIBRATION_SECTION}

---

请输出 JSON 格式：

{
  "news_id": "",
  "title": "",
  "summary": "",
  "source": "",
  "publish_time": "",
  "url": "",
  "region": "domestic or international",
  "category": "gold / silver / precious_metals / crude_oil / macro / geopolitics / usd_rates / commodities",
  "related_assets": [],
  "impact_direction": "bullish / bearish / neutral / mixed",
  "impact_strength": "high / medium / low",
  "confidence": "high / medium / low",
  "reason": "",
  "risk_note": ""
}

## 判断规则

1. 美元走强、美债收益率上行、实际利率上升，通常对黄金白银偏空。
2. 美元走弱、美债收益率下行、降息预期升温，通常对黄金白银偏多。
3. 地缘政治风险上升、避险情绪升温，通常对黄金偏多。
4. 通胀超预期可能通过避险和抗通胀逻辑支撑金价，但若推升加息预期，也可能形成压制，应判断为 mixed。
5. 原油上涨可能推升通胀预期，从而间接影响贵金属。
6. 央行购金、黄金 ETF 流入通常对黄金偏多。
7. 白银兼具贵金属和工业品属性，需同时考虑避险需求与工业需求。
8. 不得输出确定性价格预测。
9. 不得给出直接交易建议。
10. 趋势判断只能使用“可能偏多”“可能偏空”“中性”“多空交织”等表达。
