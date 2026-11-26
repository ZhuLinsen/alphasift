# -*- coding: utf-8 -*-
"""Self-contained zero-dependency local interactive Workbench UI for ``alphasift serve``."""

from __future__ import annotations


def render_workbench_html() -> str:
    """Return a single-file offline-safe HTML workbench interacting with local JSON endpoints."""
    return """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20viewBox%3D%270%200%2032%2032%27%3E%3Crect%20width%3D%2732%27%20height%3D%2732%27%20rx%3D%278%27%20fill%3D%27%23090d16%27%2F%3E%3Cpath%20d%3D%27M6%208h20l-7.5%208.8v6.6l-5%202.4V16.8L6%208z%27%20fill%3D%27%233b82f6%27%20fill-opacity%3D%27.25%27%20stroke%3D%27%2360a5fa%27%20stroke-width%3D%272.2%27%20stroke-linejoin%3D%27round%27%2F%3E%3Ccircle%20cx%3D%2723%27%20cy%3D%2723%27%20r%3D%272.5%27%20fill%3D%27%2334d399%27%2F%3E%3C%2Fsvg%3E">
<title>AlphaSift · Local Quantitative Workbench</title>
<style>
  :root {
    --bg: #09090b;
    --surface: #111115;
    --surface-2: #17171d;
    --ink: #f4f4f5;
    --muted: #8e8e9a;
    --border: rgba(255, 255, 255, 0.085);
    --accent: #3b82f6;
    --accent-hi: #60a5fa;
    --emerald: #10b981;
    --amber: #fbbf24;
    --rose: #f43f5e;
    --status-ok: #38bdf8;
    --up: #f87171;
    --down: #34d399;
    --mono: "JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, Monaco, Consolas, monospace;
    --sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  }
  html[data-theme="light"] {
    --bg: #fafafa;
    --surface: #ffffff;
    --surface-2: #f4f4f5;
    --ink: #09090b;
    --muted: #52525b;
    --border: rgba(9, 9, 11, 0.1);
    --accent: #1d4ed8;
    --accent-hi: #2563eb;
    --emerald: #059669;
    --amber: #b45309;
    --rose: #e11d48;
    --status-ok: #0284c7;
    --up: #dc2626;
    --down: #059669;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: var(--sans);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1260px; margin: 0 auto; padding: 20px 18px 48px; }
  header {
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
    gap: 12px; padding-bottom: 14px; border-bottom: 1px solid var(--border); margin-bottom: 18px;
  }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand-mark {
    width: 34px; height: 34px; border-radius: 9px;
    background: var(--surface-2); border: 1px solid var(--border); color: var(--accent-hi);
    display: grid; place-items: center; font-weight: 800; font-family: var(--mono);
  }
  .brand h1 { font-size: 18px; margin: 0; letter-spacing: -0.02em; }
  .brand p { font-size: 12px; margin: 2px 0 0; color: var(--muted); }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  button, select, input {
    font-family: inherit; color: var(--ink); background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px; padding: 6px 11px; font-size: 13px;
  }
  a.ctrl-link {
    text-decoration: none; font-family: inherit; color: var(--ink); background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px; padding: 6px 11px; font-size: 13px;
    font-weight: 600; transition: border-color .15s, background .15s;
  }
  a.ctrl-link:hover { border-color: var(--accent-hi); }
  button { cursor: pointer; font-weight: 600; transition: border-color .15s, background .15s; }
  button:hover { border-color: var(--accent-hi); }
  button.active { background: var(--accent); color: #ffffff; border-color: var(--accent); }
  button.mini-btn { padding: 3px 8px; font-size: 11.5px; }
  .card-head-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }
  .card-head-row .section-title { margin: 0; }
  .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 18px; }
  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px;
  }
  .kpi-label { font-size: 11.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .kpi-val { font-size: 24px; font-weight: 700; font-family: var(--mono); margin-top: 4px; font-variant-numeric: tabular-nums; }
  .kpi-sub { font-size: 12px; color: var(--muted); margin-top: 3px; }
  .row { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-bottom: 16px; }
  .toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; align-items: center; }
  .toolbar input { flex: 1; min-width: 200px; }
  .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
  th, td { padding: 8px 11px; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
  th { font-size: 11px; color: var(--muted); text-transform: uppercase; background: var(--surface-2); letter-spacing: 0.03em; }
  td.mono, th.mono { font-family: var(--mono); }
  .badge {
    display: inline-block; padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 600;
    background: var(--surface-2); border: 1px solid var(--border); margin-right: 4px;
  }
  .badge.ok { color: var(--status-ok); border-color: rgba(56,189,248,0.4); }
  .badge.warn { color: var(--amber); border-color: rgba(251,191,36,0.45); }
  .badge.bad { color: var(--rose); border-color: rgba(244,63,94,0.45); }
  .badge.accent { color: var(--accent-hi); border-color: rgba(96,165,250,0.45); }
  .card.bad { border-color: rgba(244,63,94,0.5); }
  .hidden { display: none; }
  pre {
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px; font-family: var(--mono); font-size: 12px; overflow-x: auto; margin: 8px 0 0;
  }
  .section-title { font-size: 15px; font-weight: 700; margin: 0 0 10px; }
  .empty { color: var(--muted); font-size: 13px; padding: 14px 0; }
  a.ep-link {
    display: inline-block; padding: 5px 10px; border: 1px solid var(--border); border-radius: 6px;
    text-decoration: none; color: var(--accent-hi); font-family: var(--mono); font-size: 12px; margin: 4px 6px 4px 0;
    background: var(--surface);
  }
  a.ep-link:hover { border-color: var(--accent-hi); }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px; margin-top: 12px; }
  .kline { width: 92px; height: 26px; display: inline-block; vertical-align: middle; }
  details.raw-toggle { margin-top: 10px; font-size: 12px; color: var(--muted); }
  details.raw-toggle summary { cursor: pointer; font-weight: 600; }
  .chg-up { color: var(--up); } .chg-down { color: var(--down); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="brand-mark">AS</div>
      <div>
        <h1 id="wb-title">AlphaSift Workbench</h1>
        <p id="wb-sub">Read-only local UI backed by JSON API + YAML strategy catalog</p>
      </div>
    </div>
    <div class="controls">
      <a class="ctrl-link" id="btn-daily-report" href="/daily-report.html" target="_blank" rel="noopener noreferrer">Daily Report</a>
      <button type="button" id="btn-refresh">Refresh</button>
      <button type="button" id="btn-lang">EN / 中文</button>
      <button type="button" id="btn-theme">Light / Dark</button>
    </div>
  </header>

  <nav class="tabs" id="tab-bar"></nav>

  <section id="panel-overview"></section>
  <section id="panel-strategies" class="hidden"></section>
  <section id="panel-patterns" class="hidden"></section>
  <section id="panel-runs" class="hidden"></section>
  <section id="panel-digest" class="hidden"></section>
  <section id="panel-mcp" class="hidden"></section>
</div>

<script>
(function () {
  "use strict";

  const SVG_NS = ["http", "://www.w3.org/2000/svg"].join("");

  const TEXT = {
    en: {
      title: "AlphaSift · Local Quantitative Workbench",
      sub: "Zero-dependency local UI for strategies, live pattern scans, saved runs & AI readiness",
      btn_report: "Daily Report",
      refresh: "Refresh",
      refreshing: "Refreshing...",
      tabs: { overview: "Overview", strategies: "Strategies", patterns: "Patterns", runs: "Runs & Picks", digest: "Markets Digest", mcp: "MCP & API" },
      kpi_strats: "Built-in Strategies",
      kpi_pats: "Pattern Catalog",
      kpi_runs: "Saved Runs",
      kpi_health: "Doctor Radar",
      doc_sources: "Data Source Readiness (Offline Check)",
      radar_status: "Radar & Notification Config",
      filter_ph: "Search name, market, category, or tag...",
      all_mkts: "All Markets",
      compare_title: "Compare Two Strategies",
      run_compare: "Compare",
      select_run: "Select Saved Run",
      no_runs: "No saved runs found yet. Run `alphasift screen <strategy> --save-run` first.",
      exposure_title: "Portfolio Topic Exposure & Replacement Candidates",
      picks_title: "Top Picks & Topic Alignment",
      digest_load: "Load Digest",
      digest_loading: "Building multi-market digest...",
      digest_date_ph: "YYYY-MM-DD (optional)",
      digest_empty: "No saved runs found for selected markets yet. Run `alphasift screen <strategy> --market us --save-run` first.",
      digest_no_picks: "No saved runs for this market on selected date.",
      digest_cols: ["Security", "Strategies", "Avg Score", "Chg%"],
      digest_card_title: "IM Push Card Preview (<1200 chars)",
      copy_card: "Copy IM Card",
      mcp_title: "STDIO MCP Client Configuration (Claude Code / Cursor / OpenClaw)",
      mcp_caps: "14 read-only tools · 4 resources · Zero-dependency STDIO JSON-RPC 2.0 (never spends LLM credits by default)",
      mcp_tools_lbl: "Highlighted Tools",
      mcp_resources_lbl: "Read-only Resources",
      markets_reg_title: "Supported Markets Registry (/markets)",
      cols_mkt: ["Market", "Currency", "Timezone", "Session", "Benchmark", "Daily Pack"],
      codex_title: "Codex CLI Quick Add",
      copy_cli: "Copy CLI",
      copy_json: "Copy JSON",
      copy_cmd: "Copy",
      copied_lbl: "Copied",
      api_title: "Read-Only JSON Endpoints",
      loading: "Loading local workbench telemetry...",
      err_prefix: "Request failed: ",
      cols_strat: ["Name", "Markets", "Category", "Version", "Horizon", "Daily Required", "Tags", "CLI"],
      cols_pat: ["Pattern", "Markets", "Family", "Min History", "Status"],
      cols_pick: ["#", "Stock", "Industry", "Score", "Topic Alignment", "Risk"],
      cols_fresh: ["Family", "State", "Cache", "Notes"],
      raw_json: "Raw JSON",
      cmp_summary: "Differences Summary",
      cmp_dim: "Dimension",
      cmp_details: "Diff Detail",
      scan_btn: "Scan Local Pack",
      scan_running: "Scanning CN DailyPack...",
      scan_need_pack: "CN DailyPack not found locally. Build it with: alphasift pack build --days 250",
      scan_title: "Latest Local Pattern Scan",
      scan_cols: ["Security", "Chg%", "Overhead", "20D K-Line"],
      replay_btn: "250D Purged Replay",
      replay_running: "Running Walk-Forward...",
      replay_title: "Purged Walk-Forward Audit (/patterns/replay)",
      replay_cols: ["Pattern", "Signals", "Split Mid", "H1 Positive Regimes", "Joint H2 Delta", "Purged H1", "Status"],
      pf_all: "All",
      pf_active: "active",
      pf_exp: "experimental",
      yes_lbl: "YES",
      no_lbl: "NO",
      radar_llm: "LLM Track",
      radar_notify: "IM Notify",
      radar_pack: "CN DailyPack",
      radar_parity: "Pattern Parity",
    },
    zh: {
      title: "AlphaSift · 本地量化工作台",
      sub: "零外部依赖本地 Web UI — 策略对比、本地形态扫描、历史归因与就绪自检",
      btn_report: "盘后日报",
      refresh: "刷新数据",
      refreshing: "正在刷新…",
      tabs: { overview: "总览与自检", strategies: "内置策略", patterns: "形态扫描", runs: "历史运行与持仓暴露", digest: "多市场摘要", mcp: "MCP 与 API" },
      kpi_strats: "内置 YAML 策略",
      kpi_pats: "形态模板",
      kpi_runs: "已保存运行",
      kpi_health: "系统就绪度",
      doc_sources: "数据源健康与新鲜度检查",
      radar_status: "模型与推送就绪状态",
      filter_ph: "搜索策略名、市场、分类或标签…",
      all_mkts: "全部市场",
      compare_title: "双策略结构化对比",
      run_compare: "对比",
      select_run: "选择已保存运行",
      no_runs: "暂无保存的选股记录，可先运行 `alphasift screen <strategy> --save-run`。",
      exposure_title: "组合主题暴露、集中度预警与替补候选",
      picks_title: "入选标的与热点对齐明细",
      digest_load: "生成摘要",
      digest_loading: "正在汇总多市场选股摘要…",
      digest_date_ph: "YYYY-MM-DD（可选）",
      digest_empty: "所选市场暂无已保存运行记录，可先执行 `alphasift screen <strategy> --market us --save-run`。",
      digest_no_picks: "该市场在所选日期暂无已保存候选。",
      digest_cols: ["标的", "共振策略", "均分", "涨跌%"],
      digest_card_title: "IM 推送卡片预览（<1200 字）",
      copy_card: "复制卡片",
      mcp_title: "STDIO MCP 客户端配置 (Claude Code / Cursor / OpenClaw)",
      mcp_caps: "14 个只读工具 · 4 项资源 · 零依赖 STDIO JSON-RPC 2.0（默认零 LLM 消耗）",
      mcp_tools_lbl: "核心工具一览",
      mcp_resources_lbl: "只读资源列表",
      markets_reg_title: "支持市场规范注册表 (/markets)",
      cols_mkt: ["市场", "币种", "时区", "交易时段", "基准指数", "离线日线包"],
      codex_title: "Codex CLI 一键接入",
      copy_cli: "复制命令",
      copy_json: "复制 JSON",
      copy_cmd: "复制",
      copied_lbl: "已复制",
      api_title: "本地只读 JSON 接口索引",
      loading: "正在读取本地量化服务数据…",
      err_prefix: "请求失败：",
      cols_strat: ["策略名", "适用市场", "类型", "版本", "周期", "需日 K", "标签", "快捷命令"],
      cols_pat: ["形态名称", "市场", "谱系", "最少历史", "状态"],
      cols_pick: ["#", "标的", "行业", "综合分", "热点对齐", "风险"],
      cols_fresh: ["数据链路", "状态", "缓存状态", "建议"],
      raw_json: "查看原始 JSON",
      cmp_summary: "差异摘要",
      cmp_dim: "对比维度",
      cmp_details: "差异详情",
      scan_btn: "扫描本地日线包",
      scan_running: "正在扫描 CN 日线包…",
      scan_need_pack: "本机尚未构建 A 股日线包，可先执行：alphasift pack build --days 250",
      scan_title: "本地日线包形态扫描结果",
      scan_cols: ["股票", "涨跌%", "上方筹码", "20日K线"],
      replay_btn: "250日防泄露回放",
      replay_running: "正在运行 Walk-Forward…",
      replay_title: "Purged Walk-Forward 实证审计 (/patterns/replay)",
      replay_cols: ["形态", "信号数", "切分中点", "H1 正超额阶段", "联合 H2 超额差", "H1 剔除跨界", "状态"],
      pf_all: "全部",
      pf_active: "active",
      pf_exp: "experimental",
      yes_lbl: "是",
      no_lbl: "否",
      radar_llm: "AI 复核",
      radar_notify: "消息推送",
      radar_pack: "A 股日线包",
      radar_parity: "形态镜像同步",
    },
  };

  function initialLang() {
    const qp = new URLSearchParams(window.location.search).get("lang");
    if (qp === "en" || qp === "zh") return qp;
    try {
      const saved = window.localStorage.getItem("alphasift_wb_lang");
      if (saved === "en" || saved === "zh") return saved;
    } catch (_) {}
    return "en";
  }

  function initialTheme() {
    const qp = new URLSearchParams(window.location.search).get("theme");
    if (qp === "dark" || qp === "light") return qp;
    try {
      const saved = window.localStorage.getItem("alphasift_wb_theme");
      if (saved === "dark" || saved === "light") return saved;
    } catch (_) {}
    return "dark";
  }

  const state = {
    lang: initialLang(),
    theme: initialTheme(),
    tab: "overview",
    overview: null,
    strategies: [],
    markets: [],
    patterns: [],
    patFilter: "all",
    patternScan: null,
    patternScanErr: "",
    patternScanning: false,
    patternReplay: null,
    patternReplayErr: "",
    patternReplaying: false,
    runs: [],
    radar: null,
    sources: null,
    index: null,
    selectedRunId: "",
    activeRun: null,
    compareResult: null,
    runReqId: 0,
    refreshReqId: 0,
    refreshing: false,
    digestReqId: 0,
    digestMarkets: ["us", "hk", "jp", "kr", "tw", "in"],
    digestDate: "",
    digestData: null,
    digestErr: "",
    digestLoading: false,
  };

  function t(key) {
    return (TEXT[state.lang] && TEXT[state.lang][key]) || TEXT.en[key] || key;
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = String(v);
        else node.setAttribute(k, String(v));
      }
    }
    if (children) {
      for (const child of Array.isArray(children) ? children : [children]) {
        if (child === null || child === undefined) continue;
        node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
      }
    }
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  function syncUrl() {
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("lang", state.lang);
      url.searchParams.set("theme", state.theme);
      window.history.replaceState(null, "", url.toString());
    } catch (_) {}
  }

  function applyTheme() {
    document.documentElement.setAttribute("data-theme", state.theme);
    try { window.localStorage.setItem("alphasift_wb_theme", state.theme); } catch (_) {}
  }

  async function fetchJson(path) {
    const res = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
    if (!res.ok) {
      let msg = res.status + " " + path;
      try {
        const errObj = await res.json();
        if (errObj && errObj.error) msg = errObj.error + ": " + (errObj.message || msg);
      } catch (_) {}
      throw new Error(msg);
    }
    return await res.json();
  }

  function makeBadge(label, tone) {
    return el("span", { class: "badge" + (tone ? " " + tone : ""), text: label });
  }

  function copyText(text, btn, origLabel) {
    const markDone = () => {
      if (!btn) return;
      if (btn._copyTimer) clearTimeout(btn._copyTimer);
      btn.textContent = t("copied_lbl");
      btn._copyTimer = setTimeout(() => { btn.textContent = origLabel; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(markDone).catch(() => {
        fallbackCopy(text, markDone);
      });
    } else {
      fallbackCopy(text, markDone);
    }
  }

  function fallbackCopy(text, onDone) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      onDone();
    } catch (_) {}
  }

  function makeSvgKline(bars) {
    if (!Array.isArray(bars) || !bars.length) return el("span", { class: "kpi-sub", text: "-" });
    let lo = Infinity, hi = -Infinity;
    for (const b of bars) {
      if (!Array.isArray(b) || b.length < 4) continue;
      if (b[2] < lo) lo = b[2];
      if (b[1] > hi) hi = b[1];
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return el("span", { text: "-" });
    const span = Math.max(hi - lo, hi * 0.005, 1e-6);
    const W = 92, H = 26, pad = 2;
    const step = (W - pad * 2) / bars.length;
    const bw = Math.max(1.6, step * 0.65);
    const yFn = (p) => pad + (1 - (p - lo) / span) * (H - pad * 2);
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "kline");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    bars.forEach((b, i) => {
      const [o, h, l, c] = b;
      const cx = (pad + (i + 0.5) * step).toFixed(1);
      const col = c >= o ? "var(--up)" : "var(--down)";
      const yTop = yFn(Math.max(o, c));
      const yBot = yFn(Math.min(o, c));
      const line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("x1", cx);
      line.setAttribute("x2", cx);
      line.setAttribute("y1", yFn(h).toFixed(1));
      line.setAttribute("y2", yFn(l).toFixed(1));
      line.setAttribute("stroke", col);
      line.setAttribute("stroke-width", "1");
      const rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("x", (Number(cx) - bw / 2).toFixed(1));
      rect.setAttribute("y", yTop.toFixed(1));
      rect.setAttribute("width", bw.toFixed(1));
      rect.setAttribute("height", Math.max(1.4, yBot - yTop).toFixed(1));
      rect.setAttribute("fill", col);
      svg.appendChild(line);
      svg.appendChild(rect);
    });
    return svg;
  }

  function renderHeaderAndTabs() {
    document.getElementById("wb-title").textContent = t("title");
    document.getElementById("wb-sub").textContent = t("sub");
    const repLink = document.getElementById("btn-daily-report");
    if (repLink) repLink.textContent = t("btn_report");
    const refBtn = document.getElementById("btn-refresh");
    if (refBtn) {
      refBtn.textContent = state.refreshing ? t("refreshing") : t("refresh");
      refBtn.disabled = state.refreshing;
      refBtn.setAttribute("aria-busy", state.refreshing ? "true" : "false");
    }
    const tabLabels = t("tabs");
    const tabIds = ["overview", "strategies", "patterns", "runs", "digest", "mcp"];
    const bar = clear(document.getElementById("tab-bar"));
    for (const id of tabIds) {
      const btn = el("button", { type: "button", class: state.tab === id ? "active" : "", text: tabLabels[id] });
      btn.addEventListener("click", function () {
        state.tab = id;
        if (id === "digest" && !state.digestData && !state.digestLoading && !state.digestErr) {
          loadMarketsDigest();
        }
        renderAll();
      });
      bar.appendChild(btn);
    }
    for (const id of tabIds) {
      const sec = document.getElementById("panel-" + id);
      if (state.tab === id) sec.classList.remove("hidden");
      else sec.classList.add("hidden");
    }
  }

  function stratMarkets(s) {
    return Array.isArray(s && s.market_scope) && s.market_scope.length ? s.market_scope : ["cn"];
  }

  function renderOverview() {
    const root = clear(document.getElementById("panel-overview"));
    const ov = state.overview || {};
    const ovSum = ov.summary || {};
    const radar = state.radar || {};
    const radPat = radar.patterns || {};
    const radLlm = radar.llm || {};
    const radPack = radar.pack || {};
    const radNotify = radar.notify || {};
    const src = state.sources || {};

    const mkts = Array.from(new Set(state.strategies.flatMap((s) => stratMarkets(s))));
    const kpiGrid = el("div", { class: "kpi-grid" }, [
      el("div", { class: "card" }, [
        el("div", { class: "kpi-label", text: t("kpi_strats") }),
        el("div", { class: "kpi-val", text: String(state.strategies.length || ovSum.strategy_count || 0) }),
        el("div", { class: "kpi-sub", text: (mkts.length ? mkts : ["cn","hk","us","jp","kr","tw","in"]).join(", ").toUpperCase() }),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "kpi-label", text: t("kpi_pats") }),
        el("div", { class: "kpi-val", text: String(state.patterns.length || radPat.total || 0) }),
        el("div", {
          class: "kpi-sub",
          text: radPat.total !== undefined
            ? String(radPat.active_count || 0) + " active · " + String(radPat.experimental_count || 0) + " experimental"
            : "250-day next_open verified",
        }),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "kpi-label", text: t("kpi_runs") }),
        el("div", { class: "kpi-val", text: String(state.runs.length || ovSum.recent_run_count || 0) }),
        el("div", { class: "kpi-sub", text: state.runs[0] ? String(state.runs[0].run_id || "") : "-" }),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "kpi-label", text: t("kpi_health") }),
        el("div", { class: "kpi-val", text: String(radar.status || src.status || "ok").toUpperCase() }),
        el("div", { class: "kpi-sub", text: "LLM: " + (radLlm.configured ? String(radLlm.ai_track_mode || "configured") : "rules-only") }),
      ]),
    ]);
    root.appendChild(kpiGrid);

    const row = el("div", { class: "row" });
    const radarCard = el("div", { class: "card" }, [el("h3", { class: "section-title", text: t("radar_status") })]);
    const radarItems = [
      {
        label: t("radar_llm"),
        tone: radLlm.configured ? "ok" : "warn",
        badge: radLlm.configured ? "CONFIGURED" : "RULES",
        detail: String(radLlm.ai_track_mode || "rules_only"),
      },
      {
        label: t("radar_notify"),
        tone: radNotify.any_configured ? "ok" : "warn",
        badge: radNotify.any_configured ? "READY" : "NONE",
        detail: (radNotify.configured_channels || []).length
          ? (radNotify.configured_channels || []).join(", ")
          : "0 targets",
      },
      {
        label: t("radar_pack"),
        tone: radPack.valid && radPack.fresh ? "ok" : radPack.exists ? "warn" : "bad",
        badge: radPack.valid ? (radPack.fresh ? "FRESH" : "STALE") : "ABSENT",
        detail: (radPack.trade_date || "-") + " / " + (radPack.expected_trade_date || "-"),
      },
      {
        label: t("radar_parity"),
        tone: radPat.mirror_sync_ok ? "ok" : "bad",
        badge: radPat.mirror_sync_ok ? "SYNCED" : "DRIFT",
        detail: String(radPat.active_count || 0) + " active / " + String(radPat.experimental_count || 0) + " exp",
      },
    ];
    const list = el("div");
    for (const item of radarItems) {
      list.appendChild(el("div", { style: "margin:6px 0;" }, [
        makeBadge(item.badge, item.tone),
        el("span", { text: item.label + " — " + item.detail }),
      ]));
    }
    if (Array.isArray(radar.recommendations) && radar.recommendations.length) {
      const recBox = el("div", { style: "margin-top:8px;" });
      for (const r of radar.recommendations) {
        recBox.appendChild(el("div", { class: "kpi-sub", text: "• " + String(r) }));
      }
      list.appendChild(recBox);
    }
    radarCard.appendChild(list);

    const srcCard = el("div", { class: "card" }, [el("h3", { class: "section-title", text: t("doc_sources") })]);
    const srcOrder = (src.config && src.config.snapshot_source_priority) || [];
    if (Array.isArray(srcOrder) && srcOrder.length) {
      const box = el("div", { style: "margin-bottom:10px;" });
      for (const name of srcOrder) box.appendChild(makeBadge(String(name), "accent"));
      srcCard.appendChild(box);
    }
    const fresh = src.freshness_summary || {};
    const freshCols = t("cols_fresh");
    const tblWrap = el("div", { class: "table-wrap" });
    const fTbl = el("table");
    fTbl.appendChild(el("thead", null, el("tr", null, freshCols.map((c) => el("th", { text: c })))));
    const fBody = el("tbody");
    for (const famKey of ["snapshot", "daily"]) {
      const f = fresh[famKey];
      if (!f || typeof f !== "object") continue;
      const st = String(f.data_state || "unknown");
      const tone = st === "fresh" ? "ok" : st === "unavailable" ? "bad" : "warn";
      fBody.appendChild(el("tr", null, [
        el("td", { class: "mono", text: String(f.family || famKey) }),
        el("td", null, makeBadge(st, tone)),
        el("td", { class: "mono", text: String(f.cache_state || "-") }),
        el("td", { class: "kpi-sub", text: String(f.recommendation || "-") }),
      ]));
    }
    fTbl.appendChild(fBody);
    tblWrap.appendChild(fTbl);
    srcCard.appendChild(tblWrap);
    const rawFresh = el("details", { class: "raw-toggle" }, [
      el("summary", { text: t("raw_json") }),
      el("pre", { text: JSON.stringify(fresh, null, 2) }),
    ]);
    srcCard.appendChild(rawFresh);

    row.appendChild(radarCard);
    row.appendChild(srcCard);
    root.appendChild(row);
  }

  function renderCompareBody(container, data) {
    clear(container);
    if (!data) return;
    if (typeof data === "string") {
      container.appendChild(el("div", { class: "empty", text: data }));
      return;
    }
    const notes = Array.isArray(data.summary) ? data.summary : [];
    if (notes.length) {
      const box = el("div", { style: "margin:8px 0;" });
      box.appendChild(el("div", { class: "kpi-label", text: t("cmp_summary") }));
      for (const n of notes) box.appendChild(el("div", { class: "kpi-sub", text: "• " + String(n) }));
      container.appendChild(box);
    }
    const diffs = data.differences || {};
    const wrap = el("div", { class: "table-wrap", style: "margin-top:8px;" });
    const tbl = el("table");
    tbl.appendChild(el("thead", null, el("tr", null, [
      el("th", { text: t("cmp_dim") }),
      el("th", { text: t("cmp_details") }),
    ])));
    const tbody = el("tbody");
    for (const [k, v] of Object.entries(diffs)) {
      let summaryText = "-";
      if (v && typeof v === "object") {
        if ("changed" in v) summaryText = JSON.stringify(v.changed);
        else if (Array.isArray(v.added) || Array.isArray(v.removed)) {
          summaryText = "+" + JSON.stringify(v.added || []) + " / -" + JSON.stringify(v.removed || []);
        } else {
          summaryText = JSON.stringify(v);
        }
      }
      tbody.appendChild(el("tr", null, [
        el("td", { class: "mono", text: k }),
        el("td", { class: "kpi-sub mono", text: summaryText }),
      ]));
    }
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
    container.appendChild(wrap);
    container.appendChild(el("details", { class: "raw-toggle" }, [
      el("summary", { text: t("raw_json") }),
      el("pre", { text: JSON.stringify(data, null, 2) }),
    ]));
  }

  function renderStrategies() {
    const root = clear(document.getElementById("panel-strategies"));
    const bar = el("div", { class: "toolbar" });
    const search = el("input", { type: "search", placeholder: t("filter_ph") });
    const mktSel = el("select");
    mktSel.appendChild(el("option", { value: "", text: t("all_mkts") }));
    const allMkts = Array.from(new Set(state.strategies.flatMap((s) => stratMarkets(s)))).sort();
    for (const m of allMkts) {
      mktSel.appendChild(el("option", { value: m, text: m.toUpperCase() }));
    }
    bar.appendChild(search);
    bar.appendChild(mktSel);
    root.appendChild(bar);

    const tblWrap = el("div", { class: "table-wrap" });
    root.appendChild(tblWrap);
    const sCols = t("cols_strat");

    function drawTable() {
      const q = search.value.trim().toLowerCase();
      const mk = mktSel.value;
      const filtered = state.strategies.filter((s) => {
        const mkts = stratMarkets(s);
        if (mk && !mkts.includes(mk)) return false;
        if (!q) return true;
        const hay = [s.name, s.display_name, mkts.join(" "), s.category, (s.tags || []).join(" ")].join(" ").toLowerCase();
        return hay.includes(q);
      });
      const table = el("table");
      const thead = el("thead", null, el("tr", null, sCols.map((c) => el("th", { text: c }))));
      const tbody = el("tbody");
      for (const s of filtered) {
        const mkts = stratMarkets(s);
        const holding = (s.style && s.style.holding_period) || "-";
        const cliCmd = "alphasift screen " + String(s.name || "") + " --market " + String(mkts[0] || "cn") + " --no-llm --explain";
        const cliBtn = el("button", { type: "button", class: "mini-btn", text: t("copy_cli"), title: cliCmd });
        cliBtn.addEventListener("click", function () { copyText(cliCmd, cliBtn, t("copy_cli")); });
        tbody.appendChild(el("tr", null, [
          el("td", null, [el("strong", { text: s.display_name || s.name }), el("div", { class: "kpi-sub", text: s.name })]),
          el("td", null, mkts.map((m) => makeBadge(String(m).toUpperCase(), "accent"))),
          el("td", { text: String(s.category || "-") }),
          el("td", { class: "mono", text: String(s.version || "-") }),
          el("td", { class: "mono", text: String(holding) }),
          el("td", null, makeBadge(s.requires_daily_features ? t("yes_lbl") : t("no_lbl"), s.requires_daily_features ? "warn" : "ok")),
          el("td", null, (s.tags || []).slice(0, 4).map((tg) => makeBadge(String(tg)))),
          el("td", null, cliBtn),
        ]));
      }
      table.appendChild(thead);
      table.appendChild(tbody);
      clear(tblWrap).appendChild(table);
    }

    search.addEventListener("input", drawTable);
    mktSel.addEventListener("change", drawTable);
    drawTable();

    if (state.strategies.length >= 2) {
      const cmpCard = el("div", { class: "card", style: "margin-top:16px;" });
      cmpCard.appendChild(el("h3", { class: "section-title", text: t("compare_title") }));
      const selA = el("select");
      const selB = el("select");
      state.strategies.forEach((s, idx) => {
        selA.appendChild(el("option", { value: s.name, text: s.name }));
        const optB = el("option", { value: s.name, text: s.name });
        if (idx === 1) optB.selected = true;
        selB.appendChild(optB);
      });
      const btnCmp = el("button", { type: "button", text: t("run_compare") });
      const cmpOut = el("div");
      if (state.compareResult) renderCompareBody(cmpOut, state.compareResult);
      btnCmp.addEventListener("click", async function () {
        try {
          const data = await fetchJson(
            "/strategy-compare?base=" + encodeURIComponent(selA.value) + "&target=" + encodeURIComponent(selB.value)
          );
          state.compareResult = data;
          renderCompareBody(cmpOut, data);
        } catch (err) {
          renderCompareBody(cmpOut, t("err_prefix") + err.message);
        }
      });
      cmpCard.appendChild(el("div", { class: "toolbar" }, [selA, selB, btnCmp]));
      cmpCard.appendChild(cmpOut);
      root.appendChild(cmpCard);
    }
  }

  async function runPatternScan() {
    state.patternScanning = true;
    state.patternScanErr = "";
    renderPatterns();
    try {
      state.patternScan = await fetchJson("/patterns/scan?include_experimental=true&with_kline=1");
    } catch (err) {
      state.patternScan = null;
      state.patternScanErr = String(err.message || err);
    } finally {
      state.patternScanning = false;
      renderPatterns();
    }
  }

  async function runPatternReplay() {
    state.patternReplaying = true;
    state.patternReplayErr = "";
    renderPatterns();
    try {
      state.patternReplay = await fetchJson("/patterns/replay?cost_bps=25");
    } catch (err) {
      state.patternReplay = null;
      state.patternReplayErr = String(err.message || err);
    } finally {
      state.patternReplaying = false;
      renderPatterns();
    }
  }

  function renderPatterns() {
    const root = clear(document.getElementById("panel-patterns"));
    const bar = el("div", { class: "toolbar" });
    for (const pf of [
      ["all", t("pf_all")],
      ["active", t("pf_active")],
      ["experimental", t("pf_exp")],
    ]) {
      const btn = el("button", { type: "button", class: state.patFilter === pf[0] ? "active" : "", text: pf[1] });
      btn.addEventListener("click", function () {
        state.patFilter = pf[0];
        renderPatterns();
      });
      bar.appendChild(btn);
    }
    const scanBtn = el("button", {
      type: "button",
      id: "btn-scan-patterns",
      text: state.patternScanning ? t("scan_running") : t("scan_btn"),
    });
    scanBtn.addEventListener("click", runPatternScan);
    bar.appendChild(scanBtn);
    const replayBtn = el("button", {
      type: "button",
      id: "btn-replay-patterns",
      text: state.patternReplaying ? t("replay_running") : t("replay_btn"),
    });
    replayBtn.addEventListener("click", runPatternReplay);
    bar.appendChild(replayBtn);
    root.appendChild(bar);

    const pCols = t("cols_pat");
    const tblWrap = el("div", { class: "table-wrap" });
    const table = el("table");
    table.appendChild(el("thead", null, el("tr", null, pCols.map((c) => el("th", { text: c })))));
    const tbody = el("tbody");
    const filteredPats = state.patterns.filter((p) => {
      const st = String(p.status || "experimental");
      return state.patFilter === "all" || st === state.patFilter;
    });
    for (const p of filteredPats) {
      const statusText = String(p.status || "experimental");
      const isActive = statusText === "active";
      const mkts = Array.isArray(p.market_scope) && p.market_scope.length ? p.market_scope : ["cn"];
      tbody.appendChild(el("tr", null, [
        el("td", null, [el("strong", { text: p.display_name || p.name }), el("div", { class: "kpi-sub", text: p.name })]),
        el("td", null, mkts.map((m) => makeBadge(String(m).toUpperCase(), "accent"))),
        el("td", { text: String(p.family || "-") }),
        el("td", { class: "mono", text: p.min_history_days ? p.min_history_days + "d" : "-" }),
        el("td", null, makeBadge(statusText, isActive ? "ok" : "warn")),
      ]));
    }
    table.appendChild(tbody);
    tblWrap.appendChild(table);
    root.appendChild(tblWrap);

    if (state.patternScanErr) {
      const msg = state.patternScanErr.includes("pack_unavailable")
        ? t("scan_need_pack")
        : t("err_prefix") + state.patternScanErr;
      root.appendChild(el("div", { class: "card", style: "margin-top:14px;" }, el("div", { class: "empty", text: msg })));
    } else if (state.patternScan) {
      const sc = state.patternScan;
      const sigMap = sc.signals_by_pattern || {};
      const counts = sc.counts_by_pattern || {};
      const scanCardWrap = el("div", { style: "margin-top:16px;" }, [
        el("h3", { class: "section-title", text: t("scan_title") + " · " + String(sc.trade_date || "") }),
      ]);
      const grid = el("div", { class: "cards" });
      const sCols = t("scan_cols");
      for (const pName of Object.keys(counts)) {
        const items = sigMap[pName] || [];
        const card = el("div", { class: "card" }, [
          el("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;" }, [
            el("strong", { text: (items[0] && items[0].display_name) || pName }),
            makeBadge(String(counts[pName] || 0), (counts[pName] || 0) > 0 ? "accent" : ""),
          ]),
        ]);
        if (!items.length) {
          card.appendChild(el("div", { class: "kpi-sub", text: "-" }));
        } else {
          const innerWrap = el("div", { class: "table-wrap" });
          const stbl = el("table");
          stbl.appendChild(el("thead", null, el("tr", null, sCols.map((c) => el("th", { text: c })))));
          const sbody = el("tbody");
          for (const it of items.slice(0, 6)) {
            const chg = Number(it.change_pct || 0);
            const ov = it.overhead_supply_10pct !== null && it.overhead_supply_10pct !== undefined
              ? Number(it.overhead_supply_10pct).toFixed(0) + "%"
              : "-";
            sbody.appendChild(el("tr", null, [
              el("td", null, [el("strong", { text: it.name || it.code }), el("div", { class: "kpi-sub mono", text: it.code })]),
              el("td", { class: "mono " + (chg >= 0 ? "chg-up" : "chg-down"), text: (chg > 0 ? "+" : "") + chg.toFixed(2) + "%" }),
              el("td", { class: "mono", text: ov }),
              el("td", null, makeSvgKline(it.kline)),
            ]));
          }
          stbl.appendChild(sbody);
          innerWrap.appendChild(stbl);
          card.appendChild(innerWrap);
        }
        grid.appendChild(card);
      }
      scanCardWrap.appendChild(grid);
      root.appendChild(scanCardWrap);
    }

    if (state.patternReplayErr) {
      const msg = state.patternReplayErr.includes("pack_unavailable")
        ? t("scan_need_pack")
        : t("err_prefix") + state.patternReplayErr;
      root.appendChild(el("div", { class: "card", id: "pattern-replay-card", style: "margin-top:14px;" }, el("div", { class: "empty", text: msg })));
    } else if (state.patternReplay) {
      const rep = state.patternReplay;
      const rRows = Array.isArray(rep.patterns) ? rep.patterns : [];
      const rCols = t("replay_cols");
      const rWrap = el("div", { class: "table-wrap" });
      const rTbl = el("table");
      rTbl.appendChild(el("thead", null, el("tr", null, rCols.map((c, idx) => el("th", { class: idx === 1 || idx === 2 || idx === 4 || idx === 5 ? "mono" : "", text: c })))));
      const rBody = el("tbody");
      for (const item of rRows) {
        const wf = item.walk_forward_regime_audit || {};
        const grad = item.graduation || {};
        const deltaVal = wf.delta_non_adverse_low_overhead_vs_h2_baseline_pct;
        const hasDelta = deltaVal !== null && deltaVal !== undefined && Number.isFinite(Number(deltaVal));
        const dNum = hasDelta ? Number(deltaVal) : 0;
        const deltaTxt = hasDelta ? ((dNum > 0 ? "+" : "") + dNum.toFixed(2) + "%") : "-";
        const posRegs = Array.isArray(wf.h1_positive_regimes) && wf.h1_positive_regimes.length ? wf.h1_positive_regimes.join(", ") : "-";
        const isGrad = Boolean(grad.graduated);
        rBody.appendChild(el("tr", null, [
          el("td", null, [el("strong", { text: item.display_name || item.pattern }), el("div", { class: "kpi-sub", text: item.pattern })]),
          el("td", { class: "mono", text: String(item.total_signals ?? "-") }),
          el("td", { class: "mono", text: String(wf.eval_mid_date || "-") }),
          el("td", { class: "kpi-sub", text: posRegs }),
          el("td", { class: "mono " + (hasDelta ? (dNum >= 0 ? "chg-up" : "chg-down") : ""), text: deltaTxt }),
          el("td", { class: "mono", text: String(wf.h1_purged_signals ?? "-") }),
          el("td", null, makeBadge(isGrad ? "active" : String(item.mode || "experimental"), isGrad ? "ok" : "warn")),
        ]));
      }
      rTbl.appendChild(rBody);
      rWrap.appendChild(rTbl);
      root.appendChild(el("div", { class: "card", id: "pattern-replay-card", style: "margin-top:16px;" }, [
        el("div", { class: "card-head-row" }, [
          el("h3", { class: "section-title", text: t("replay_title") }),
          makeBadge(String(rep.walk_forward_boundary_policy || "purged_by_exit_date"), "ok"),
        ]),
        rWrap,
      ]));
    }
  }

  async function selectRun(runId) {
    if (!runId) return;
    state.selectedRunId = runId;
    const reqId = ++state.runReqId;
    try {
      const data = await fetchJson("/report?run=" + encodeURIComponent(runId));
      if (reqId !== state.runReqId) return;
      state.activeRun = data;
      renderRuns();
    } catch (err) {
      if (reqId !== state.runReqId) return;
      state.activeRun = { error: err.message };
      renderRuns();
    }
  }

  function renderRuns() {
    const root = clear(document.getElementById("panel-runs"));
    if (!state.runs.length) {
      root.appendChild(el("div", { class: "card empty", text: t("no_runs") }));
      return;
    }
    const bar = el("div", { class: "toolbar" });
    bar.appendChild(el("span", { class: "kpi-label", text: t("select_run") }));
    const sel = el("select");
    for (const r of state.runs) {
      const rid = String(r.run_id || "");
      const label = rid + " · " + String(r.strategy || "") + " (" + String(r.market || "").toUpperCase() + ")";
      const opt = el("option", { value: rid, text: label });
      if (state.selectedRunId === rid) opt.selected = true;
      sel.appendChild(opt);
    }
    sel.addEventListener("change", function () { selectRun(sel.value); });
    bar.appendChild(sel);
    root.appendChild(bar);

    if (!state.activeRun) {
      selectRun(state.selectedRunId || String(state.runs[0].run_id || ""));
      return;
    }
    if (state.activeRun.error) {
      root.appendChild(el("div", { class: "card bad", text: t("err_prefix") + state.activeRun.error }));
      return;
    }
    const rep = state.activeRun;
    const sh = rep.source_health || {};
    const expMap = sh.portfolio_topic_exposure || {};
    const overList = sh.overconcentrated_topics || [];
    const repList = sh.replacement_candidates || [];

    const expCard = el("div", { class: "card", style: "margin-bottom:14px;" }, [
      el("h3", { class: "section-title", text: t("exposure_title") }),
    ]);
    const bucketEntries = Object.entries(expMap);
    if (bucketEntries.length) {
      const badges = el("div", { style: "margin-bottom:8px;" });
      for (const [bName, info] of bucketEntries) {
        const tone = info && info.overconcentrated ? "bad" : "accent";
        badges.appendChild(makeBadge(bName + ": " + String(info.count || 0) + " (" + String(info.share_pct || 0) + "%)", tone));
      }
      expCard.appendChild(badges);
    }
    if (overList.length) {
      expCard.appendChild(el("div", { style: "margin:6px 0;" }, [makeBadge("Overconcentrated: " + overList.join(", "), "bad")]));
    }
    if (repList.length) {
      expCard.appendChild(el("div", { class: "kpi-sub", text: "Replacements: " + repList.map((c) => c.code + " " + c.name + " (" + c.bucket + ")").join(" · ") }));
    }
    root.appendChild(expCard);

    const picks = rep.top_picks || [];
    const picksCard = el("div", { class: "card" }, [el("h3", { class: "section-title", text: t("picks_title") })]);
    const tblWrap = el("div", { class: "table-wrap" });
    const table = el("table");
    const pkCols = t("cols_pick");
    table.appendChild(el("thead", null, el("tr", null, pkCols.map((c, idx) => el("th", { class: idx === 0 || idx === 3 ? "mono" : "", text: c })))));
    const tbody = el("tbody");
    for (const p of picks) {
      const alignSt = p.topic_alignment_status || "unassessed";
      const alignTone = alignSt === "aligned" ? "ok" : alignSt === "unmatched" ? "warn" : "";
      const riskLvl = p.risk_level || "unassessed";
      const riskTone = riskLvl === "high" ? "bad" : riskLvl === "medium" ? "warn" : riskLvl === "low" ? "ok" : "";
      tbody.appendChild(el("tr", null, [
        el("td", { class: "mono", text: String(p.rank || "-") }),
        el("td", null, [el("strong", { text: String(p.name || p.code) }), el("div", { class: "kpi-sub mono", text: String(p.code || "") })]),
        el("td", { text: String(p.industry || "-") }),
        el("td", { class: "mono", text: String(p.final_score ?? p.screen_score ?? "-") }),
        el("td", null, [
          makeBadge(alignSt, alignTone),
          el("span", { class: "kpi-sub", text: (p.matched_topics || []).join(", ") }),
        ]),
        el("td", null, [
          makeBadge(riskLvl, riskTone),
          el("span", { class: "kpi-sub", text: (p.risk_flags || []).slice(0, 2).join(", ") }),
        ]),
      ]));
    }
    table.appendChild(tbody);
    tblWrap.appendChild(table);
    picksCard.appendChild(tblWrap);
    root.appendChild(picksCard);
  }

  const ALL_DIGEST_MARKETS = ["us", "hk", "jp", "kr", "tw", "in", "cn"];

  async function loadMarketsDigest() {
    const reqId = ++state.digestReqId;
    const mkts = state.digestMarkets.length ? state.digestMarkets : ["us", "hk", "jp", "kr", "tw", "in"];
    let url = "/markets-digest?markets=" + encodeURIComponent(mkts.join(","));
    const td = String(state.digestDate || "").trim();
    if (td) url += "&trade_date=" + encodeURIComponent(td);
    state.digestLoading = true;
    state.digestErr = "";
    renderDigest();
    try {
      const payload = await fetchJson(url);
      if (reqId !== state.digestReqId) return;
      state.digestData = payload;
    } catch (err) {
      if (reqId !== state.digestReqId) return;
      state.digestData = null;
      state.digestErr = String(err.message || err);
    } finally {
      if (reqId === state.digestReqId) {
        state.digestLoading = false;
        renderDigest();
      }
    }
  }

  function appendMarketsRegistryCard(root) {
    const mkts = Array.isArray(state.markets) ? state.markets : [];
    if (!mkts.length) return;
    const mCols = t("cols_mkt");
    const wrap = el("div", { class: "table-wrap" });
    const tbl = el("table");
    tbl.appendChild(el("thead", null, el("tr", null, mCols.map((c, idx) => el("th", { class: idx === 1 || idx === 3 ? "mono" : "", text: c })))));
    const tbody = el("tbody");
    for (const spec of mkts) {
      const session = String(spec.session_open || "-") + "-" + String(spec.session_close || "-");
      const bench = spec.benchmark_name || spec.benchmark || "-";
      tbody.appendChild(el("tr", null, [
        el("td", null, [el("strong", { text: String(spec.id || "").toUpperCase() }), el("span", { class: "kpi-sub", style: "margin-left:6px;", text: String(spec.name || "") })]),
        el("td", { class: "mono", text: String(spec.currency || "-") }),
        el("td", { class: "kpi-sub mono", text: String(spec.timezone || "-") }),
        el("td", { class: "mono", text: session }),
        el("td", { text: String(bench) }),
        el("td", null, makeBadge(spec.supports_daily_pack ? t("yes_lbl") : t("no_lbl"), spec.supports_daily_pack ? "ok" : "")),
      ]));
    }
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
    root.appendChild(el("div", { class: "card", id: "markets-registry-card", style: "margin-top:14px;" }, [
      el("h3", { class: "section-title", text: t("markets_reg_title") }),
      wrap,
    ]));
  }

  function renderDigest() {
    const root = clear(document.getElementById("panel-digest"));
    const mktMap = Object.fromEntries((state.markets || []).map((x) => [x.id, x]));
    const bar = el("div", { class: "toolbar" });
    for (const m of ALL_DIGEST_MARKETS) {
      const active = state.digestMarkets.includes(m);
      const mSpec = mktMap[m];
      const mAttrs = { type: "button", class: active ? "active" : "", text: m.toUpperCase() };
      if (mSpec) mAttrs.title = String(mSpec.name || "") + " · " + String(mSpec.currency || "") + " · " + String(mSpec.timezone || "") + " " + String(mSpec.session_open || "") + "-" + String(mSpec.session_close || "");
      const mBtn = el("button", mAttrs);
      mBtn.addEventListener("click", function () {
        if (state.digestMarkets.includes(m)) {
          if (state.digestMarkets.length <= 1) return;
          state.digestMarkets = state.digestMarkets.filter((x) => x !== m);
        } else {
          const next = state.digestMarkets.concat([m]);
          state.digestMarkets = ALL_DIGEST_MARKETS.filter((x) => next.includes(x));
        }
        state.digestData = null;
        state.digestErr = "";
        loadMarketsDigest();
      });
      bar.appendChild(mBtn);
    }
    const dateInp = el("input", {
      type: "text",
      id: "digest-date-input",
      placeholder: t("digest_date_ph"),
      value: state.digestDate,
      style: "flex:0 1 170px;min-width:140px;",
    });
    dateInp.addEventListener("input", function () {
      state.digestDate = dateInp.value;
    });
    bar.appendChild(dateInp);
    const loadBtn = el("button", {
      type: "button",
      id: "btn-load-digest",
      text: state.digestLoading ? t("digest_loading") : t("digest_load"),
    });
    if (state.digestLoading) loadBtn.disabled = true;
    loadBtn.addEventListener("click", loadMarketsDigest);
    bar.appendChild(loadBtn);
    root.appendChild(bar);

    if (state.digestErr) {
      root.appendChild(el("div", { class: "card bad", text: t("err_prefix") + state.digestErr }));
      appendMarketsRegistryCard(root);
      return;
    }
    const d = state.digestData;
    if (!d) {
      root.appendChild(el("div", { class: "card empty", text: state.digestLoading ? t("digest_loading") : t("digest_empty") }));
      appendMarketsRegistryCard(root);
      return;
    }

    const metaRow = el("div", { style: "margin-bottom:12px;" }, [
      makeBadge(String(d.trade_date || "-"), "accent"),
      makeBadge(String(d.im_card_chars || 0) + " chars", "ok"),
    ]);
    root.appendChild(metaRow);

    const sections = Array.isArray(d.market_sections) ? d.market_sections : [];
    const dCols = t("digest_cols");
    const grid = el("div", { class: "cards" });
    let anyPick = false;
    for (const sec of sections) {
      const top = Array.isArray(sec.top_picks) ? sec.top_picks : [];
      if (top.length) anyPick = true;
      const card = el("div", { class: "card" }, [
        el("div", { class: "card-head-row" }, [
          el("strong", { text: String(sec.market_name || sec.market || "").toUpperCase() + " (" + String(sec.market || "").toUpperCase() + ")" }),
          makeBadge(String(sec.strategy_count || 0) + " · " + String(sec.trade_date || "-"), top.length ? "accent" : ""),
        ]),
      ]);
      if (!top.length) {
        card.appendChild(el("div", { class: "kpi-sub", text: t("digest_no_picks") }));
      } else {
        const innerWrap = el("div", { class: "table-wrap" });
        const tbl = el("table");
        tbl.appendChild(el("thead", null, el("tr", null, dCols.map((c, idx) => el("th", { class: idx >= 2 ? "mono" : "", text: c })))));
        const tbody = el("tbody");
        for (const p of top) {
          const scoreTxt = p.avg_final_score !== null && p.avg_final_score !== undefined
            ? Number(p.avg_final_score).toFixed(1)
            : "-";
          const hasChg = p.change_pct !== null && p.change_pct !== undefined && Number.isFinite(Number(p.change_pct));
          const chgNum = hasChg ? Number(p.change_pct) : 0;
          const chgCls = hasChg ? ("mono " + (chgNum >= 0 ? "chg-up" : "chg-down")) : "mono";
          const chgTxt = hasChg ? ((chgNum > 0 ? "+" : "") + chgNum.toFixed(2) + "%") : "-";
          const stratList = Array.isArray(p.strategy_display_names) && p.strategy_display_names.length
            ? p.strategy_display_names
            : (p.strategies || []);
          tbody.appendChild(el("tr", null, [
            el("td", null, [el("strong", { text: String(p.name || p.code || "") }), el("div", { class: "kpi-sub mono", text: String(p.code || "") })]),
            el("td", { class: "kpi-sub", text: String(p.strategy_count || 1) + " · " + stratList.slice(0, 2).join(", ") }),
            el("td", { class: "mono", text: scoreTxt }),
            el("td", { class: chgCls, text: chgTxt }),
          ]));
        }
        tbl.appendChild(tbody);
        innerWrap.appendChild(tbl);
        card.appendChild(innerWrap);
      }
      grid.appendChild(card);
    }
    root.appendChild(grid);
    if (!anyPick) {
      root.appendChild(el("div", { class: "card empty", style: "margin-top:12px;", text: t("digest_empty") }));
    }

    const cardMd = String(d.im_card_markdown || "");
    const btnCopyCard = el("button", { type: "button", class: "mini-btn", text: t("copy_card") });
    btnCopyCard.addEventListener("click", function () { copyText(cardMd, btnCopyCard, t("copy_card")); });
    root.appendChild(el("div", { class: "card", style: "margin-top:14px;" }, [
      el("div", { class: "card-head-row" }, [
        el("h3", { class: "section-title", text: t("digest_card_title") }),
        btnCopyCard,
      ]),
      el("pre", { text: cardMd }),
      el("details", { class: "raw-toggle" }, [
        el("summary", { text: t("raw_json") }),
        el("pre", { text: JSON.stringify(d, null, 2) }),
      ]),
    ]));
    appendMarketsRegistryCard(root);
  }

  function renderMcp() {
    const root = clear(document.getElementById("panel-mcp"));
    const mcpJson = JSON.stringify({
      mcpServers: {
        alphasift: {
          command: "alphasift",
          args: ["mcp"],
        },
      },
    }, null, 2);
    const btnCopyJson = el("button", { type: "button", class: "mini-btn", text: t("copy_json") });
    btnCopyJson.addEventListener("click", function () { copyText(mcpJson, btnCopyJson, t("copy_json")); });
    const toolRow = el("div", { style: "margin:8px 0;" }, [el("span", { class: "kpi-sub", style: "margin-right:6px;", text: t("mcp_tools_lbl") + ":" })]);
    for (const tn of ["alphasift_markets", "alphasift_screen", "alphasift_replay_patterns", "alphasift_markets_digest", "alphasift_daily_report", "alphasift_overview", "alphasift_list_strategies"]) {
      toolRow.appendChild(makeBadge(tn, "accent"));
    }
    const resRow = el("div", { style: "margin:6px 0 8px;" }, [el("span", { class: "kpi-sub", style: "margin-right:6px;", text: t("mcp_resources_lbl") + ":" })]);
    for (const rn of ["alphasift://skill", "alphasift://strategies", "alphasift://patterns", "alphasift://markets"]) {
      resRow.appendChild(makeBadge(rn, "ok"));
    }
    const mcpCard = el("div", { class: "card", style: "margin-bottom:14px;" }, [
      el("div", { class: "card-head-row" }, [
        el("h3", { class: "section-title", text: t("mcp_title") }),
        btnCopyJson,
      ]),
      el("div", { class: "kpi-sub", text: t("mcp_caps") }),
      toolRow,
      resRow,
      el("pre", { text: mcpJson }),
    ]);
    root.appendChild(mcpCard);

    const codexCmd = "codex mcp add alphasift -- alphasift mcp";
    const btnCopyCodex = el("button", { type: "button", class: "mini-btn", text: t("copy_cmd") });
    btnCopyCodex.addEventListener("click", function () { copyText(codexCmd, btnCopyCodex, t("copy_cmd")); });
    const codexCard = el("div", { class: "card", style: "margin-bottom:14px;" }, [
      el("div", { class: "card-head-row" }, [
        el("h3", { class: "section-title", text: t("codex_title") }),
        btnCopyCodex,
      ]),
      el("pre", { text: codexCmd }),
    ]);
    root.appendChild(codexCard);

    const epCard = el("div", { class: "card" }, [el("h3", { class: "section-title", text: t("api_title") })]);
    const eps = (state.index && state.index.endpoints) || [
      "/health", "/overview", "/markets", "/strategies", "/patterns", "/patterns/replay", "/runs",
      "/doctor/radar", "/doctor/data-sources", "/result-schema", "/daily-report-schema",
      "/daily-report", "/daily-report.html", "/markets-digest",
    ];
    const box = el("div");
    for (const ep of eps) {
      if (typeof ep === "string" && ep.startsWith("/") && !ep.startsWith("//")) {
        box.appendChild(el("a", { class: "ep-link", href: ep, target: "_blank", rel: "noopener noreferrer", text: ep }));
      }
    }
    epCard.appendChild(box);
    root.appendChild(epCard);
  }

  function renderAll() {
    renderHeaderAndTabs();
    renderOverview();
    renderStrategies();
    renderPatterns();
    renderRuns();
    renderDigest();
    renderMcp();
  }

  async function refreshAll() {
    const reqId = ++state.refreshReqId;
    state.refreshing = true;
    renderHeaderAndTabs();
    let ok = false;
    try {
      const [idx, ov, strats, pats, runs, radar, src, mkts] = await Promise.all([
        fetchJson("/?format=json").catch(() => null),
        fetchJson("/overview").catch(() => null),
        fetchJson("/strategies").catch(() => ({ strategies: [] })),
        fetchJson("/patterns").catch(() => ({ patterns: [] })),
        fetchJson("/runs").catch(() => ({ runs: [] })),
        fetchJson("/doctor/radar").catch(() => null),
        fetchJson("/doctor/data-sources?live=0").catch(() => null),
        fetchJson("/markets").catch(() => ({ markets: [] })),
      ]);
      if (reqId !== state.refreshReqId) return;
      state.index = idx;
      state.overview = ov;
      state.strategies = (strats && (strats.strategies || strats.items)) || [];
      state.markets = (mkts && mkts.markets) || [];
      state.patterns = (pats && (pats.patterns || pats.items)) || [];
      state.runs = (runs && (runs.runs || runs.items)) || [];
      state.radar = radar;
      state.sources = src;
      state.activeRun = null;
      state.digestReqId += 1;
      state.digestLoading = false;
      state.digestData = null;
      state.digestErr = "";
      ok = true;
    } finally {
      if (reqId === state.refreshReqId) {
        state.refreshing = false;
        renderAll();
        if (ok && state.tab === "digest") {
          loadMarketsDigest();
        }
      }
    }
  }

  document.getElementById("btn-refresh").addEventListener("click", refreshAll);
  document.getElementById("btn-lang").addEventListener("click", function () {
    state.lang = state.lang === "en" ? "zh" : "en";
    try { window.localStorage.setItem("alphasift_wb_lang", state.lang); } catch (_) {}
    syncUrl();
    renderAll();
  });
  document.getElementById("btn-theme").addEventListener("click", function () {
    state.theme = state.theme === "dark" ? "light" : "dark";
    applyTheme();
    syncUrl();
  });

  applyTheme();
  renderAll();
  refreshAll();
})();
</script>
</body>
</html>
"""
