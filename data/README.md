# 港股科技股策略数据缓存

本目录用于缓存执行 `buyv2.md` 所需的“最新搜索数据”，目标是：

1. 初始化时保存一份本地快照。
2. 后续执行策略时，优先使用本地数据。
3. 只对“缺失字段”或“超过有效期的字段”做增量搜索。

## 目录结构

- `market_context.json`
  - 市场层数据：恒生科技指数估值分位、3 月以来南向累计净买入、执行日期、来源。
- `stock_pool.json`
  - 港股科技股票池。推荐范围应来自整个股票池，而不是写死少数股票。
- `stocks_snapshot.json`
  - 个股层数据：价格、52 周高低、PE、南向净买入、南向连续净买入、是否触发追高过滤、催化等。
- `manual_incremental_updates.json`
  - 搜索或人工补录得到的增量字段。执行 `make socket_sug` 时会自动合并回本地缓存。
- `southbound_trends_cache.json`
  - 南向持仓历史与趋势图缓存。执行 `make socket_sug` 时优先读取本地缓存，再增量拉取最近一段交易日数据并合并，避免每次全量抓取历史。
- `update_manifest.json`
  - 数据字段的有效期、缺失字段、刷新策略、搜索优先级。
- `prompt_template.md`
  - 每次执行策略时直接可复制的 prompt。

## 增量更新原则

### 1. 市场层数据

以下字段默认视为高频数据，超过 1 个交易日就应重新搜索：

- `hang_seng_tech_pe_percentile`
- `southbound_net_buy_mtd_hkd_billion`
- `southbound_net_buy_today_hkd_billion`

### 2. 个股层数据

以下字段默认 1 个交易日过期：

- `current_price_hkd`
- `southbound_recent_flow`
- `southbound_active_rank`

以下字段默认 5 个交易日过期：

- `pe_ttm`
- `pb`
- `southbound_holding_ratio`
- `southbound_turnover_ratio`

以下字段默认 20 个交易日过期：

- `52w_high`
- `52w_low`
- `valuation_percentile_5y`
- `three_month_price_behavior`

### 3. 缺失字段优先更新

如果本地字段为空、为 `null`、为 `unknown`，无论是否在有效期内，都优先搜索。

### 4. 推荐输出前必须二次确认

以下字段即使本地有缓存，也建议在正式出结论前做一次快速核验：

- 最近 3 个月是否出现单日暴涨
- 最近 5 个交易日南向是否仍为净买入
- 最新价格是否已经接近 52 周高点 50%

## 当前策略最关键字段

按 `buyv2.md`，优先级最高的字段是：

1. `current_price_hkd`
2. `52w_high`
3. `valuation_percentile_5y`
4. `southbound_net_buy_20d_hkd_billion`
5. `southbound_net_buy_50d_hkd_billion`
6. `southbound_buy_weeks_in_10w`
7. `southbound_turnover_ratio_5d`
8. `three_month_has_single_day_gain_ge_10pct`

## 使用建议

每次跑策略时：

1. 先读取本目录 5 个文件。
2. 先按 `stock_pool.json` 建立完整股票池。
3. 再将 `stocks_snapshot.json` 中已有快照映射到股票池。
4. 只对 `update_manifest.json` 中标记为 `stale` 或 `missing` 的字段做网络搜索或接口更新。
5. 用“本地数据 + 增量更新数据”重新生成推荐。

## 自动化执行

仓库根目录提供 `Makefile` 后，可直接运行：

```bash
make socket_sug
```

它会完成：

1. 读取 `stock_pool.json`
2. 更新可自动拉取的最新价格、52 周高低、部分估值字段
3. 自动合并 `manual_incremental_updates.json` 中的搜索增量字段
4. 将增量结果写回 `stocks_snapshot.json`
5. 增量刷新 `southbound_trends_cache.json` 中的南向趋势历史
6. 基于当前本地缓存生成最新推荐结果

输出文件位于：

- `sockets/outputs/latest_recommendation.md`
- `sockets/outputs/latest_recommendation_trends.png`
- `sockets/outputs/latest_recommendation_trends_weekly.png`
- `sockets/outputs/latest_recommendation_trends.json`
