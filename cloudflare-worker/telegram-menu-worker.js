const DEFAULT_WATCH_SYMBOLS = ["SPY", "QQQ", "NVDA", "TSLA", "SOXX"];
const COMMON_SYMBOLS = [
  "SPY",
  "QQQ",
  "NVDA",
  "TSLA",
  "SOXX",
  "XLK",
  "XLY",
  "AAPL",
  "MSFT",
  "GOOGL",
  "AMZN",
  "META",
  "AMD",
  "AVGO",
];

export default {
  async fetch(request, env) {
    if (request.method === "GET") {
      return json({ ok: true, service: "Market Risk Alert Telegram Menu" });
    }

    if (request.method !== "POST") {
      return json({ ok: false, error: "Method not allowed" }, 405);
    }

    if (env.TELEGRAM_WEBHOOK_SECRET) {
      const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
      if (secret !== env.TELEGRAM_WEBHOOK_SECRET) {
        return json({ ok: false, error: "Unauthorized webhook" }, 401);
      }
    }

    const update = await request.json();
    await handleUpdate(update, env);
    return json({ ok: true });
  },
};

async function handleUpdate(update, env) {
  if (update.message) {
    const chatId = String(update.message.chat.id);
    if (!isAllowedChat(chatId, env)) return;

    const text = (update.message.text || "").trim();
    if (text === "/start" || text === "/menu") {
      await sendMainMenu(env, chatId);
      return;
    }

    if (text === "/watchlist") {
      await sendMessage(env, chatId, await watchlistText(env), watchlistKeyboard(await getWatchSymbols(env)));
      return;
    }

    if (text.startsWith("/add ")) {
      const symbol = normalizeSymbol(text.slice(5));
      if (!symbol) {
        await sendMessage(env, chatId, "格式不对。示例：/add AMD");
        return;
      }
      const symbols = await addWatchSymbol(env, symbol);
      await sendMessage(env, chatId, `已添加 ${symbol}\n\n当前关注：${symbols.join(", ")}`, watchlistKeyboard(symbols));
      return;
    }

    if (text.startsWith("/remove ")) {
      const symbol = normalizeSymbol(text.slice(8));
      if (!symbol) {
        await sendMessage(env, chatId, "格式不对。示例：/remove TSLA");
        return;
      }
      const symbols = await removeWatchSymbol(env, symbol);
      await sendMessage(env, chatId, `已移除 ${symbol}\n\n当前关注：${symbols.join(", ")}`, watchlistKeyboard(symbols));
      return;
    }

    await sendMessage(env, chatId, [
      "发送 /start 打开菜单。",
      "",
      "自由增减标的：",
      "/add AMD",
      "/remove TSLA",
      "/watchlist",
    ].join("\n"));
    return;
  }

  if (update.callback_query) {
    const query = update.callback_query;
    const chatId = String(query.message.chat.id);
    if (!isAllowedChat(chatId, env)) return;

    await answerCallback(env, query.id);
    try {
      await handleCallback(query, env, chatId);
    } catch (error) {
      await sendMessage(env, chatId, [
        "操作失败。",
        "",
        String(error && error.message ? error.message : error),
        "",
        "如果这是第一次使用自助选股，请确认 GITHUB_PAT 具备 repository variables 的读写权限。",
      ].join("\n"));
    }
  }
}

async function handleCallback(query, env, chatId) {
  const data = query.data || "main";
  const messageId = query.message.message_id;

  if (data === "main") {
    await editMessage(env, chatId, messageId, await mainMenuText(env), mainMenuKeyboard());
    return;
  }

  if (data === "dashboard") {
    await editMessage(env, chatId, messageId, await dashboardText(env), dashboardKeyboard());
    return;
  }

  if (data === "watchlist") {
    const symbols = await getWatchSymbols(env);
    await editMessage(env, chatId, messageId, watchlistTextFromSymbols(symbols), watchlistKeyboard(symbols));
    return;
  }

  if (data.startsWith("watch:toggle:")) {
    const symbol = normalizeSymbol(data.split(":")[2]);
    const symbols = await toggleWatchSymbol(env, symbol);
    await editMessage(env, chatId, messageId, watchlistTextFromSymbols(symbols), watchlistKeyboard(symbols));
    return;
  }

  if (data === "watch:reset") {
    const symbols = await setWatchSymbols(env, DEFAULT_WATCH_SYMBOLS);
    await editMessage(env, chatId, messageId, watchlistTextFromSymbols(symbols), watchlistKeyboard(symbols));
    return;
  }

  if (data === "watch:custom") {
    await editMessage(env, chatId, messageId, [
      "自定义标的",
      "",
      "直接发送命令即可：",
      "/add AMD",
      "/remove TSLA",
      "",
      "支持美股常见代码，例如 AAPL、MSFT、AVGO。"
    ].join("\n"), backKeyboard("watchlist"));
    return;
  }

  if (data === "schedule") {
    await editMessage(env, chatId, messageId, scheduleText(env), backKeyboard("main"));
    return;
  }

  if (data === "status") {
    await editMessage(env, chatId, messageId, await statusText(env), backKeyboard("main"));
    return;
  }

  if (data === "trigger") {
    await editMessage(env, chatId, messageId, "选择要立即触发的报告：", triggerKeyboard());
    return;
  }

  if (data === "trigger:alert" || data === "trigger:evening" || data === "trigger:morning") {
    const reportMode = data.split(":")[1];
    await triggerGithubReport(env, reportMode);
    const reportName = {
      alert: "异动检测",
      evening: "晚间复盘",
      morning: "开盘建议",
    }[reportMode];
    await editMessage(
      env,
      chatId,
      messageId,
      `已请求 GitHub Actions 生成 ${reportName}。\n\n如果达到提醒阈值，通常 10-30 秒后 Telegram 会收到报告。`,
      backKeyboard("main"),
    );
  }
}

async function mainMenuText(env) {
  const symbols = await getWatchSymbols(env);
  return [
    "Market Risk Alert",
    "",
    "个人云端菜单已连接。",
    `关注标的：${symbols.join(", ")}`,
  ].join("\n");
}

async function dashboardText(env) {
  const symbols = await getWatchSymbols(env);
  return [
    "Dashboard",
    "",
    "- Telegram 菜单负责触发和修改关注标的",
    "- GitHub Actions 负责生成报告和异动监控",
    "- 关注标的保存在 GitHub repository variables",
    "",
    `关注标的：${symbols.join(", ")}`,
  ].join("\n");
}

async function watchlistText(env) {
  return watchlistTextFromSymbols(await getWatchSymbols(env));
}

function watchlistTextFromSymbols(symbols) {
  return [
    "关注标的",
    "",
    symbols.join(", "),
    "",
    "点按钮可增减常用标的。",
    "自由添加：/add AMD",
    "自由移除：/remove TSLA",
  ].join("\n");
}

function scheduleText(env) {
  return [
    "汇报时间",
    "",
    `晚间复盘：${env.EVENING_TIME || "22:00"}`,
    `开盘建议：${env.MORNING_TIME || "09:45"}`,
    "",
    "当前版本先支持自助选股；时间修改后续再加。",
  ].join("\n");
}

async function statusText(env) {
  const symbols = await getWatchSymbols(env);
  return [
    "系统状态",
    "",
    "Telegram webhook：已连接",
    "GitHub Actions：可由按钮触发",
    `Workflow：${env.GITHUB_WORKFLOW || "telegram-reports.yml"}`,
    `Branch：${env.GITHUB_REF || "main"}`,
    `关注标的：${symbols.join(", ")}`,
  ].join("\n");
}

async function getWatchSymbols(env) {
  try {
    const value = await getGithubVariable(env, "WATCH_SYMBOLS");
    return parseSymbols(value || env.WATCH_SYMBOLS || DEFAULT_WATCH_SYMBOLS.join(","));
  } catch {
    return parseSymbols(env.WATCH_SYMBOLS || DEFAULT_WATCH_SYMBOLS.join(","));
  }
}

async function addWatchSymbol(env, symbol) {
  const symbols = await getWatchSymbols(env);
  if (!symbols.includes(symbol)) symbols.push(symbol);
  return setWatchSymbols(env, symbols);
}

async function removeWatchSymbol(env, symbol) {
  const symbols = (await getWatchSymbols(env)).filter((item) => item !== symbol);
  return setWatchSymbols(env, symbols.length ? symbols : DEFAULT_WATCH_SYMBOLS);
}

async function toggleWatchSymbol(env, symbol) {
  if (!symbol) return getWatchSymbols(env);
  const symbols = await getWatchSymbols(env);
  const next = symbols.includes(symbol)
    ? symbols.filter((item) => item !== symbol)
    : [...symbols, symbol];
  return setWatchSymbols(env, next.length ? next : DEFAULT_WATCH_SYMBOLS);
}

async function setWatchSymbols(env, symbols) {
  const normalized = Array.from(new Set(symbols.map(normalizeSymbol).filter(Boolean)));
  const watchSymbols = normalized.length ? normalized : DEFAULT_WATCH_SYMBOLS;
  const quoteSymbols = watchSymbols.filter(isQuoteSymbol);
  await upsertGithubVariable(env, "WATCH_SYMBOLS", watchSymbols.join(","));
  await upsertGithubVariable(env, "QUOTE_SYMBOLS", (quoteSymbols.length ? quoteSymbols : DEFAULT_WATCH_SYMBOLS).join(","));
  return watchSymbols;
}

function parseSymbols(value) {
  if (Array.isArray(value)) return value.map(normalizeSymbol).filter(Boolean);
  return String(value || "")
    .split(",")
    .map(normalizeSymbol)
    .filter(Boolean);
}

function normalizeSymbol(value) {
  const symbol = String(value || "").trim().toUpperCase();
  if (!/^[A-Z0-9.^-]{1,15}$/.test(symbol)) return "";
  return symbol;
}

function isQuoteSymbol(symbol) {
  return !["US10Y", "US2Y", "VIX"].includes(symbol);
}

function mainMenuKeyboard() {
  return {
    inline_keyboard: [
      [
        { text: "Dashboard", callback_data: "dashboard" },
        { text: "立即触发", callback_data: "trigger" },
      ],
      [
        { text: "关注标的", callback_data: "watchlist" },
        { text: "汇报时间", callback_data: "schedule" },
      ],
      [{ text: "状态", callback_data: "status" }],
    ],
  };
}

function watchlistKeyboard(symbols) {
  const active = new Set(symbols);
  const rows = [];
  for (let index = 0; index < COMMON_SYMBOLS.length; index += 2) {
    rows.push(
      COMMON_SYMBOLS.slice(index, index + 2).map((symbol) => ({
        text: `${symbol}${active.has(symbol) ? " ✓" : ""}`,
        callback_data: `watch:toggle:${symbol}`,
      })),
    );
  }
  rows.push([{ text: "+ 自定义代码", callback_data: "watch:custom" }]);
  rows.push([{ text: "恢复默认", callback_data: "watch:reset" }]);
  rows.push([{ text: "返回", callback_data: "main" }]);
  return { inline_keyboard: rows };
}

function triggerKeyboard() {
  return {
    inline_keyboard: [
      [{ text: "异动检测", callback_data: "trigger:alert" }],
      [{ text: "晚间复盘", callback_data: "trigger:evening" }],
      [{ text: "开盘建议", callback_data: "trigger:morning" }],
      [{ text: "返回", callback_data: "main" }],
    ],
  };
}

function dashboardKeyboard() {
  return {
    inline_keyboard: [
      [{ text: "关注标的", callback_data: "watchlist" }],
      [{ text: "立即触发", callback_data: "trigger" }],
      [{ text: "返回", callback_data: "main" }],
    ],
  };
}

function backKeyboard(target = "main") {
  return {
    inline_keyboard: [[{ text: "返回", callback_data: target }]],
  };
}

async function triggerGithubReport(env, reportMode) {
  await githubRequest(env, `/actions/workflows/${env.GITHUB_WORKFLOW || "telegram-reports.yml"}/dispatches`, {
    method: "POST",
    body: {
      ref: env.GITHUB_REF || "main",
      inputs: {
        report_mode: reportMode,
        input_file: "examples/cloud_seed_signals.json",
        send_to_telegram: "true",
      },
    },
  });
}

async function getGithubVariable(env, name) {
  try {
    const data = await githubRequest(env, `/actions/variables/${name}`, { method: "GET" });
    return data.value;
  } catch (error) {
    if (String(error.message || "").includes("404")) return "";
    throw error;
  }
}

async function upsertGithubVariable(env, name, value) {
  try {
    await githubRequest(env, `/actions/variables/${name}`, {
      method: "PATCH",
      body: { name, value },
    });
  } catch (error) {
    if (!String(error.message || "").includes("404")) throw error;
    await githubRequest(env, "/actions/variables", {
      method: "POST",
      body: { name, value },
    });
  }
}

async function githubRequest(env, path, options = {}) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const token = env.GITHUB_PAT;
  if (!owner || !repo || !token) {
    throw new Error("Missing GitHub Worker settings.");
  }

  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}${path}`, {
    method: options.method || "GET",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "User-Agent": "market-risk-alert-telegram-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`GitHub API failed: ${response.status} ${text}`);
  }

  if (response.status === 204) return {};
  return response.json();
}

async function sendMainMenu(env, chatId) {
  await sendMessage(env, chatId, await mainMenuText(env), mainMenuKeyboard());
}

async function sendMessage(env, chatId, text, replyMarkup) {
  return telegram(env, "sendMessage", {
    chat_id: chatId,
    text,
    reply_markup: replyMarkup,
    disable_web_page_preview: true,
  });
}

async function editMessage(env, chatId, messageId, text, replyMarkup) {
  return telegram(env, "editMessageText", {
    chat_id: chatId,
    message_id: messageId,
    text,
    reply_markup: replyMarkup,
    disable_web_page_preview: true,
  });
}

async function answerCallback(env, callbackQueryId) {
  return telegram(env, "answerCallbackQuery", {
    callback_query_id: callbackQueryId,
  });
}

async function telegram(env, method, payload) {
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Telegram ${method} failed: ${response.status} ${text}`);
  }

  return response.json();
}

function isAllowedChat(chatId, env) {
  return String(env.TELEGRAM_CHAT_ID) === String(chatId);
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
