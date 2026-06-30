# 横向比较与短板

## 对比对象

| 项目 | 主要定位 | 强项 | 与 AlphaSift 的关系 |
|---|---|---|---|
| AlphaSift | 全市场候选发现与 LLM 横向排序 | A 股全市场硬筛、结构化 LLM 重排、组合风险桶、可插拔 L3、T+N 轻量评估 | 本项目主体 |
| daily_stock_analysis | 自选股/单股深度分析和通知 | 单股分析、仪表盘、推送、多市场自选股 | AlphaSift 上游筛出候选后，可用 DSA 做 L3 深度分析 |
| daily_ai_assistant | LLM 助手、自动化和通知 | 多渠道 LLM 配置、任务自动化、消息触达 | AlphaSift 可复用其 LLM 配置，但不承担通知助手职责 |
| [OpenBB](https://docs.openbb.co/odp) | 金融数据平台和研究工作流 | 多数据源整合、Python/CLI/REST/MCP/Workspace 等多消费层 | AlphaSift 不做通用金融数据平台，短板是数据源广度 |
| [Microsoft Qlib](https://www.microsoft.com/en-us/research/publication/qlib-an-ai-oriented-quantitative-investment-platform/) | AI 量化研究平台 | 数据、模型、回测、量化研究工作流 | AlphaSift 不替代 Qlib；后续可把评估/回测向 Qlib 靠拢 |
| [FinGPT](https://ai4finance.org/research/fingpt-open-source-finllm.html) | 金融 LLM 框架和模型生态 | 金融 LLM 数据、训练、适配、部署 | AlphaSift 使用通用 LLM 接口，不训练金融基座模型 |
| [Backtrader](https://www.backtrader.com/) | Python 回测和交易框架 | 策略回测、指标、分析器、交易模拟 | AlphaSift 当前只有 T+N 轻量评估，完整回测是短板 |

## AlphaSift 的优势

1. **位置清晰**：不是单股分析，也不是通知助手，而是全市场候选发现。
2. **LLM 用得克制**：LLM 只在候选池内做横向排序和语义归因，不参与硬筛，也不能推荐池外股票。
3. **输出结构化**：每个候选有因子分、LLM thesis、风险、催化、行业/主题、watch items、invalidators。
4. **组合风险可审计**：LLM 给行业/主题，代码映射风险桶并写入 `portfolio_penalty`。
5. **主题热度进入软判断**：行业/概念映射可以携带 `board_heat_score`、滚动趋势、持续性、降温状态和热度摘要，进入因子、LLM prompt 和后续归因。
6. **默认可跑、规则可覆盖**：策略 YAML 可覆盖评分曲线、风险阈值、组合桶和 scorecard。
7. **能接下游系统**：DSA、外部 HTTP 评分器都只是 L3 后置分析器，不侵入主筛选路径。

## 当前短板

| 短板 | 影响 | 补齐方向 |
|---|---|---|
| 行业/概念数据源不足 | 已支持本地映射文件、可选 AkShare 板块反查、`industry-cache` 缓存刷新、metadata/history sidecar、板块热度分、主题热度摘要、滚动趋势、持续性、降温信号和异常热度值过滤，但数据源广度仍弱 | 增加多源映射、板块层级口径归一和更完整的数据质量报告 |
| 新闻/公告/资金流上下文不足 | 已支持候选级上下文文件、可选 Top K 抓取、缓存、基础去重、来源置信度、来源权重分、压缩摘要、公告类别、事件标签、负面风险识别和策略级事件偏好，但事件效果还没有进入后验归因 | 将事件类型偏好纳入 T+N 归因统计，补更细公告分类和来源质量评估 |
| 完整回测不足 | 已支持 saved-run 批量 T+N 聚合、策略/行业/主题/风险标签/持有期维度、等权组合摘要、交易成本扣减和可选日 K 路径最大回撤/最大浮盈，但仍不能替代复权、持仓约束回测 | 继续补持仓约束和组合逐日权益曲线；后续接 Qlib/Backtrader |
| 形态验证仍偏粗 | 已支持 20 日突破幅度、区间振幅、量能比、实体强度、MA20 回踩距离、平台持续天数、T+N 形态后验标签和可选价格路径回撤/浮盈，但还没有压力密集度和盘中失效条件 | 增加前高压力密集度、盘中失效条件和组合持仓路径 |
| 数据源广度弱于 OpenBB | 已有 sina、efinance、akshare_em、em_datacenter、Tushare 兜底和日 K 多源降级，但暂不适合多资产、多市场通用研究平台 | 先做 A 股多源字段对账和质量报告，再扩展港股/美股 |
| 缺少 UI/通知层 | 不适合直接作为每日推送产品 | 与 daily_ai_assistant 或其他通知系统解耦集成 |

## 补短板优先级

1. **行业/概念映射**  
   候选、LLM 上下文和组合分散层已支持 `industry/concepts/board_heat_score`，`industry-cache` 可刷新本地缓存并写 metadata/history，加载映射时会回填滚动趋势、持续性、降温和状态字段，并跳过异常热度值；下一步补板块层级口径归一和更完整的数据质量报告。

2. **候选级新闻/公告/资金流摘要**  
   当前可用 `--candidate-context-file` 注入，也可用 `--collect-candidate-context` 对 Top K 抓取并缓存；抓取结果已有来源数、来源置信度、来源权重分、压缩摘要、公告类别、事件标签和负面风险识别，策略 YAML 可用 `event_profile` 配置偏好和来源权重。下一步把事件类型偏好纳入 T+N 归因统计。

3. **形态类日 K 特征增强**  
   `volume_breakout` 和 `shrink_pullback` 已使用 20 日突破/区间/量能/实体/回踩/平台天数字段，`evaluate` 会标记突破延续/失败，启用价格路径后会输出最大回撤/最大浮盈；下一步补压力密集度和盘中失效条件。

4. **批量评估报告**  
   当前已能按策略、行业、主题、标签、风险标记、组合标记、持有期和等权组合聚合，并可扣交易成本；启用价格路径后可估算最大回撤和最大浮盈。下一步补持仓约束和组合逐日权益曲线。

5. **外部框架对接**  
   Qlib/Backtrader 适合作为完整回测后端，但不应进入主筛选链路。

## 自检命令

```bash
alphasift audit
alphasift audit --json
```

自检会输出：

- 策略数量与分类
- 四类 profile 覆盖情况
- 策略级配置缺口
- 项目级短板
- 下一步优先级
