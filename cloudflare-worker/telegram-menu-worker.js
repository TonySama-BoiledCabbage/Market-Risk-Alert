const DEFAULT_WATCH_SYMBOLS = "SPY, QQQ, NVDA, TSLA, SOXX";

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

    await sendMessage(env, chatId, "发送 /start 打开 Market Risk Alert 菜单。");
    return;
  }

  if (update.callback_query) {
    const query = update.callback_query;
    const chatId = String(query.message.chat.id);
    if (!isAllowedChat(chatId, env)) return;

    await answerCallback(env, query.id);
    await handleCallback(query, env, chatId);
  }
}

async function handleCallback(query, env, chatId) {
  const data = query.data || "main";
  const messageId = query.message.message_id;

  if (data === "main") {
    await editMessage(env, chatId, messageId, mainMenuText(env), mainMenuKeyboard());
    return;
  }

  if (data === "dashboard") {
    await editMessage(env, chatId, messageId, dashboardText(env), dashboardKeyboard());
    return;
  }

  if (data === "watchlist") {
    await editMessage(env, chatId, messageId, watchlistText(env), backKeyboard());
    return;
  }

  if (data === "schedule") {
    await editMessage(env, chatId, messageId, scheduleText(env), backKeyboard());
    return;
  }

  if (data === "status") {
    await editMessage(env, chatId, messageId, statusText(env), backKeyboard());
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
      backKeyboard(),
    );
  }
}

function mainMenuText(env) {
  return [
    "Market Risk Alert",
    "",
    "个人云端菜单已连接。",
    `关注标的：${watchSymbols(env)}`,
  ].join("\n");
}

function dashboardText(env) {
  return [
    "Dashboard",
    "",
    "当前为极简个人版：",
    "- Telegram 菜单负责触发",
    "- GitHub Actions 负责生成报告",
    "- Secrets 保存在你自己的 GitHub / Cloudflare",
    "",
    `关注标的：${watchSymbols(env)}`,
  ].join("\n");
}

function watchlistText(env) {
  return [
    "关注标的",
    "",
    watchSymbols(env),
    "",
    "第一版先只读显示。后续如果你确认这个菜单体验顺手，再加按钮修改股票。"
  ].join("\n");
}

function scheduleText(env) {
  return [
    "汇报时间",
    "",
    `晚间复盘：${env.EVENING_TIME || "22:00"}`,
    `开盘建议：${env.MORNING_TIME || "09:45"}`,
    "",
    "第一版仍由 GitHub Actions 定时运行。按钮修改时间会放到下一版。"
  ].join("\n");
}

function statusText(env) {
  return [
    "系统状态",
    "",
    "Telegram webhook：已连接",
    "GitHub Actions：可由按钮触发",
    `Workflow：${env.GITHUB_WORKFLOW || "telegram-reports.yml"}`,
    `Branch：${env.GITHUB_REF || "main"}`,
  ].join("\n");
}

function watchSymbols(env) {
  return (env.WATCH_SYMBOLS || DEFAULT_WATCH_SYMBOLS).trim();
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
      [{ text: "立即触发", callback_data: "trigger" }],
      [{ text: "返回", callback_data: "main" }],
    ],
  };
}

function backKeyboard() {
  return {
    inline_keyboard: [[{ text: "返回", callback_data: "main" }]],
  };
}

async function triggerGithubReport(env, reportMode) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const workflow = env.GITHUB_WORKFLOW || "telegram-reports.yml";
  const ref = env.GITHUB_REF || "main";
  const token = env.GITHUB_PAT;

  if (!owner || !repo || !token) {
    throw new Error("Missing GitHub Worker settings.");
  }

  const response = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "market-risk-alert-telegram-worker",
        "X-GitHub-Api-Version": "2026-03-10",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          report_mode: reportMode,
          input_file: "examples/cloud_seed_signals.json",
          send_to_telegram: "true",
        },
      }),
    },
  );

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`GitHub dispatch failed: ${response.status} ${text}`);
  }
}

async function sendMainMenu(env, chatId) {
  await sendMessage(env, chatId, mainMenuText(env), mainMenuKeyboard());
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
