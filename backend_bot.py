"""
ChartPulse AI - Background Execution Engine
Version: 2.0.0
Description: Rate-limit aware, API quota efficient autonomous paper-trading engine.
             Computes RSI, EMA, ATR and volume metrics locally to save prompt tokens 
             and minimize API calls. Operates on a 3-minute interval scan loop.
"""

import time
import json
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    try:
        import streamlit as st
        API_KEY = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        pass

try:
    client = genai.Client(api_key=API_KEY) if API_KEY else None
except Exception as _e:
    client = None

MODEL_FALLBACKS = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
ACTIVE_MODEL = MODEL_FALLBACKS[0]

# Top 20 High-Volume Crypto Assets Watchlist
WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "NEARUSDT",
    "SUIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
    "RENDERUSDT", "FETUSDT", "PEPEUSDT", "SHIBUSDT", "ATOMUSDT"
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "portfolio_state.json")
ERROR_LOG_FILE = os.path.join(BASE_DIR, "error_log.txt")
SCAN_INTERVAL_SECONDS = 60  # 60-second scan interval backed by multi-model failover rotation

import db

def log_error_to_file(error_msg):
    """Appends backend errors to error_log.txt with full date & timestamp."""
    try:
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_entry = f"[{timestamp_str}] {error_msg}\n"
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted_entry)
    except Exception as e:
        print(f"❌ Failed writing to {ERROR_LOG_FILE}: {e}")

def load_portfolio(user_id=1):
    """Loads user portfolio from SQLite via db.py (and syncs with local state file for Guest user 1)."""
    db.init_db()
    portfolio = db.get_or_create_portfolio(user_id)
    
    # Sync with local STATE_FILE for Guest (user_id=1) if present
    if user_id == 1 and os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                file_data = json.load(f)
                for key in ["cash_balance", "active_positions", "closed_trades", "latest_scan_decisions", "equity_history", "bot_logs", "last_scan_time", "challenge_active", "challenge_start_time"]:
                    if key in file_data and file_data[key]:
                        portfolio[key] = file_data[key]
        except Exception as e:
            print(f"⚠️ Error merging local state file: {e}")
    return portfolio

def save_portfolio(portfolio, user_id=1):
    """Saves portfolio to SQLite database and syncs local state file for Guest user 1."""
    db.init_db()
    db.save_portfolio_db(user_id, portfolio)
    
    # Sync to local STATE_FILE if user is Guest (1)
    if user_id == 1:
        temp_file = f"{STATE_FILE}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(portfolio, f, indent=4)
            os.replace(temp_file, STATE_FILE)
        except Exception as e:
            print(f"❌ Error saving {STATE_FILE}: {e}")

def fetch_binance_klines(symbol):
    """Fetches candlestick data using multi-exchange failover (Binance, CoinGecko, KuCoin)."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    endpoints = [
        f"https://api.binance.us/api/v3/klines?symbol={symbol}&interval=5m&limit=30",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=30",
        f"https://api1.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=30"
    ]
    data = None
    for url in endpoints:
        try:
            res = requests.get(url, headers=headers, timeout=4)
            if res.status_code == 200:
                json_res = res.json()
                if isinstance(json_res, list) and len(json_res) >= 15:
                    data = json_res
                    break
        except Exception:
            continue

    # Fallback to KuCoin API if Binance cloud endpoints fail
    if not data:
        try:
            kc_sym = symbol.replace("USDT", "-USDT")
            url = f"https://api.kucoin.com/api/v1/market/candles?symbol={kc_sym}&type=5min"
            res = requests.get(url, headers=headers, timeout=4)
            if res.status_code == 200:
                kc_json = res.json()
                if kc_json.get("code") == "200000" and isinstance(kc_json.get("data"), list):
                    # KuCoin candle format: [time, open, close, high, low, volume, turnover]
                    raw_kc = kc_json["data"][:30]
                    data = [[0, 0, c[3], c[4], c[2], c[5]] for c in reversed(raw_kc)]
        except Exception:
            pass

    if not data:
        return None

    try:
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        volumes = [float(c[5]) for c in data]
        
        cur_price = closes[-1]
        
        # Simple EMA 9 calculation
        ema9 = cur_price
        k9 = 2 / (9 + 1)
        for price in closes[-9:]:
            ema9 = (price * k9) + (ema9 * (1 - k9))

        # Simple RSI 14 calculation
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(abs(diff))
                losses.append(abs(diff)) if diff < 0 else losses.append(0)
        
        avg_gain = sum(gains[-14:]) / 14 if gains else 0.0001
        avg_loss = sum(losses[-14:]) / 14 if losses else 0.0001
        rs = avg_gain / max(avg_loss, 0.00001)
        rsi = 100 - (100 / (1 + rs))

        avg_vol = sum(volumes[-10:]) / 10 if len(volumes) >= 10 else volumes[-1]
        vol_ratio = volumes[-1] / max(avg_vol, 0.0001)

        return {
            "price": cur_price,
            "high_24h": max(highs),
            "low_24h": min(lows),
            "ema9": round(ema9, 4),
            "rsi14": round(rsi, 2),
            "vol_ratio": round(vol_ratio, 2),
            "raw_candles_summary": f"{symbol}:{cur_price:.2f}|RSI:{rsi:.1f}|EMA:{ema9:.2f}|V:{vol_ratio:.1f}x"
        }
    except Exception as e:
        print(f"⚠️ Market indicator processing error on {symbol}: {e}")
        return None

SYSTEM_INSTRUCTIONS = """
Role: Master Crypto Quantitative Analyst & High-Conviction Scalper.
Objective: Maximize $10,000 portfolio ROI in a strict 48-Hour Autonomous Trading Challenge.

48-HOUR CHALLENGE DIRECTIVE:
- You are in full autonomous control. Utilize all technical price data, RSI momentum metrics, EMA trend alignments, volume ratios, 24h range extremes, and historical market dynamics.
- Evaluate all tickers in the batch prompt as potential BUY setups.
- CRITICAL SELL DIRECTIVE: Also evaluate any currently open ACTIVE POSITIONS provided in the prompt. If technical momentum weakens, RSI turns overbought, or trend degrades, issue "EXECUTE_PAPER_SELL" for that symbol to secure profits or cut losses early!
- Execute BUY/SELL trades ONLY when your technical analysis indicates high conviction (>75% confidence).
- Keep rationales concise (1-4 words). Output strictly raw standard JSON array without markdown codeblock wrappers (```json), unescaped newlines, trailing commas, or syntax errors.

Schema Example:
[
  {
    "action": "EXECUTE_PAPER_BUY",
    "symbol": "BTCUSDT",
    "confidence_score": 85,
    "target_entry_price": 64500.0,
    "trade_details": {
      "entry_price": 64500.0,
      "stop_loss": 63500.0,
      "take_profit": 67000.0,
      "allocated_amount": 2500.0,
      "risk_reward_ratio": "1:2.5"
    },
    "technical_rationale": ["RSI 34 oversold", "Vol 1.8x"]
  }
]
"""

def manage_active_positions(portfolio):
    active_positions = portfolio.get("active_positions", [])
    remaining_positions = []
    
    try:
        res = requests.get("https://api.binance.us/api/v3/ticker/price", timeout=4).json()
        price_map = {item["symbol"]: float(item["price"]) for item in res if "symbol" in item and "price" in item}
    except Exception as e:
        print(f"⚠️ Error fetching bulk prices for position exits: {e}")
        price_map = {}

    for pos in active_positions:
        sym = pos["symbol"]
        entry = float(pos.get("entry_price", 1.0))
        raw_price = price_map.get(sym)
        
        # Safeguard fallback to entry_price if current price invalid or experiencing extreme abnormal tick variance (>50%)
        if raw_price is None or raw_price <= 0 or abs(raw_price - entry) / entry > 0.5:
            current_price = entry
        else:
            current_price = raw_price

        tp = pos.get("take_profit")
        sl = pos.get("stop_loss")
        
        close_reason = None
        if tp and current_price >= tp:
            close_reason = "TAKE_PROFIT"
        elif sl and current_price <= sl:
            close_reason = "STOP_LOSS"

        if close_reason:
            u_id = portfolio.get("user_id", 1)
            updated_p, closed_rec = db.execute_position_exit(u_id, sym, current_price, exit_reason=close_reason, rationale=pos.get("rationale", ""))
            if updated_p:
                portfolio.update(updated_p)
            if closed_rec:
                pnl = closed_rec["pnl_usd"]
                pnl_pct = closed_rec["pnl_pct"]
                print(f" 🎉 CLOSED POSITION: {sym} via {close_reason} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)")
        else:
            remaining_positions.append(pos)
    
    portfolio["active_positions"] = remaining_positions

def update_equity_snapshot(portfolio, live_prices):
    active_val = 0.0
    for pos in portfolio.get("active_positions", []):
        entry_p = float(pos.get("entry_price", 1.0))
        raw_p = live_prices.get(pos["symbol"])
        
        # Valuation safeguard: fallback to entry_price if current price invalid or >50% tick deviation
        if raw_p is None or raw_p <= 0 or abs(raw_p - entry_p) / entry_p > 0.5:
            cur_p = entry_p
        else:
            cur_p = raw_p

        alloc = float(pos.get("allocated_amount", 0.0))
        qty = float(pos.get("quantity")) if pos.get("quantity") is not None else (alloc / entry_p if entry_p > 0 else 0.0)
        active_val += qty * cur_p
    
    total_eq = portfolio.get("cash_balance", 10000.0) + active_val
    portfolio["invested_amount"] = active_val
    
    snapshot = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "cash": round(portfolio["cash_balance"], 2),
        "invested": round(active_val, 2),
        "total_equity": round(total_eq, 2)
    }
    
    if "equity_history" not in portfolio:
        portfolio["equity_history"] = []
    
    portfolio["equity_history"].append(snapshot)
    if len(portfolio["equity_history"]) > 100:
        portfolio["equity_history"] = portfolio["equity_history"][-100:]

def run_single_scan_pass(passed_api_key=None):
    global ACTIVE_MODEL
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"\n--- [Scan Cycle Start: {timestamp}] ---")
    
    user_ids = db.get_all_users()
    
    # Process position exits across all user portfolios first
    for u_id in user_ids:
        p = load_portfolio(user_id=u_id)
        manage_active_positions(p)
        save_portfolio(p, user_id=u_id)

    # Primary reference portfolio for bot logs & scan decisions (Guest user 1)
    primary_portfolio = load_portfolio(user_id=1)
    if "bot_logs" not in primary_portfolio:
        primary_portfolio["bot_logs"] = []

    def log_bot_event(msg):
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode('ascii', errors='replace').decode('ascii'))
        primary_portfolio["bot_logs"].insert(0, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(primary_portfolio["bot_logs"]) > 50:
            primary_portfolio["bot_logs"] = primary_portfolio["bot_logs"][:50]
        save_portfolio(primary_portfolio, user_id=1)
        
        # Log all errors/exceptions to error_log.txt with full date and time
        if "❌" in msg or "⚠️" in msg or "Error" in msg or "CRITICAL" in msg:
            log_error_to_file(msg)

    log_bot_event(f"🚀 Scan Cycle Start | Active Model: {ACTIVE_MODEL} | Active Users: {len(user_ids)}")

    batch_payload = []
    live_prices = {}
    
    for sym in WATCHLIST:
        metrics = fetch_binance_klines(sym)
        if metrics:
            live_prices[sym] = metrics["price"]
            batch_payload.append(f"SYMBOL: {sym}\nDATA: {metrics['raw_candles_summary']}\n---")

    log_bot_event(f"📡 Processed indicators for {len(batch_payload)} tickers.")

    if not batch_payload:
        log_bot_event("⚠️ Market API Warning: 0 tickers fetched. Retrying on next cycle...")
        return

    if batch_payload:
        try:
            api_key = passed_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("gemini_api_key")
            if not api_key:
                try:
                    import streamlit as st
                    if hasattr(st, "secrets"):
                        if "GEMINI_API_KEY" in st.secrets:
                            api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                        elif "gemini_api_key" in st.secrets:
                            api_key = str(st.secrets["gemini_api_key"]).strip()
                except Exception:
                    pass

            if not api_key or len(str(api_key).strip()) < 10 or api_key == "None":
                log_bot_event(f"❌ CRITICAL: GEMINI_API_KEY is missing or invalid! (Key Length: {len(str(api_key)) if api_key else 0}). Please verify Streamlit Secrets.")
                return

            client = genai.Client(api_key=str(api_key).strip())

            settings = primary_portfolio.get("bot_settings", {
                "min_confidence": 75,
                "take_profit_pct": 4.0,
                "stop_loss_pct": 2.0,
                "max_positions": 5,
                "max_trade_size": 3000.0,
                "bot_attitude": "Balanced",
                "strategy": "Scalping"
            })

            attitude = settings.get("bot_attitude", "Balanced")
            strategy = settings.get("strategy", "Scalping")
            
            header = f"CURRENT_AVAILABLE_CASH: ${primary_portfolio['cash_balance']:,.2f}\n"
            header += f"BOT_SETTINGS: Attitude={attitude}, Strategy={strategy}, MinConfidence={settings.get('min_confidence', 75)}%\n"
            
            active_pos_list = primary_portfolio.get("active_positions", [])
            if active_pos_list:
                header += "CURRENT_ACTIVE_OPEN_POSITIONS:\n"
                for ap in active_pos_list:
                    header += f"- Symbol: {ap['symbol']}, EntryPrice: ${ap['entry_price']:.4f}, Allocated: ${ap['allocated_amount']:.2f}, TP: ${ap.get('take_profit', 0):.4f}, SL: ${ap.get('stop_loss', 0):.4f}\n"
            else:
                header += "CURRENT_ACTIVE_OPEN_POSITIONS: None\n"
            
            header += "\nMARKET_TICKER_DATA:\n"
            prompt = header + "\n".join(batch_payload)
            
            log_bot_event(f"🧠 Querying Gemini API ({ACTIVE_MODEL} | Attitude: {attitude} | Strategy: {strategy})...")
            max_retries = 4
            response = None
            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model=ACTIVE_MODEL,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTIONS,
                            response_mime_type="application/json",
                            temperature=0.1,
                            max_output_tokens=4096
                        )
                    )
                    if response and getattr(response, "text", None):
                        break
                except Exception as model_err:
                    err_str = str(model_err)
                    next_model_idx = (MODEL_FALLBACKS.index(ACTIVE_MODEL) + 1) % len(MODEL_FALLBACKS) if ACTIVE_MODEL in MODEL_FALLBACKS else 0
                    prev_model = ACTIVE_MODEL
                    ACTIVE_MODEL = MODEL_FALLBACKS[next_model_idx]
                    log_bot_event(f"⚠️ API error on {prev_model}: {err_str[:120]}. Failover switching to {ACTIVE_MODEL} (attempt {attempt+1}/{max_retries})...")
                    time.sleep(4)

            if response is None or not getattr(response, 'text', None):
                log_bot_event("⚠️ No valid response text from Gemini after retries. Skipping cycle.")
            else:
                raw_text = response.text.strip()
                log_bot_event(f"📥 Raw AI Stream Received ({len(raw_text)} chars): {raw_text[:150]}")
                
                # Strip markdown codeblocks
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                elif raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                raw_text = raw_text.strip()

                import re
                # Clean up unescaped control characters inside JSON strings (newlines, tabs, carriage returns)
                cleaned_text = re.sub(r'[\r\n\t]+', ' ', raw_text)
                cleaned_text = re.sub(r',\s*([\]}])', r'\1', cleaned_text)
                cleaned_text = re.sub(r':\s*NaN', r': null', cleaned_text)

                signals = None
                try:
                    signals = json.loads(cleaned_text)
                except json.JSONDecodeError as decode_err:
                    log_bot_event(f"⚠️ Initial JSON parse failed ({decode_err}). Attempting auto-repair...")
                    repaired_text = cleaned_text
                    last_complete_obj = repaired_text.rfind("}")
                    if last_complete_obj != -1:
                        repaired_text = repaired_text[:last_complete_obj+1]
                        if not repaired_text.endswith("]"):
                            repaired_text += "]"
                        try:
                            signals = json.loads(repaired_text)
                        except Exception:
                            signals = None

                # Fallback protection if JSON repair fails
                if not isinstance(signals, list):
                    log_bot_event("⚠️ AI response JSON parsing failed completely. Using safe default hold signal.")
                    signals = [{
                        "action": "HOLD",
                        "confidence_score": 0,
                        "symbol": "MARKET",
                        "technical_rationale": ["AI response JSON parsing failed"]
                    }]
                    decisions_log = []
                    for s in signals:
                        trade = s.get("trade_details") or {}
                        decisions_log.append({
                            "symbol": s.get("symbol", "N/A"),
                            "action": s.get("action", "NO_TRADE"),
                            "confidence": s.get("confidence_score", 0),
                            "target_entry": s.get("target_entry_price", trade.get("entry_price", "N/A")),
                            "take_profit": trade.get("take_profit", "N/A"),
                            "stop_loss": trade.get("stop_loss", "N/A"),
                            "suggested_alloc": trade.get("allocated_amount", "N/A"),
                            "rationale": "; ".join(s.get("technical_rationale", []) if isinstance(s.get("technical_rationale"), list) else [str(s.get("technical_rationale", ""))]),
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        })

                    # Apply signals across ALL active user accounts in SQLite
                    for u_id in user_ids:
                        user_p = load_portfolio(user_id=u_id)
                        user_p["latest_scan_decisions"] = decisions_log
                        user_settings = user_p.get("bot_settings", settings)
                        
                        u_min_conf = user_settings.get("min_confidence", 75)
                        u_tp_pct = user_settings.get("take_profit_pct", 4.0) / 100.0
                        u_sl_pct = user_settings.get("stop_loss_pct", 2.0) / 100.0
                        u_max_pos = user_settings.get("max_positions", 5)
                        u_max_alloc = user_settings.get("max_trade_size", 3000.0)

                        # Process SELL Signals
                        sell_signals = [s for s in signals if str(s.get("action", "")).upper() == "EXECUTE_PAPER_SELL"]
                        for sell_sig in sell_signals:
                            s_sym = sell_sig.get("symbol")
                            pos_match = next((p for p in user_p.get("active_positions", []) if p["symbol"] == s_sym), None)
                            if pos_match:
                                cur_p = live_prices.get(s_sym, pos_match.get("entry_price", 1.0))
                                rat_list = sell_sig.get("technical_rationale", ["AI Momentum Shift Sell"])
                                rat_str = "; ".join(rat_list) if isinstance(rat_list, list) else str(rat_list)

                                updated_p, _ = db.execute_position_exit(u_id, s_sym, cur_p, exit_reason="AI_MOMENTUM_SELL", rationale=rat_str)
                                if updated_p:
                                    user_p.update(updated_p)

                        # Process BUY Signals
                        valid_buys = [s for s in signals if str(s.get("action", "")).upper() == "EXECUTE_PAPER_BUY" and float(s.get("confidence_score", 0) or 0) >= u_min_conf]
                        valid_buys = sorted(valid_buys, key=lambda x: float(x.get("confidence_score", 0) or 0), reverse=True)

                        for signal in valid_buys:
                            sym = signal.get("symbol")
                            already_in = any(p["symbol"] == sym for p in user_p.get("active_positions", []))
                            if len(user_p.get("active_positions", [])) < u_max_pos and not already_in:
                                trade = signal.get("trade_details") or {}
                                entry_pr = live_prices.get(sym, trade.get("entry_price", 0.0))
                                suggested_alloc = float(trade.get("allocated_amount") or 2000.0)
                                alloc = min(suggested_alloc, u_max_alloc, user_p["cash_balance"])

                                if entry_pr > 0 and alloc >= 100.0:
                                    qty = alloc / entry_pr
                                    take_val = float(trade.get("take_profit") or (entry_pr * (1 + u_tp_pct)))
                                    stop_val = float(trade.get("stop_loss") or (entry_pr * (1 - u_sl_pct)))

                                    user_p["cash_balance"] -= alloc
                                    user_p["invested_amount"] = user_p.get("invested_amount", 0.0) + alloc
                                    if "active_positions" not in user_p:
                                        user_p["active_positions"] = []

                                    user_p["active_positions"].append({
                                        "symbol": sym,
                                        "entry_price": entry_pr,
                                        "allocated_amount": alloc,
                                        "quantity": qty,
                                        "stop_loss": stop_val,
                                        "take_profit": take_val,
                                        "risk_reward": trade.get("risk_reward_ratio", "1:2"),
                                        "rationale": "; ".join(signal.get("technical_rationale", []) if isinstance(signal.get("technical_rationale"), list) else [str(signal.get("technical_rationale", ""))]),
                                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    })

                        update_equity_snapshot(user_p, live_prices)
                        user_p["last_scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_portfolio(user_p, user_id=u_id)

                    log_bot_event(f"✅ Multi-User Scan Complete: Decisions saved across {len(user_ids)} active account(s).")
                else:
                    log_bot_event("⚠️ Unexpected response format from AI.")

        except Exception as e:
            log_bot_event(f"❌ Scan Error: {e}")

def main(passed_api_key=None):
    global ACTIVE_MODEL
    print(f"ChartPulse AI Engine v2.0.0 Active [{ACTIVE_MODEL}]")
    print(f"API Quota Optimized Mode: Scanning 20 assets every {SCAN_INTERVAL_SECONDS}s")
    
    try:
        print("⏳ Engine initialized. Initial scan starting in 5 seconds...")
    except Exception:
        print("Engine initialized. Initial scan starting in 5 seconds...")
    time.sleep(5)
    
    while True:
        run_single_scan_pass(passed_api_key=passed_api_key)
        time.sleep(SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
