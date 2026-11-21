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
<title>AlphaSift · Local Quantitative Workbench</title>
<style>
  :root {
    --bg: #0b1120;
    --surface: #111827;
    --surface-2: #1a2334;
    --ink: #e5edf7;
    --muted: #94a3b8;
    --border: rgba(148, 163, 184, 0.22);
    --accent: #38bdf8;
    --emerald: #10b981;
    --amber: #f59e0b;
    --rose: #f43f5e;
    --violet: #a78bfa;
    --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", "Hiragino Sans", sans-serif;
  }
  html[data-theme="light"] {
    --bg: #f8fafc;
    --surface: #ffffff;
    --surface-2: #f1f5f9;
    --ink: #0f172a;
    --muted: #475569;
    --border: rgba(15, 23, 42, 0.14);
    --accent: #0284c7;
    --emerald: #059669;
    --amber: #d97706;
    --rose: #e11d48;
    --violet: #7c3aed;
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
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 18px;
  }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand-mark {
    width: 34px; height: 34px; border-radius: 9px;
    background: linear-gradient(135deg, var(--accent), var(--emerald));
    display: grid; place-items: center; color: #06131f; font-weight: 800; font-family: var(--mono);
  }
  .brand h1 { font-size: 18px; margin: 0; letter-spacing: -0.01em; }
  .brand p { font-size: 12px; margin: 2px 0 0; color: var(--muted); }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  button, select, input {
    font-family: inherit;
    color: var(--ink);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 6px 11px;
    font-size: 13px;
  }
  button { cursor: pointer; font-weight: 600; transition: border-color .15s, background .15s; }
  button:hover { border-color: var(--accent); }
  button.active { background: var(--accent); color: #06131f; border-color: var(--accent); }
  .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 18px; }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
  }
  .kpi-label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .kpi-val { font-size: 24px; font-weight: 700; font-family: var(--mono); margin-top: 4px; }
  .kpi-sub { font-size: 12px; color: var(--muted); margin-top: 3px; }
  .row { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-bottom: 16px; }
  .toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; align-items: center; }
  .toolbar input { flex: 1; min-width: 200px; }
  .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 9px 11px; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
  th { font-size: 11.5px; color: var(--muted); text-transform: uppercase; background: var(--surface-2); letter-spacing: 0.03em; }
  td.mono, th.mono { font-family: var(--mono); }
  .badge {
    display: inline-block; padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 600;
    background: var(--surface-2); border: 1px solid var(--border); margin-right: 4px;
  }
  .badge.ok { color: var(--emerald); border-color: rgba(16,185,129,0.45); }
  .badge.warn { color: var(--amber); border-color: rgba(245,158,11,0.45); }
  .badge.bad { color: var(--rose); border-color: rgba(244,63,94,0.45); }
  .badge.accent { color: var(--accent); border-color: rgba(56,189,248,0.45); }
  .hidden { display: none; }
  pre {
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px; font-family: var(--mono); font-size: 12px; overflow-x: auto; margin: 8px 0 0;
  }
  .section-title { font-size: 15px; font-weight: 700; margin: 0 0 10px; }
  .empty { color: var(--muted); font-size: 13px; padding: 14px 0; }
  a.ep-link {
    display: inline-block; padding: 5px 10px; border: 1px solid var(--border); border-radius: 6px;
    text-decoration: none; color: var(--accent); font-family: var(--mono); font-size: 12px; margin: 4px 6px 4px 0;
    background: var(--surface);
  }
  a.ep-link:hover { border-color: var(--accent); }
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
  <section id="panel-mcp" class="hidden"></section>
</div>

<script>
(function () {
  "use strict";

  const TEXT = {
    en: {
      title: "AlphaSift · Local Quantitative Workbench",
      sub: "Zero-dependency local UI for strategies, patterns, saved runs & AI readiness",
      refresh: "Refresh",
      tabs: { overview: "Overview", strategies: "Strategies", patterns: "Patterns", runs: "Runs & Picks", mcp: "MCP & API" },
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
      mcp_title: "STDIO MCP Client Configuration (Claude Code / Cursor / Codex)",
      api_title: "Read-Only JSON Endpoints",
      loading: "Loading local workbench telemetry...",
      err_prefix: "Request failed: ",
    },
    zh: {
      title: "AlphaSift · 本地量化工作台",
      sub: "零外部依赖本地 Web UI — 策略目录、形态雷达、历史选股归因与就绪自检",
      refresh: "刷新数据",
      tabs: { overview: "总览与自检", strategies: "内置策略", patterns: "形态扫描", runs: "历史运行与持仓暴露", mcp: "MCP 与 API" },
      kpi_strats: "内置 YAML 策略",
      kpi_pats: "形态模板",
      kpi_runs: "已保存运行",
      kpi_health: "系统就绪度",
      doc_sources: "数据源检查 (Offline Check)",
      radar_status: "模型与推送就绪状态",
      filter_ph: "搜索策略名、市场、分类或标签…",
      all_mkts: "全部市场",
      compare_title: "双策略并排对比",
      run_compare: "对比",
      select_run: "选择已保存运行",
      no_runs: "暂无保存的选股记录，可先运行 `alphasift screen <strategy> --save-run`。",
      exposure_title: "组合主题暴露、集中度预警与替补候选",
      picks_title: "入选标的与热点对齐明细",
      mcp_title: "STDIO MCP 客户端配置 (Claude Code / Cursor / Codex)",
      api_title: "本地只读 JSON 接口索引",
      loading: "正在读取本地量化服务数据…",
      err_prefix: "请求失败：",
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
    patterns: [],
    runs: [],
    radar: null,
    sources: null,
    index: null,
    activeRun: null,
    compareResult: null,
    runReqId: 0,
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
    if (!res.ok) throw new Error(res.status + " " + path);
    return await res.json();
  }

  function makeBadge(label, tone) {
    return el("span", { class: "badge" + (tone ? " " + tone : ""), text: label });
  }

  function renderHeaderAndTabs() {
    document.getElementById("wb-title").textContent = t("title");
    document.getElementById("wb-sub").textContent = t("sub");
    document.getElementById("btn-refresh").textContent = t("refresh");
    const tabLabels = t("tabs");
    const bar = clear(document.getElementById("tab-bar"));
    for (const id of ["overview", "strategies", "patterns", "runs", "mcp"]) {
      const btn = el("button", { type: "button", class: state.tab === id ? "active" : "", text: tabLabels[id] });
      btn.addEventListener("click", function () {
        state.tab = id;
        renderAll();
      });
      bar.appendChild(btn);
    }
    for (const id of ["overview", "strategies", "patterns", "runs", "mcp"]) {
      const sec = document.getElementById("panel-" + id);
      if (state.tab === id) sec.classList.remove("hidden");
      else sec.classList.add("hidden");
    }
  }

  function renderOverview() {
    const root = clear(document.getElementById("panel-overview"));
    const ov = state.overview || {};
    const radar = state.radar || {};
    const src = state.sources || {};

    const kpiGrid = el("div", { class: "kpi-grid" }, [
      el("div", { class: "card" }, [
        el("div", { class: "kpi-label", text: t("kpi_strats") }),
        el("div", { class: "kpi-val", text: String(state.strategies.length || ov.strategy_count || 0) }),
        el("div", { class: "kpi-sub", text: (ov.markets || ["cn","hk","us","jp","kr","tw","in"]).join(", ").toUpperCase() }),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "kpi-label", text: t("kpi_pats") }),
        el("div", { class: "kpi-val", text: String(state.patterns.length || ov.pattern_count || 0) }),
        el("div", { class: "kpi-sub", text: "250-day next_open verified" }),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "kpi-label", text: t("kpi_runs") }),
        el("div", { class: "kpi-val", text: String(state.runs.length) }),
        el("div", { class: "kpi-sub", text: state.runs[0] ? String(state.runs[0].run_id || "") : "-" }),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "kpi-label", text: t("kpi_health") }),
        el("div", { class: "kpi-val", text: String(radar.status || src.status || "ok").toUpperCase() }),
        el("div", { class: "kpi-sub", text: "LLM: " + (radar.llm_ready ? "ready" : "rules-only") }),
      ]),
    ]);
    root.appendChild(kpiGrid);

    const row = el("div", { class: "row" });
    const radarCard = el("div", { class: "card" }, [el("h3", { class: "section-title", text: t("radar_status") })]);
    const radarChecks = (radar.checks || []);
    if (radarChecks.length) {
      const list = el("div");
      for (const chk of radarChecks.slice(0, 12)) {
        const st = String(chk.status || (chk.ok ? "ok" : "warn"));
        const tone = st === "ok" || st === "pass" ? "ok" : st === "error" || st === "fail" ? "bad" : "warn";
        list.appendChild(el("div", { style: "margin:6px 0;" }, [
          makeBadge(st.toUpperCase(), tone),
          el("span", { text: (chk.name || chk.key || "check") + (chk.detail ? " — " + chk.detail : "") }),
        ]));
      }
      radarCard.appendChild(list);
    } else {
      radarCard.appendChild(el("div", { class: "empty", text: JSON.stringify({ llm_ready: radar.llm_ready, notify_targets: radar.notify_targets || [] }) }));
    }

    const srcCard = el("div", { class: "card" }, [el("h3", { class: "section-title", text: t("doc_sources") })]);
    const srcOrder = (src.source_order || (src.config && src.config.source_priority) || []);
    if (Array.isArray(srcOrder) && srcOrder.length) {
      const box = el("div");
      for (const name of srcOrder) box.appendChild(makeBadge(String(name), "accent"));
      srcCard.appendChild(box);
    }
    const fresh = src.freshness_summary || {};
    srcCard.appendChild(el("pre", { text: JSON.stringify(fresh, null, 2) }));

    row.appendChild(radarCard);
    row.appendChild(srcCard);
    root.appendChild(row);
  }

  function renderStrategies() {
    const root = clear(document.getElementById("panel-strategies"));
    const bar = el("div", { class: "toolbar" });
    const search = el("input", { type: "search", placeholder: t("filter_ph") });
    const mktSel = el("select");
    mktSel.appendChild(el("option", { value: "", text: t("all_mkts") }));
    for (const m of Array.from(new Set(state.strategies.map((s) => s.market).filter(Boolean))).sort()) {
      mktSel.appendChild(el("option", { value: m, text: m.toUpperCase() }));
    }
    bar.appendChild(search);
    bar.appendChild(mktSel);
    root.appendChild(bar);

    const tblWrap = el("div", { class: "table-wrap" });
    root.appendChild(tblWrap);

    function drawTable() {
      const q = search.value.trim().toLowerCase();
      const mk = mktSel.value;
      const filtered = state.strategies.filter((s) => {
        if (mk && s.market !== mk) return false;
        if (!q) return true;
        const hay = [s.name, s.display_name, s.market, s.category, (s.tags || []).join(" ")].join(" ").toLowerCase();
        return hay.includes(q);
      });
      const table = el("table");
      const thead = el("thead", null, el("tr", null, [
        el("th", { text: "Name" }),
        el("th", { text: "Market" }),
        el("th", { text: "Category" }),
        el("th", { text: "Version" }),
        el("th", { text: "Max Picks" }),
        el("th", { text: "Daily Required" }),
        el("th", { text: "Tags" }),
      ]));
      const tbody = el("tbody");
      for (const s of filtered) {
        tbody.appendChild(el("tr", null, [
          el("td", null, [el("strong", { text: s.display_name || s.name }), el("div", { class: "kpi-sub", text: s.name })]),
          el("td", null, makeBadge(String(s.market || "-").toUpperCase(), "accent")),
          el("td", { text: String(s.category || "-") }),
          el("td", { class: "mono", text: String(s.version || "-") }),
          el("td", { class: "mono", text: String(s.max_output || "-") }),
          el("td", null, makeBadge(s.requires_daily_features ? "YES" : "NO", s.requires_daily_features ? "warn" : "ok")),
          el("td", null, (s.tags || []).slice(0, 4).map((tg) => makeBadge(String(tg)))),
        ]));
      }
      table.appendChild(thead);
      table.appendChild(tbody);
      clear(tblWrap).appendChild(table);
    }

    search.addEventListener("input", drawTable);
    mktSel.addEventListener("change", drawTable);
    drawTable();

    // Strategy comparator
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
      const cmpOut = el("pre", { text: state.compareResult ? JSON.stringify(state.compareResult, null, 2) : "" });
      btnCmp.addEventListener("click", async function () {
        try {
          const data = await fetchJson("/strategy-compare?names=" + encodeURIComponent(selA.value + "," + selB.value));
          state.compareResult = data;
          cmpOut.textContent = JSON.stringify(data, null, 2);
        } catch (err) {
          cmpOut.textContent = t("err_prefix") + err.message;
        }
      });
      cmpCard.appendChild(el("div", { class: "toolbar" }, [selA, selB, btnCmp]));
      cmpCard.appendChild(cmpOut);
      root.appendChild(cmpCard);
    }
  }

  function renderPatterns() {
    const root = clear(document.getElementById("panel-patterns"));
    const tblWrap = el("div", { class: "table-wrap" });
    const table = el("table");
    table.appendChild(el("thead", null, el("tr", null, [
      el("th", { text: "Pattern" }),
      el("th", { text: "Market" }),
      el("th", { text: "Family" }),
      el("th", { text: "Horizon" }),
      el("th", { text: "Status" }),
    ])));
    const tbody = el("tbody");
    for (const p of state.patterns) {
      const exp = Boolean(p.experimental);
      tbody.appendChild(el("tr", null, [
        el("td", null, [el("strong", { text: p.display_name || p.name }), el("div", { class: "kpi-sub", text: p.name })]),
        el("td", null, makeBadge(String(p.market || "cn").toUpperCase(), "accent")),
        el("td", { text: String(p.family || "-") }),
        el("td", { class: "mono", text: p.default_horizon ? "T+" + p.default_horizon : "T+5" }),
        el("td", null, makeBadge(exp ? "experimental" : "graduated", exp ? "warn" : "ok")),
      ]));
    }
    table.appendChild(tbody);
    tblWrap.appendChild(table);
    root.appendChild(tblWrap);
  }

  async function selectRun(runId) {
    if (!runId) return;
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
      if (state.activeRun && state.activeRun.run && state.activeRun.run.run_id === rid) opt.selected = true;
      sel.appendChild(opt);
    }
    sel.addEventListener("change", function () { selectRun(sel.value); });
    bar.appendChild(sel);
    root.appendChild(bar);

    if (!state.activeRun) {
      selectRun(String(state.runs[0].run_id || ""));
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
    table.appendChild(el("thead", null, el("tr", null, [
      el("th", { class: "mono", text: "#" }),
      el("th", { text: "Stock" }),
      el("th", { text: "Industry" }),
      el("th", { class: "mono", text: "Score" }),
      el("th", { text: "Topic Alignment" }),
      el("th", { text: "Risk" }),
    ])));
    const tbody = el("tbody");
    for (const p of picks) {
      const alignSt = p.topic_alignment_status || "unassessed";
      const alignTone = alignSt === "aligned" ? "ok" : alignSt === "unmatched" ? "warn" : "";
      const riskLvl = p.risk_level || "low";
      const riskTone = riskLvl === "high" ? "bad" : riskLvl === "medium" ? "warn" : "ok";
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

  function renderMcp() {
    const root = clear(document.getElementById("panel-mcp"));
    const mcpCard = el("div", { class: "card", style: "margin-bottom:14px;" }, [
      el("h3", { class: "section-title", text: t("mcp_title") }),
      el("pre", {
        text: JSON.stringify({
          mcpServers: {
            alphasift: {
              command: "alphasift",
              args: ["mcp"],
            },
          },
        }, null, 2),
      }),
    ]);
    root.appendChild(mcpCard);

    const epCard = el("div", { class: "card" }, [el("h3", { class: "section-title", text: t("api_title") })]);
    const eps = (state.index && state.index.endpoints) || [
      "/health", "/overview", "/strategies", "/patterns", "/runs",
      "/doctor/radar", "/doctor/data-sources", "/result-schema", "/daily-report.html",
    ];
    const box = el("div");
    for (const ep of eps) {
      box.appendChild(el("a", { class: "ep-link", href: ep, target: "_blank", rel: "noopener", text: ep }));
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
    renderMcp();
  }

  async function refreshAll() {
    const [idx, ov, strats, pats, runs, radar, src] = await Promise.all([
      fetchJson("/?format=json").catch(() => null),
      fetchJson("/overview").catch(() => null),
      fetchJson("/strategies").catch(() => ({ strategies: [] })),
      fetchJson("/patterns").catch(() => ({ patterns: [] })),
      fetchJson("/runs").catch(() => ({ runs: [] })),
      fetchJson("/doctor/radar").catch(() => null),
      fetchJson("/doctor/data-sources?live=0").catch(() => null),
    ]);
    state.index = idx;
    state.overview = ov;
    state.strategies = (strats && (strats.strategies || strats.items)) || [];
    state.patterns = (pats && (pats.patterns || pats.items)) || [];
    state.runs = (runs && (runs.runs || runs.items)) || [];
    state.radar = radar;
    state.sources = src;
    renderAll();
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
