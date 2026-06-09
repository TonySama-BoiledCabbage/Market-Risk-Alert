# Market Risk Alert

This is a lightweight Telegram alert script for a portfolio focused on SPY/S&P 500, QQQ/Nasdaq, NVDA, and TSLA.

It combines:

- Professional macro, market, options, filing, and company signals
- Equity confirmation signals such as QQQ vs SPY, NVDA vs SOXX, TSLA vs QQQ
- Macro confirmation signals such as US 10Y yield change and VIX change
- Optional alternative event signals such as Polymarket, treated as secondary context
- Optional Alpha Vantage quote data for SPY, QQQ, NVDA, TSLA, and SOXX

## 1. Create Telegram Bot

1. Open Telegram and chat with `@BotFather`.
2. Run `/newbot`, follow the prompts, and copy the bot token.
3. Send any message to your new bot.
4. Open this URL in a browser, replacing the token:

```text
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
```

5. Find `chat.id` in the JSON response.

## 1.5 Minimal Local Client

Launch the local browser client:

```powershell
.\launch_client.ps1
```

Or double-click:

```text
launch_client.bat
```

The client lets you choose watched symbols, set the evening and morning report times, trigger reports manually, and install Windows scheduled tasks. It saves local preferences to `config\client_settings.json` and updates `WATCH_SYMBOLS` / `QUOTE_SYMBOLS` in `.env` without changing your Telegram token.

## 2. Configure

Copy `.env.example` to `.env` and fill in:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ALERT_MIN_SCORE=40
ALPHAVANTAGE_API_KEY=optional
QUOTE_SYMBOLS=SPY,QQQ,NVDA,TSLA,SOXX
```

## 3. Input Format

Your data scraper should output a JSON snapshot like:

```json
{
  "signals": [
    {
      "id": "cme_fedwatch_higher_for_longer",
      "title": "CME FedWatch 隐含降息预期显著回撤",
      "source": "CME FedWatch / Fed Funds futures",
      "source_tier": "exchange",
      "category": "macro",
      "unit": "probability_pct",
      "value": 70,
      "previous_value": 50,
      "risk_direction": "higher_is_risk",
      "impact": ["SPY", "QQQ", "NVDA", "TSLA"]
    }
  ],
  "market": {
    "SPY": { "change_pct": -0.4 },
    "QQQ": { "change_pct": -1.5 },
    "NVDA": { "change_pct": -2.2 },
    "TSLA": { "change_pct": -3.4 },
    "SOXX": { "change_pct": -1.0 },
    "US10Y": { "change_bps": 9 },
    "VIX": { "change_pct": 10.5 }
  }
}
```

`previous_value` is optional. If omitted, the script compares against `state/last_snapshot.json` from the previous run.

Recommended source tiers:

- `official`: FRED, BLS, BEA, Treasury, SEC
- `exchange`: CME FedWatch, exchange-implied rates, exchange market data
- `market`: equity/ETF/index price data
- `options`: OPRA, Cboe, option IV/skew/put-call data
- `company`: filings, earnings models, IR data
- `professional`: Bloomberg, FactSet, LSEG, S&P Capital IQ exports
- `alternative`: prediction markets such as Polymarket

Polymarket can still be included under `polymarket`, but the script treats it as `alternative` context and caps its standalone influence.

## 4. Test Locally

From this folder:

```powershell
& "C:\Users\LuYuntao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\market_alert.py --input .\examples\sample_signals.json --dry-run --force
```

## 5. Send Telegram Alert

```powershell
& "C:\Users\LuYuntao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\market_alert.py --input .\examples\sample_signals.json
```

To automatically fill equity price changes from Alpha Vantage:

```powershell
& "C:\Users\LuYuntao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\market_alert.py --input .\examples\sample_signals.json --fetch-alpha-vantage
```

Keep feeding `US10Y.change_bps` and `VIX.change_pct` from your preferred macro/market source. The script will merge them with fetched stock/ETF changes.

## 6. Suggested Scheduling

Use Windows Task Scheduler to run every 5-15 minutes during US market hours.

Recommended cadence:

- Premarket: every 15 minutes
- Regular session: every 5 minutes
- After-hours: every 15-30 minutes

For major-change monitoring, a quieter default is every 15 minutes during regular market hours.

First, have your Polymarket/market data scraper write the latest snapshot to:

```text
data\latest_signals.json
```

Install the scheduled task:

```powershell
.\scripts\install_windows_task.ps1
```

This creates a weekday task that runs every 15 minutes from `09:20` for 8 hours. The task writes run logs to `logs\`.

To use a custom input file:

```powershell
.\scripts\install_windows_task.ps1 -InputPath "C:\path\to\latest_signals.json"
```

To smoke-test the scheduled runner without sending Telegram:

```powershell
.\scripts\run_market_alert.ps1 -InputPath ".\examples\sample_signals.json" -DryRun
```

Install threshold-free scheduled reports:

```powershell
.\scripts\install_daily_reports_task.ps1
```

This creates:

- `22:00` daily recap: sends that day's events and stock changes.
- `09:45` weekday market-open advice: sends the day's suggested posture 15 minutes after the US open.

Both scheduled reports ignore `ALERT_MIN_SCORE`; they always send as long as `data\latest_signals.json` exists and Telegram is configured.

Every run is archived under:

```text
archive\YYYY\MM\YYYY-MM-DD\
```

Each archive set includes:

- `*-snapshot.json`: raw input snapshot used for that run
- `*-scores.json`: scored signals and reasons
- `*-telegram.txt`: exact Telegram message/report text

To test either report without sending Telegram:

```powershell
.\scripts\run_market_alert.ps1 -InputPath ".\examples\sample_signals.json" -ReportMode evening -DryRun
.\scripts\run_market_alert.ps1 -InputPath ".\examples\sample_signals.json" -ReportMode morning -DryRun
```

To remove these report tasks:

```powershell
.\scripts\uninstall_daily_reports_task.ps1
```

To remove the scheduled task:

```powershell
.\scripts\uninstall_windows_task.ps1
```

## 7. Scoring Logic

Default alert threshold is `40`.

- `0-39`: log only
- `40-59`: Telegram observation alert
- `60-79`: strong alert
- `80-100`: high-risk alert; consider later adding SMS/Pushover fallback

Professional sources receive higher scoring weight than alternative event probabilities. A prediction-market move alone should not drive a portfolio conclusion unless confirmed by price, rates, volatility, options, filings, or company data.
