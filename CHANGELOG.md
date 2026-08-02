# ChartPulse AI — System Changelog & Context Document

## 📌 Active Architecture & State
* **Frontend:** Streamlit (`dashboard.py`) hosting guest & multi-user dynamic state.
* **Backend:** `backend_bot.py` executing background scan passes, technical analysis, and position management.
* **Storage:** SQLite (`db.py` / `app_data.db`) and `portfolio_state.json`.

---

## 🚨 CRITICAL AI DEVELOPMENT RULES (STRICT GUARDRAILS)
1. **Scope Boundaries:** NEVER touch, rewrite, or refactor untouched functions, files, UI layouts, or authentication logic unless explicitly instructed.
2. **Token Quantity vs. USD Allocation:** When opening a position, token quantity MUST always be calculated as:
   `quantity = position_size_usd / current_price`
   NEVER store the raw USD allocation in the token quantity field.
3. **Valuation Fallbacks:** If `current_price` is missing or invalid during equity evaluation, fallback to `entry_price` (0% unrealized PnL) to prevent corrupted equity spikes.
4. **Closed Trades Reporting:** Every position closure must immediately emit a complete trade record (`symbol`, `entry_price`, `exit_price`, `quantity`, `pnl_usd`, `pnl_pct`, `exit_reason`, `timestamp`) into both `portfolio_state.json` AND the `trades` SQLite table.

---

## 📜 Recent Fixes & Modifications

### [v2.4.4] - Model Quota Optimization & Failover Text Parsing
* **Updated:** Changed default routine market scanning model to `gemini-2.0-flash` to prevent 429 quota exhaustion.
* **Fixed:** Enhanced API response text extraction to inspect `response.text` and fallback to `response.candidates[0].content.parts[0].text`.
* **Added:** Exponential backoff (`2s`, `4s`, `8s`, `16s`) on retry/failover attempts to allow API bucket recovery.

### [v2.4.3] - Unified Position Exit Pipeline & SQLite Trades Persistence
* **Added:** Created `trades` table schema and unified `execute_position_exit` function in `db.py` to consolidate all position exit paths.
* **Unified:** Routed manual UI sell button, stop-loss exits, take-profit exits, and AI momentum sell signals through `db.execute_position_exit`.
* **Updated:** Win Rate % and Profit Factor metrics calculation in `dashboard.py` to read directly from consolidated closed trade datasets.

### [v2.4.2] - AI Response Sanitization & Safe JSON Parsing
* **Fixed:** Resolved `JSONDecodeError` / `Unterminated string` exceptions by cleaning unescaped control characters (`\n`, `\r`, `\t`) and stripping markdown wrappers.
* **Added:** Fallback protection returning a default hold signal when AI response JSON parsing or auto-repair fails.
* **Updated:** System instructions prompting raw standard JSON arrays without markdown wrappers.

### [v2.4.1] - Portfolio Valuation & Trade Closure Fixes
* **Fixed:** Token quantity calculation in `backend_bot.py` to prevent USD allocations from corrupting position quantities and doubling total equity.
* **Fixed:** Fallback pricing logic for open positions when ticker prices return zero or null during background scans.
* **Fixed:** Trade closure logging pipeline to ensure sold positions properly report to the "Closed Trade History & Logs" tab in `dashboard.py`.
* **Added:** Automated Playwright headless site tester (`site_tester.py` / `run_monitor.py`) for background anomaly detection.

---

## 🧭 Instructions for New AI Chat Sessions
When starting a new session, read this `CHANGELOG.md` file first to understand system rules, core architecture, and historical bug patterns before making any code modifications.
