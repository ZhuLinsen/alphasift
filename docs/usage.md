# 使用指南

这份文档放 README 之外的日常用法：安装、CLI 命令、Python 调用、上下文注入和评估闭环。

## 安装

```bash
pip install -e .
cp .env.example .env
```

如果暂时不用 LLM 排序，运行命令时加 `--no-llm` 即可，不需要配置模型 key。

## 三步跑通

```bash
alphasift strategies

alphasift screen dual_low --no-llm --explain

alphasift screen dual_low --no-llm --save-run
alphasift runs
alphasift evaluate <run_id> --explain
```

策略目录也可以输出更完整的能力描述，方便 UI、agent 或外部系统选择合适策略：

```bash
alphasift strategies --explain
alphasift strategies --json
```

结构化输出包含策略分类、标签、数据依赖、是否需要日 K、必需 snapshot/daily 字段、活跃 hard filters、因子权重和 profile 覆盖项。

按具体策略预检数据源字段覆盖：

```bash
alphasift doctor data-sources --strategy low_volatility_quality --no-live --explain
alphasift doctor data-sources --all-strategies --no-live --explain
```

单策略模式会列出该策略依赖的 snapshot 字段和 daily 特征字段；全策略模式会输出策略覆盖矩阵，方便 UI/API 或 agent 判断哪些策略依赖日 K、哪些字段是数据源稳定性的关键路径。去掉 `--no-live` 后会发起真实取数 smoke test，并在字段缺失、缓存过期或数据源降级时输出 `snapshot_missing`、`daily_missing`、`source_errors` 和修复建议。

## 常用场景

使用 LLM 横向排序：

```bash
alphasift screen balanced_alpha
```

复用其他项目的 LiteLLM 配置文件：

```bash
alphasift --env-file /home/ubuntu/daily_ai_assistant/.env screen balanced_alpha
```

带市场、主题或新闻背景的 LLM 排序：

```bash
alphasift screen balanced_alpha --context "今日券商板块放量，低估值金融获得资金回流"
```

注入按候选代码对齐的新闻、公告、资金流或研究摘要：

```bash
alphasift screen balanced_alpha --candidate-context-file candidate_context.csv
```

默认运行本地 L3 scorecard 后置评分器：

```bash
alphasift screen balanced_alpha --explain
```

追加 DSA 作为可选 L3 后置分析器之一：

```bash
alphasift screen dual_low --post-analyzer dsa
```

显式关闭 L3 后置评分或分析：

```bash
alphasift screen dual_low --no-post-analysis
```

项目和策略自检：

```bash
alphasift audit
alphasift audit --json
```

刷新行业、概念、板块热度映射缓存：

```bash
alphasift industry-cache --output data/industry_map.csv --explain
alphasift screen balanced_alpha --industry-map-file data/industry_map.csv
```

批量评估最近保存的运行：

```bash
alphasift evaluate-batch --limit 20 --explain
```

评估时额外抓取日 K 路径，输出最大回撤和最大浮盈：

```bash
alphasift evaluate <run_id> --with-price-path --explain
```

## Python 调用

```python
from alphasift import evaluate_saved_run, evaluate_saved_runs, screen

result = screen("dual_low", use_llm=False)
for p in result.picks:
    print(f"{p.rank}. {p.code} {p.name} score={p.final_score:.1f}")
```

## 保存与评估

`alphasift screen --save-run` 会保存策略版本、数据源、降级记录、候选、分数、风险字段、后置分析结果和保存时价格。后续可用：

```bash
alphasift evaluate <run_id> --explain
alphasift evaluate-batch --limit 20 --explain
```

评估会用保存时价格与评估时最新快照价格计算 T+N 收益、胜率、缺失报价、交易成本扣减、等权组合摘要和形态后验标签。启用 `--with-price-path` 后，会额外估算最大回撤和最大浮盈。

## 自定义策略

在 `strategies/` 目录添加 YAML 文件即可，文件名就是策略标识。完整写法见 [strategy-guide.md](strategy-guide.md)，内置策略说明见 [../strategies/README.md](../strategies/README.md)。
