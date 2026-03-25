# 港股科技股推荐 Prompt

下面这份 prompt 分为两种模式：

1. `全量模式`
   - 第一次建库，或者本地数据明显过旧时使用。
2. `增量模式`
   - 日常执行时使用，只搜索本地缺失或过期的数据。

---

## 1. 全量模式 Prompt

```text
你现在执行港股科技股推荐策略，请严格按以下流程：

第一步：先读取本地文件
1. 读取 `sockets/buyv2.md`
2. 读取 `sockets/data/market_context.json`
3. 读取 `sockets/data/stock_pool.json`
4. 读取 `sockets/data/stocks_snapshot.json`
5. 读取 `sockets/data/manual_incremental_updates.json`
6. 读取 `sockets/data/update_manifest.json`

第二步：判断是否需要全量刷新
如果出现以下任一情况，则执行全量刷新：
- market_context.json 的 snapshot_date 不是最新交易日附近
- 恒生科技指数 PE 分位缺失或过期
- 南向资金 3 月以来累计净买入缺失或过期
- 候选股关键字段缺失过多（current_price_hkd / high_52w_hkd / pe_ttm / southbound_net_buy_20d_hkd_billion / southbound_net_buy_50d_hkd_billion / three_month_has_single_day_gain_ge_10pct）

第三步：全量搜索并更新本地数据
按以下优先级搜索：
1. 市场层：
   - 恒生科技指数最新 PE / PE 分位
   - 南向资金最新当日净买入、近20日或3月以来累计净买入
2. 个股层：
   - 遍历 `stock_pool.json` 中全部港股科技股票
   - 优先更新 `priority=high` 的股票
   - 再补全 `priority=medium/low` 中缺失或过期字段

第四步：按 `buyv2.md` 严格筛选
只推荐同时满足以下要求的港股科技股：
- 南向资金持续净买入
- 股价仍在低位区
- 最近3个月没有明显单日暴涨 >=10%
- 累积涨幅不过热
- 不是刚被消息刺激大幅拉升

第五步：输出两部分内容
1. 推荐股票表格（严格按 buyv2.md 的格式）
2. 需要写回本地缓存的数据更新建议：
   - market_context.json 需要更新哪些字段
   - stocks_snapshot.json 需要更新哪些字段
   - 哪些字段仍缺失，下一次需要继续搜索
3. 若本次搜索获得了最新南向资金/估值分位/催化数据，请同时给出应写入 `manual_incremental_updates.json` 的 JSON 片段

要求：
- 完全基于最新搜索结果
- 必须标注哪些结论来自本地旧数据，哪些来自本次增量搜索
- 若本地数据与最新搜索冲突，以最新搜索为准
```

---

## 2. 增量模式 Prompt

```text
你现在执行港股科技股推荐策略，但不要重复搜索已经存在且未过期的数据。

请严格按照以下流程：

第一步：先读取本地文件
1. `sockets/buyv2.md`
2. `sockets/data/market_context.json`
3. `sockets/data/stock_pool.json`
4. `sockets/data/stocks_snapshot.json`
5. `sockets/data/manual_incremental_updates.json`
6. `sockets/data/update_manifest.json`

第二步：只搜索“本地缺失或已过期”的字段
判断规则：
- 若字段在 update_manifest.json 中 ttl 已过期，则必须重新搜索
- 若字段为空、unknown、estimated、needs_incremental_check，也必须重新搜索
- 若字段仍在有效期内，则直接使用本地数据，不要重复搜索

第三步：搜索优先级
先市场，后个股：
1. 恒生科技指数最新 PE 分位
2. 南向资金最新累计净买入
3. `stock_pool.json` 中全部股票先建立基础快照
4. 当前 candidate / watchlist 股票的缺失字段优先补全
5. 非核心排除股票除非被用户要求复核，否则不优先搜索

第四步：基于“本地有效数据 + 本次增量更新数据”执行策略
筛选时重点检查：
- 当前股价是否低于 52周高点 50%，或估值仍在历史低位
- 最近 1 个月 / 20 天 / 2 周内南向资金是否持续净买入
- 最近 3 个月是否出现单日暴涨 >=10%，或累积涨幅 >15%
- 是否已经属于追高状态

第五步：最终输出
请按以下结构输出：

【本次使用的本地数据】
- 列出直接沿用的字段

【本次增量更新的数据】
- 列出本次新搜索补齐的字段

【建议写回 manual_incremental_updates.json 的内容】
- 只输出本次新搜索得到的市场层字段与个股层字段 JSON 片段

【推荐股票列表】（按综合得分降序）
- 严格使用 buyv2.md 中定义的表格格式

【结论】
- 只保留最符合“南向资金在股价低位建仓、不能追高”的港股科技股
- 若严格筛选后只有 1 只，也只输出 1 只

要求：
- 不要为了凑数量放宽条件
- 明确区分 candidate、watchlist、excluded
- 若某股票因最近3个月暴涨被排除，要明确写出排除原因
```

---

## 3. 推荐的日常使用方式

最实用的是直接用“增量模式 Prompt”，因为它会：

1. 先用本地缓存。
2. 只补缺失和过期字段。
3. 最终仍按最新数据输出推荐结果。
