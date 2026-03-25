# Socket Stock Suggestion (2026-03-25 22:48:33)

## 本次使用的本地数据
- 市场快照日期：`2026-03-25`
- 个股快照日期：`2026-03-25`
- 自动更新字段：`current_price_hkd`、`high_52w_hkd`、`low_52w_hkd`、`pe_ttm`、`price_vs_52w_high_pct`
- 人工/搜索缓存字段：南向资金、估值分位、催化、是否追高

## 推荐股票列表

| 排序 | 股票名称 (代码) | 当前股价 (港元) | 个股PE分位数 (近5年) | 南向近50日净买入 (亿港元) | 南向成交占比 | 近10周上榜次数 | 催化强度 | 综合得分 | 优先级 | 信号类型 |
|-----|----------------|----------------|---------------------|--------------------------|-------------|--------------|---------|---------|--------|---------|
| 1 | 阿里巴巴-W (09988.HK) | 128.9 | unknown | 51.25 | estimated_high | >=4_estimated_from_public_reports | strong | 69 | P2 | B |
| 2 | 美团-W [人选] (03690.HK) | 90.0 | unknown | unknown | unknown | unknown | unknown | manual | 人选 | 人选 |
| 3 | 京东物流 [人选] (02618.HK) | 13.83 | unknown | unknown | unknown | unknown | unknown | manual | 人选 | 人选 |

## 观察池

- `快手-W (01024.HK)`：2026-01-05 单日涨幅约 11.09%，进入观察池而非正式推荐。

## 详细说明

- `阿里巴巴-W (09988.HK)`：近50日南向流向代理值约 65.39 亿港元。 近5日南向流向代理值约 49.77 亿港元。
- `美团-W (03690.HK)`：人工加入趋势观察与展示。 近50日南向流向代理值约 61.03 亿港元。 近5日南向流向代理值约 -4.12 亿港元。
- `京东物流 (02618.HK)`：人工加入趋势观察与展示。 近50日南向流向代理值约 -8.07 亿港元。 近5日南向流向代理值约 -2.92 亿港元。

## 结论
- 当前推荐数量：`3`
- 已将 `manual_trends.json` 中的人工入选股票一并加入推荐表与趋势图展示，并标注“人选”。
- 已纳入“低位短线净卖出可能是洗盘”的判断，不再把低位小幅净卖出直接视作撤离。
- 推荐结果基于本地缓存 + 本次自动增量更新后的最新行情字段。

## 趋势图输出

- 推荐结果 Markdown：`/home/lhy/workspace/sockets/outputs/20260325_224650_stock_recommendation.md`
- 90日趋势图 PNG：`/home/lhy/workspace/sockets/outputs/20260325_224650_stock_recommendation_trends.png`
- 1年周视图 PNG：`/home/lhy/workspace/sockets/outputs/20260325_224650_stock_recommendation_trends_weekly.png`
- 趋势图数据 JSON：`/home/lhy/workspace/sockets/outputs/20260325_224650_stock_recommendation_trends.json`
- 趋势图股票数量：`3`
- 最新兼容 Markdown：`/home/lhy/workspace/sockets/outputs/latest_recommendation.md`
- 最新兼容 90日 PNG：`/home/lhy/workspace/sockets/outputs/latest_recommendation_trends.png`
- 最新兼容 1年周视图 PNG：`/home/lhy/workspace/sockets/outputs/latest_recommendation_trends_weekly.png`
- 最新兼容 JSON：`/home/lhy/workspace/sockets/outputs/latest_recommendation_trends.json`
- 自动推荐数量参数：`num=3`（默认 `3`，人工入选股票仍会追加展示）。
- 趋势图前五行为汇总视图：日视图中股价改为当日涨跌幅，周视图中股价改为周涨跌幅；并新增5日、20日、50日南资累计净额汇总视图，南资相关汇总区做了约3倍视觉放大，且每个视图均带股票图例。
- 趋势图时间范围已调整为近90日，横轴按日展示，并加宽图像以便观察每日变化。
- 另生成一张近1年周视图，横轴按周展示，图像和纵向高度进一步加大，便于观察中期趋势。
- 趋势图右侧纵轴单位统一为“亿港元”。
- 图中“50天累计南向净流入额”为基于南向持股日变化 × 当日收盘价估算的资金流向代理值。
