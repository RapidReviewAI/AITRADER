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
client = genai.Client(api_key=API_KEY)

MODEL_FALLBACKS = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]
ACTIVE_MODEL = MODEL_FALLBACKS[0]

# Top 20 High-Volume Crypto Assets Watchlist
WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "NEARUSDT",
    "SUIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
    "RENDERUSDT", "FETUSDT", "PEPEUSDT", "SHIBUSDT", "ATOMUSDT"
]

STATE_FILE = "portfolio_state.json"
SCAN_INTERVAL_SECONDS = 60  # 60-second scan interval backed by multi-model failover rotation

def load_portfolio():
    default_state = {
        "cash_balance": 10000.00,
        "invested_amount": 0.00,
        "active_positions": [],
        "closed_trades": [],
        "latest_scan_decisions": [],
        "bot_settings": {
            "min_confidence": 75,
            "take_profit_pct": 4.0,
            "stop_loss_pct": 2.0,
            "max_positions": 5,
            "max_trade_size": 3000.0
        },
        "equity_history": [
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "cash": 10000.00,
                "invested": 0.00,
                "total_equity": 10000.00
            }
        ]
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for key, val in default_state.items():
                    if key not in data:
                        data[key] = val
                return data
        except Exception as e:
            print(f"⚠️ Error reading {STATE_FILE}, returning defaults: {e}")
            return default_state
    return default_state

def save_portfolio(state):
    """Atomic write to avoid JSON corruption during concurrent dashboard reads."""
    temp_file = f"{STATE_FILE}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4)
        os.replace(temp_file, STATE_FILE)
    except Exception as e:
        print(f"❌ Error saving {STATE_FILE}: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

def fetch_binance_klines(symbol):
    """Fetches last 30 5m candles and calculates EMA, RSI, & Volume metrics."""
    try:
        url = f"https://api.binance.us/api/v3/klines?symbol={symbol}&interval=5m&limit=30"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if not data or len(data) < 15:
                return None
            
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
        print(f"⚠️ Binance API error on {symbol}: {e}")
    return None

SYSTEM_INSTRUCTIONS = """
Role: High-Conviction Crypto Scalper.
Objective: Maximize $10k portfolio profit over 48h.
Rules:
- YOU MUST RETURN AN EVALUATION FOR ALL 20 SYMBOLS IN PROMPT.
- Keep technical_rationale short (under 5 words per item).
- MAX 5 active positions, max $3000/trade (<=30% cash).
- Trigger EXECUTE_PAPER_BUY only when confidence >= 75%.
- Return ONLY a valid compact JSON array.

JSON Output Schema:
[
  {
    "action": "EXECUTE_PAPER_BUY" or "NO_TRADE",
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
        current_price = price_map.get(sym)
        if current_price is None:
            remaining_positions.append(pos)
            continue

        tp = pos.get("take_profit")
        sl = pos.get("stop_loss")
        
        close_reason = None
        if tp and current_price >= tp:
            close_reason = "TAKE_PROFIT"
        elif sl and current_price <= sl:
            close_reason = "STOP_LOSS"

        if close_reason:
            alloc = pos["allocated_amount"]
            entry = pos["entry_price"]
            qty = alloc / entry
            exit_value = qty * current_price
            pnl = exit_value - alloc
            pnl_pct = (pnl / alloc) * 100

            portfolio["cash_balance"] += exit_value
            portfolio["invested_amount"] -= alloc

            closed_record = {
                "symbol": sym,
                "entry_price": entry,
                "exit_price": current_price,
                "allocated_amount": alloc,
                "exit_value": exit_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "close_reason": close_reason,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if "closed_trades" not in portfolio:
                portfolio["closed_trades"] = []
            portfolio["closed_trades"].insert(0, closed_record)
            print(f" 🎉 CLOSED POSITION: {sym} via {close_reason} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)")
        else:
            remaining_positions.append(pos)
    
    portfolio["active_positions"] = remaining_positions

def update_equity_snapshot(portfolio, live_prices):
    active_val = 0.0
    for pos in portfolio.get("active_positions", []):
        cur_p = live_prices.get(pos["symbol"], pos.get("entry_price", 1.0))
        qty = pos.get("allocated_amount", 0.0) / pos.get("entry_price", 1.0)
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

def main():
    global ACTIVE_MODEL
    print(f"🚀 ChartPulse AI Engine v2.0.0 Active [{ACTIVE_MODEL}]")
    print(f"⚡ API Quota Optimized Mode: Scanning 10 assets every {SCAN_INTERVAL_SECONDS}s")
    
    print("⏳ Engine initialized. Initial scan starting in 5 seconds...")
    time.sleep(5)
    
    while True:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n--- [Scan Cycle Start: {timestamp}] ---")
        
        portfolio = load_portfolio()
        manage_active_positions(portfolio)

        batch_payload = []
        live_prices = {}
        
        for sym in WATCHLIST:
            metrics = fetch_binance_klines(sym)
            if metrics:
                live_prices[sym] = metrics["price"]
                batch_payload.append(f"SYMBOL: {sym}\nDATA: {metrics['raw_candles_summary']}\n---")

        print(f"📡 Processed technical indicators for {len(batch_payload)} tickers.")

        if batch_payload:
            try:
                header = f"CURRENT_AVAILABLE_CASH: ${portfolio['cash_balance']:,.2f}\n"
                prompt = header + "\n".join(batch_payload)
                
                print(f"🧠 Querying Gemini API ({ACTIVE_MODEL})...")
                max_retries = 3
                response = None
                for attempt in range(max_retries):
                    try:
                        response = client.models.generate_content(
                            model=ACTIVE_MODEL,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_INSTRUCTIONS,
                                response_mime_type="application/json",
                                temperature=0.2,
                                max_output_tokens=2048
                            )
                        )
                        break
                    except Exception as model_err:
                        err_str = str(model_err)
                        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                            wait_sec = (attempt + 1) * 10
                            next_model_idx = (MODEL_FALLBACKS.index(ACTIVE_MODEL) + 1) % len(MODEL_FALLBACKS) if ACTIVE_MODEL in MODEL_FALLBACKS else 0
                            ACTIVE_MODEL = MODEL_FALLBACKS[next_model_idx]
                            print(f"⚠️ Quota rate limit hit (429). Switching model to {ACTIVE_MODEL} & retrying in {wait_sec}s (Attempt {attempt+1}/{max_retries})...")
                            time.sleep(wait_sec)
                        elif "404" in err_str or "NOT_FOUND" in err_str:
                            print(f"⚠️ {ACTIVE_MODEL} returned 404. Auto-discovering fallback model...")
                            ACTIVE_MODEL = get_valid_fallback_model(client)
                            time.sleep(5)
                        else:
                            raise model_err

                
                if response is None or not getattr(response, 'text', None):
                    print("⚠️ No valid response from Gemini after retries. Skipping cycle.")
                else:
                    raw_text = response.text.strip()
                    # Clean markdown codeblocks if present
                    if raw_text.startswith("```json"):
                        raw_text = raw_text[7:]
                    if raw_text.startswith("```"):
                        raw_text = raw_text[3:]
                    if raw_text.endswith("```"):
                        raw_text = raw_text[:-3]
                    raw_text = raw_text.strip()

                    try:
                        signals = json.loads(raw_text)
                    except json.JSONDecodeError:
                        # Auto-repair unterminated JSON array if truncated mid-stream
                        if raw_text.startswith("[") and not raw_text.endswith("]"):
                            last_complete_obj = raw_text.rfind("}")
                            if last_complete_obj != -1:
                                repaired_text = raw_text[:last_complete_obj+1] + "]"
                                try:
                                    signals = json.loads(repaired_text)
                                    print(" 🔧 Auto-repaired truncated JSON response from AI.")
                                except Exception:
                                    signals = None
                            else:
                                signals = None
                        else:
                            signals = None
                    if isinstance(signals, list):
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
                        portfolio["latest_scan_decisions"] = decisions_log
                        
                        # Load dynamic slider settings from portfolio state
                        settings = portfolio.get("bot_settings", {
                            "min_confidence": 75,
                            "take_profit_pct": 4.0,
                            "stop_loss_pct": 2.0,
                            "max_positions": 5,
                            "max_trade_size": 3000.0
                        })
                        min_conf = settings.get("min_confidence", 75)
                        tp_pct = settings.get("take_profit_pct", 4.0) / 100.0
                        sl_pct = settings.get("stop_loss_pct", 2.0) / 100.0
                        max_pos = settings.get("max_positions", 5)
                        max_alloc_cap = settings.get("max_trade_size", 3000.0)

                        valid_buys = [s for s in signals if str(s.get("action", "")).upper() == "EXECUTE_PAPER_BUY" and float(s.get("confidence_score", 0) or 0) >= min_conf]
                        valid_buys = sorted(valid_buys, key=lambda x: float(x.get("confidence_score", 0) or 0), reverse=True)
                        
                        for signal in valid_buys:
                            sym = signal.get("symbol")
                            confidence = signal.get("confidence_score", 0)
                            current_active_count = len(portfolio.get("active_positions", []))
                            already_in = any(p["symbol"] == sym for p in portfolio.get("active_positions", []))
                            
                            # Dynamic Limit: Maximum active positions simultaneously
                            if current_active_count >= max_pos:
                                print(f" ✋ Buy signal for {sym} skipped (Max active positions limit [{max_pos}] reached).")
                                break

                            if not already_in and portfolio["cash_balance"] > 100.0:
                                trade = signal.get("trade_details") or {}
                                try:
                                    suggested_alloc = float(trade.get("allocated_amount") or (portfolio["cash_balance"] * 0.25))
                                except (ValueError, TypeError):
                                    suggested_alloc = portfolio["cash_balance"] * 0.25
                                
                                # Dynamic Limit: Max 30% of available cash per trade, capped at max_trade_size slider setting
                                max_allowed_alloc = min(portfolio["cash_balance"] * 0.30, max_alloc_cap)
                                alloc = min(suggested_alloc, max_allowed_alloc)
                                
                                if alloc >= 50.0 and (sym in live_prices or "entry_price" in trade):
                                    portfolio["cash_balance"] -= alloc
                                    portfolio["invested_amount"] += alloc
                                    
                                    try:
                                        entry_pr = float(trade.get("entry_price") or live_prices.get(sym, 1.0))
                                    except (ValueError, TypeError):
                                        entry_pr = live_prices.get(sym, 1.0)

                                    # Use custom Take Profit % and Stop Loss % if configured by user sliders
                                    try:
                                        stop_val = float(trade.get("stop_loss")) if trade.get("stop_loss") else entry_pr * (1 - sl_pct)
                                    except (ValueError, TypeError):
                                        stop_val = entry_pr * (1 - sl_pct)

                                    try:
                                        take_val = float(trade.get("take_profit")) if trade.get("take_profit") else entry_pr * (1 + tp_pct)
                                    except (ValueError, TypeError):
                                        take_val = entry_pr * (1 + tp_pct)

                                    # Override with exact slider percentages if user specified strict custom targets
                                    stop_val = round(entry_pr * (1 - sl_pct), 4)
                                    take_val = round(entry_pr * (1 + tp_pct), 4)
                                    
                                    portfolio["active_positions"].append({
                                        "symbol": sym,
                                        "entry_price": entry_pr,
                                        "allocated_amount": alloc,
                                        "stop_loss": stop_val,
                                        "take_profit": take_val,
                                        "risk_reward": trade.get("risk_reward_ratio", "1:2"),
                                        "rationale": "; ".join(signal.get("technical_rationale", []) if isinstance(signal.get("technical_rationale"), list) else [str(signal.get("technical_rationale", ""))]),
                                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    })
                                    print(f" ⚡ EXECUTED POSITION BUY: ${alloc:,.2f} in {sym} (Confidence: {confidence}% | TP: +{settings.get('take_profit_pct')}%, SL: -{settings.get('stop_loss_pct')}%)")
                                else:
                                    print(f" ⚠️ Could not execute buy for {sym}: price data missing or allocation below minimum.")
                            elif already_in:
                                print(f" ℹ️ Buy signal for {sym} skipped (position already open).")
                        
                        if not valid_buys:
                            print(f" 💤 No buy triggers met minimum confidence threshold (>= {min_conf}%).")
                    else:
                        print("⚠️ Unexpected response format from AI.")

            except Exception as e:
                print(f"❌ Scan Error: {e}")

        update_equity_snapshot(portfolio, live_prices)
        save_portfolio(portfolio)

        print(f"⏱️ Sleeping {SCAN_INTERVAL_SECONDS}s until next scan...")
        time.sleep(SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
