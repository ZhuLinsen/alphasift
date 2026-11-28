<div align="center">

> [!NOTE]
> 📌 **完整中文主文档位于 [README.md](README.md)**（本页保留兼容旧外链与收藏入口）。
> 👉 [**阅读完整中文文档 README.md**](README.md) · [**打开公开实时战绩看板**](https://alphasift.zhulinsen.tech/?lang=zh) · [**GitHub 仓库点 Star ⭐**](https://github.com/ZhuLinsen/alphasift/stargazers)

<a href="https://alphasift.zhulinsen.tech/?lang=zh">
  <img src="docs/assets/alphasift-logo.svg" alt="AlphaSift Logo" width="440">
</a>

简体中文主文档：[README.md](README.md) | [English](README.en.md) | [日本語](README.ja.md)

# 🔎 AlphaSift

**AI 量化选股引擎 · 公开 T+N 验真账本**

*A股 / 美股 / 港股 / 日韩台印 7 市场全量初筛 → 代码级公告排雷 → 次日开盘价 T+5 / T+10 / T+20 公开追踪*

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/alphasift?style=social)](https://github.com/ZhuLinsen/alphasift/stargazers)
[![PyPI](https://img.shields.io/pypi/v/alphasift?color=2563eb)](https://pypi.org/project/alphasift/)
[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-0ea5e9.svg)](https://alphasift.zhulinsen.tech/?lang=zh)
[![MCP Ready](https://img.shields.io/badge/MCP-14%20Tools%20STDIO-8b5cf6.svg)](docs/ecosystem.md)

</div>

<p align="center">
  <a href="https://alphasift.zhulinsen.tech/?lang=zh">
    <img src="docs/assets/dashboard-preview.gif" alt="AlphaSift 在线看板交互演示" width="800">
  </a>
</p>

## ✨ 核心能力（零 Key 可跑 · 可证伪）

- **全市场规则初筛（零 API Key）**：覆盖 A 股、美股、港股、日韩台印 7 市场，12 套透明 YAML 策略 + 8 行业桶硬上限正交分散。
- **代码硬排雷 + 公开实盘账本**：接入大模型遇重大利空在 Python 代码层面硬封顶 `llm_score <= 35`；所有选股落盘 [`track-record`](https://github.com/ZhuLinsen/alphasift/tree/track-record) 分支，按 `next_open` 扣除一字涨停核算 `T+5 / T+10 / T+20` 超额收益，同日对照 AI 与纯规则。
- **原生 14 工具 MCP & 免费云端运行**：零依赖接入 Claude Code / Cursor / Codex / OpenClaw，或 Fork 后零成本使用 GitHub Actions 盘后自动推消息。

## ⚡ 30 秒快速开始

```bash
pip install alphasift
alphasift quickstart                            # 30 秒端到端演示（零 API Key）
alphasift screen dual_low --no-llm              # 跑 A 股双低纯规则全市场筛选
uvx alphasift mcp                               # 零安装启动 14 工具 STDIO MCP Server
alphasift serve --host 127.0.0.1 --port 8765    # 打开本机 Web 投研工作台 (/ui)
```

> ⭐ **觉得「次日开盘价 T+N 公开验真 + 代码级公告排雷」有参考价值？** 点右上角 **Star** 追踪每日盘后策略榜单与新形态上线；欢迎查看完整中文文档 [README.md](README.md)、打开 [公开实时看板](https://alphasift.zhulinsen.tech/?lang=zh) 或在 [Discussions](https://github.com/ZhuLinsen/alphasift/discussions) 提出规则建议。
