# Changelog

## Unreleased

- 新增 `main_wave_v2` 确定性策略：复刻八条主升浪规则，保留原始 50 分与折算 100 分、逐项命中证据和 `n/8` 命中数
- 新增日 K 来源、复权、数据日期与抓取时间元数据；未复权、复权未知、数据不足或非法 OHLCV 会 fail-closed
- 新增 `universe_audit`，并支持策略约束最小股票池、代码唯一性和全量日 K 覆盖
- `main_wave_v2` 内置 6000 条日 K 候选上限，优先于全局默认值；显式传入更低上限时仍 fail-closed
- 新增有来源的确定性情绪面：无证据时标记不可用，达到置信度后仅对 `final_score` 做有上限修正，不改写主升浪 50/100 分
- 支持 DSA 通过 `context["dsa"]` 注入候选 provider，AlphaSift 会在 L1 初筛后、LLM 重排前补充 DSA 行情、基本面和新闻上下文
- `dsa_adapter.screen()` 现在会透传 DSA context，并在候选结果中保留 `dsa_context`、`dsa_news` 和 `dsa_analysis_summary`
- LLM ranking prompt 会读取候选上的 DSA provider context，便于排序阶段利用 DSA 已有数据能力

## 2026-04-12

- 明确说明 `DSA` 指外部项目 `daily_stock_analysis`，补充两者的职责边界与调用关系
- 更新 README、Skill 文档和设计说明，说明 DSA 只在最终入围候选上调用
- 修正文档中过期描述：移除对 `shrink_pullback` 可直接运行和“未实现 L3 deep_analysis”的错误说法
- 补充当前 DSA overlay 行为说明：结构化结果会在最后阶段影响 `final_score`、风险判断和最终排名
