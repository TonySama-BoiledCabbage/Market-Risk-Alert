const state = {
  settings: {
    input_path: "",
    symbols: ["NVDA", "TSLA", "SPY", "QQQ"],
    custom_symbols: "",
    evening_time: "22:00",
    morning_time: "09:45",
    alert_start_time: "09:20",
    alert_interval_minutes: 15,
    alert_duration_hours: 8,
    fetch_alpha_vantage: false,
  },
  equity: [],
  macro: [],
  dashboardCards: [],
  language: localStorage.getItem("mra.language") || "en",
  theme: localStorage.getItem("mra.theme") || "night",
  lastRun: localStorage.getItem("mra.lastRun") || "-",
};

const $ = (id) => document.getElementById(id);

const copy = {
  en: {
    tagline: "A quiet local watch system.",
    dashboard: "Dashboard",
    watchlist: "Watchlist",
    schedule: "Schedule",
    actions: "Actions",
    status: "Status",
    customTickers: "Custom tickers",
    comma: "Comma separated.",
    eveningRecap: "Evening recap",
    morningAdvice: "Morning advice",
    activateSummary: "Activate now (summary)",
    installSchedule: "Install schedule",
    telegram: "Telegram",
    dataFile: "Data file",
    lastRun: "Last run",
    configured: "Configured",
    missing: "Missing",
    found: "Found",
    notFound: "Not found",
    save: "Save",
    saved: "Saved",
    sent: "Sent",
    installed: "Installed",
    english: "English",
    chinese: "中文",
    dayMode: "Day mode",
    nightMode: "Night mode",
    sentAt2200: "Sent at 22:00",
    price: "Price",
    day: "Day",
    oi: "OI",
    oiChange: "OI change",
    calm: "Calm",
    oiWatch: "OI watch",
    oiAlert: "OI alert",
  },
  zh: {
    tagline: "安静的本地金融观察工具。",
    dashboard: "仪表盘",
    watchlist: "关注标的",
    schedule: "时间安排",
    actions: "操作",
    status: "状态",
    customTickers: "自定义代码",
    comma: "逗号分隔。",
    eveningRecap: "晚间复盘",
    morningAdvice: "开盘建议",
    activateSummary: "立即总结汇报",
    installSchedule: "安装定时任务",
    telegram: "Telegram",
    dataFile: "数据文件",
    lastRun: "最近运行",
    configured: "已配置",
    missing: "未配置",
    found: "已找到",
    notFound: "未找到",
    save: "保存",
    saved: "已保存",
    sent: "已发送",
    installed: "已安装",
    english: "English",
    chinese: "中文",
    dayMode: "日间模式",
    nightMode: "夜间模式",
    sentAt2200: "22:00 已发送",
    price: "价格",
    day: "日内",
    oi: "OI",
    oiChange: "OI变化",
    calm: "平稳",
    oiWatch: "OI观察",
    oiAlert: "OI提醒",
  },
};

function t(key) {
  return copy[state.language][key] || copy.en[key] || key;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.stderr || payload.error || "Request failed");
  return payload;
}

function setStatus(text) {
  $("lastRun").textContent = text;
  state.lastRun = text;
  localStorage.setItem("mra.lastRun", text);
}

function collectSettings() {
  const checked = [...document.querySelectorAll("[data-symbol]:checked")].map((item) => item.dataset.symbol);
  return {
    ...state.settings,
    symbols: checked,
    custom_symbols: $("customSymbols").value.trim(),
    evening_time: $("eveningTime").value.trim(),
    morning_time: $("morningTime").value.trim(),
    fetch_alpha_vantage: false,
  };
}

function renderSymbols() {
  const grid = $("symbolGrid");
  grid.innerHTML = "";
  const selected = new Set(state.settings.symbols || []);
  ["NVDA", "TSLA", "SPY", "QQQ"].forEach((symbol) => {
    const label = document.createElement("label");
    label.className = "symbol";
    label.innerHTML = `<input type="checkbox" data-symbol="${symbol}" ${selected.has(symbol) ? "checked" : ""} /><span>${symbol}</span>`;
    grid.appendChild(label);
  });
}

function formatNumber(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  if (Math.abs(number) >= 1000 && suffix === "") return Math.round(number).toLocaleString();
  return `${number.toFixed(suffix ? 1 : 2)}${suffix}`;
}

function oiNote(card) {
  if (card.alert) return t("oiAlert");
  if (card.watch) return t("oiWatch");
  return t("calm");
}

function renderCards() {
  const grid = $("cardGrid");
  grid.innerHTML = "";
  const cards = state.dashboardCards.length
    ? state.dashboardCards
    : (state.settings.symbols || ["NVDA", "TSLA", "SPY", "QQQ"]).map((symbol) => ({ symbol }));

  cards.forEach((card) => {
    const node = document.createElement("article");
    node.className = `ticker-card ${card.alert ? "is-alert" : card.watch ? "is-watch" : ""}`;
    node.innerHTML = `
      <div class="ticker-head">
        <div class="ticker-symbol">${card.symbol}</div>
        <div class="ticker-note">${oiNote(card)}</div>
      </div>
      <div class="metric-row"><span>${t("price")}</span><strong>${formatNumber(card.price)}</strong></div>
      <div class="metric-row"><span>${t("day")}</span><strong>${formatNumber(card.change_pct, "%")}</strong></div>
      <div class="metric-row"><span>${t("oi")}</span><strong>${formatNumber(card.open_interest)}</strong></div>
      <div class="metric-row"><span>${t("oiChange")}</span><strong>${formatNumber(card.oi_change_pct, "%")}</strong></div>
    `;
    grid.appendChild(node);
  });
}

function renderText() {
  document.documentElement.lang = state.language === "zh" ? "zh-Hans" : "en";
  document.documentElement.dataset.theme = state.theme === "day" ? "day" : "night";
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  $("languageLabel").textContent = state.language === "zh" ? t("chinese") : t("english");
  $("themeLabel").textContent = state.theme === "day" ? t("nightMode") : t("dayMode");
}

function render() {
  const s = state.settings;
  $("customSymbols").value = s.custom_symbols || "";
  $("eveningTime").value = s.evening_time || "22:00";
  $("morningTime").value = s.morning_time || "09:45";
  $("telegramStatus").textContent = state.telegramConfigured ? t("configured") : t("missing");
  $("dataStatus").textContent = state.sampleExists ? t("found") : t("notFound");
  $("lastRun").textContent = state.lastRun;
  renderSymbols();
  renderText();
  renderCards();
}

async function load() {
  try {
    const payload = await api("/api/settings");
    state.settings = payload.settings;
    state.equity = payload.equity_symbols;
    state.macro = payload.macro_symbols;
    state.telegramConfigured = payload.telegram_configured;
    state.sampleExists = payload.sample_exists;
    state.dashboardCards = payload.dashboard_cards || [];
    if (payload.last_run) state.lastRun = payload.last_run;
  } catch (error) {
    state.telegramConfigured = false;
    state.sampleExists = false;
    state.dashboardCards = [];
    state.lastRun = location.protocol === "file:" ? "Open localhost client" : error.message;
  }
  render();
}

async function save() {
  const payload = await api("/api/settings", {
    method: "POST",
    body: JSON.stringify(collectSettings()),
  });
  state.settings = payload.settings;
  setStatus(t("saved"));
  render();
}

async function run(mode, statusText) {
  setStatus("...");
  const payload = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({ mode, settings: collectSettings() }),
  });
  setStatus(payload.ok ? statusText : "Error");
}

async function installSchedule() {
  setStatus("...");
  const payload = await api("/api/install-reports", {
    method: "POST",
    body: JSON.stringify({ settings: collectSettings() }),
  });
  setStatus(payload.ok ? t("installed") : "Error");
}

function bind(id, fn) {
  $(id).addEventListener("click", async () => {
    try {
      await fn();
    } catch (error) {
      setStatus(error.message);
    }
  });
}

function setActive(sectionId) {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.section === sectionId);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active-section", panel.id === sectionId);
  });
}

function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => setActive(item.dataset.section));
  });

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) setActive(visible.target.id);
    },
    { rootMargin: "-20% 0px -55% 0px", threshold: [0.1, 0.3, 0.6] }
  );
  document.querySelectorAll(".panel").forEach((panel) => observer.observe(panel));
}

bind("saveBtn", save);
bind("eveningBtn", () => run("evening", t("sentAt2200")));
bind("morningBtn", () => run("morning", t("sent")));
bind("summaryBtn", () => run("evening", t("sent")));
bind("reportsBtn", installSchedule);

$("languageBtn").addEventListener("click", () => {
  state.language = state.language === "en" ? "zh" : "en";
  localStorage.setItem("mra.language", state.language);
  render();
});

$("themeBtn").addEventListener("click", () => {
  state.theme = state.theme === "night" ? "day" : "night";
  localStorage.setItem("mra.theme", state.theme);
  render();
});

setupNavigation();
load();
