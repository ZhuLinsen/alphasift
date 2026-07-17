# Changelog

## Unreleased

- LLM 排名按候选数量动态提升输出 token 上限（最高 8192），不完整或经过 JSON repair 的响应执行一次紧凑重试，并按覆盖率及 repair 数量选择结果
- ScreenResult、运行 sidecar、RunReport 与 DSA adapter 新增 complete/partial/fallback/disabled 排名状态、匹配数、请求数和 repair 状态，低于覆盖门槛时继续回退因子排序
- 支持 DSA 通过 `context["dsa"]` 注入候选 provider，AlphaSift 会在 L1 初筛后、LLM 重排前补充 DSA 行情、基本面和新闻上下文
- `dsa_adapter.screen()` 现在会透传 DSA context，并在候选结果中保留 `dsa_context`、`dsa_news` 和 `dsa_analysis_summary`
- LLM ranking prompt 会读取候选上的 DSA provider context，便于排序阶段利用 DSA 已有数据能力

## 2026-04-12

- 明确说明 `DSA` 指外部项目 `daily_stock_analysis`，补充两者的职责边界与调用关系
- 更新 README、Skill 文档和设计说明，说明 DSA 只在最终入围候选上调用
- 修正文档中过期描述：移除对 `shrink_pullback` 可直接运行和“未实现 L3 deep_analysis”的错误说法
- 补充当前 DSA overlay 行为说明：结构化结果会在最后阶段影响 `final_score`、风险判断和最终排名
