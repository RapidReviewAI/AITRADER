# ChartPulse AI — Backend Error & Exception Log Standard

This log file (`error_log.txt`) maintains a persistent record of all backend execution errors, API failovers, and exception tracebacks encountered by `backend_bot.py`.

---

## 📌 Log Format Standard
Each error entry appended to `error_log.txt` follows this timestamped structure:

```text
[YYYY-MM-DD HH:MM:SS] <Error Category / Symbol / API Exception Details>
```

---

## 📜 Error Event Categories
* **API_FAILOVER_ERROR:** Gemini API rate-limiting, quota depletion, or model rotation events.
* **MARKET_DATA_ERROR:** Ticker retrieval timeouts or candlestick calculation exceptions.
* **VALUATION_ERROR:** Invalid ticker prices, extreme tick anomalies, or fallback assignments.
* **DATABASE_ERROR:** SQLite query execution failures or locking conflicts.

---

## 🚨 Guidelines for AI Agents
When investigating system stability issues:
1. Inspect `error_log.txt` to analyze the exact timestamps and exception messages.
2. Cross-reference logged timestamps with `portfolio_state.json` and engine console logs.
