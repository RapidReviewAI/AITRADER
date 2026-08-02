import streamlit as st
import json
import os
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import threading
import time

# Auto-start backend bot in a background thread if running on Streamlit Cloud
def start_background_bot_thread():
    if not st.session_state.get("bot_thread_started"):
        try:
            import backend_bot
            t = threading.Thread(target=backend_bot.main, daemon=True)
            t.start()
            st.session_state["bot_thread_started"] = True
        except Exception as e:
            pass

start_background_bot_thread()

st.set_page_config(
    page_title="ChartPulse AI — Pro Trading Hub",
    page_icon="⚡",
    layout="wide"
)

st.markdown("""
    <style>
    .main {
        background-color: #0b0f19;
    }
    .stMetric {
        background: rgba(30, 41, 59, 0.6);
        border: 1px solid rgba(51, 65, 85, 0.8);
        padding: 12px 16px;
        border-radius: 10px;
    }
    .badge-buy {
        background-color: #059669;
        color: #ffffff;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 13px;
    }
    .badge-pass {
        background-color: #334155;
        color: #cbd5e1;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 13px;
    }
    .stream-watermark {
        position: fixed;
        top: 20px;
        right: 30px;
        z-index: 9999;
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid rgba(59, 130, 246, 0.4);
        padding: 8px 16px;
        border-radius: 8px;
        color: #f8fafc;
        font-family: 'Inter', sans-serif;
        font-size: 13px;
        font-weight: 700;
        backdrop-filter: blur(6px);
    }
    .stream-watermark span {
        color: #3b82f6;
    }
    </style>
    <div class="stream-watermark">
        ⚡ <span>ChartPulse AI v2.2</span> | Interactive Live Charts
    </div>
""", unsafe_allow_html=True)

STATE_FILE = "portfolio_state.json"

@st.cache_data(ttl=3)
def fetch_all_market_prices():
    """Fetches Binance market prices cached for 3 seconds."""
    try:
        res = requests.get("https://api.binance.us/api/v3/ticker/price", timeout=3).json()
        return {item["symbol"]: float(item["price"]) for item in res if "symbol" in item and "price" in item}
    except Exception:
        return {}

@st.cache_data(ttl=10)
def fetch_binance_candlesticks(symbol):
    """Fetches 5m klines from Binance and formats as pandas DataFrame."""
    try:
        url = f"https://api.binance.us/api/v3/klines?symbol={symbol}&interval=5m&limit=40"
        res = requests.get(url, timeout=4).json()
        if isinstance(res, list) and len(res) > 0:
            df = pd.DataFrame(res, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "num_trades", "tbb", "tbq", "ignore"
            ])
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            return df
    except Exception as e:
        print(f"⚠️ Error fetching candlestick data for {symbol}: {e}")
    return pd.DataFrame()

def manage_active_positions_dashboard(portfolio):
    """Instantly checks if any open position reached TP/SL during UI resync and executes exit."""
    active_positions = portfolio.get("active_positions", [])
    if not active_positions:
        return False
        
    market_prices = fetch_all_market_prices()
    remaining_positions = []
    has_closed = False

    for pos in active_positions:
        sym = pos["symbol"]
        current_price = market_prices.get(sym)
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
            has_closed = True
            alloc = pos["allocated_amount"]
            entry = pos["entry_price"]
            qty = alloc / entry if entry > 0 else 0
            exit_value = qty * current_price
            pnl = exit_value - alloc
            pnl_pct = (pnl / alloc) * 100 if alloc > 0 else 0

            portfolio["cash_balance"] += exit_value
            portfolio["invested_amount"] = max(portfolio.get("invested_amount", 0) - alloc, 0)

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
        else:
            remaining_positions.append(pos)
    
    if has_closed:
        portfolio["active_positions"] = remaining_positions
        temp_file = f"{STATE_FILE}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(portfolio, f, indent=4)
            os.replace(temp_file, STATE_FILE)
        except Exception:
            pass
    return has_closed

def load_portfolio():
    default_state = {
        "cash_balance": 10000.00,
        "invested_amount": 0.00,
        "active_positions": [],
        "closed_trades": [],
        "latest_scan_decisions": [],
        "equity_history": []
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for key, val in default_state.items():
                    if key not in data:
                        data[key] = val
                manage_active_positions_dashboard(data)
                return data
        except Exception:
            return default_state
    return default_state

def render_live_dashboard():
    portfolio = load_portfolio()
    # Ensure any pending exit triggers (TP/SL) update portfolio state before rendering metrics
    manage_active_positions_dashboard(portfolio)
    market_prices = fetch_all_market_prices()

    col_title, col_btn = st.columns([0.76, 0.24])
    with col_title:
        st.title("⚡ ChartPulse AI: $10,000 Trading Hub")
        st.caption("v2.1.0 | Autonomous Gemini AI scanning 10 crypto assets every 60s with pre-calculated RSI & EMA technical indicators.")

    with col_btn:
        st.write("")
        if st.button("🗑️ Reset $10,000 State", use_container_width=True):
            default_state = {
                "cash_balance": 10000.00,
                "invested_amount": 0.00,
                "active_positions": [],
                "closed_trades": [],
                "latest_scan_decisions": [],
                "equity_history": [
                    {
                        "timestamp": "00:00:00",
                        "cash": 10000.00,
                        "invested": 0.00,
                        "total_equity": 10000.00
                    }
                ]
            }
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(default_state, f, indent=4)
            st.rerun()

    cash = portfolio.get("cash_balance", 10000.00)
    active_positions = portfolio.get("active_positions", [])
    closed_trades = portfolio.get("closed_trades", [])
    scan_decisions = portfolio.get("latest_scan_decisions", [])
    equity_history = portfolio.get("equity_history", [])

    # Dynamic calculation of total active market value
    active_value = 0.0
    for pos in active_positions:
        cur_price = market_prices.get(pos["symbol"], pos.get("entry_price", 1.0))
        qty = pos.get("allocated_amount", 0.0) / pos.get("entry_price", 1.0) if pos.get("entry_price", 0) > 0 else 0
        active_value += qty * cur_price

    total_equity = cash + active_value
    total_pnl = total_equity - 10000.00
    pnl_pct = (total_pnl / 10000.00) * 100

    # Stats Calculation
    wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
    win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0.0
    total_profit = sum([t.get("pnl", 0) for t in wins]) if wins else 0.0
    losses = [t for t in closed_trades if t.get("pnl", 0) <= 0]
    total_loss = abs(sum([t.get("pnl", 0) for t in losses])) if losses else 0.0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else (total_profit if total_profit > 0 else 1.0)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Equity", f"${total_equity:,.2f}", f"{pnl_pct:+.2f}%")
    c2.metric("Liquid Cash", f"${cash:,.2f}")
    c3.metric("Active Investments", f"${active_value:,.2f}")
    c4.metric("Active Open Positions", len(active_positions))
    c5.metric("Win Rate / Profit Factor", f"{win_rate:.1f}%", f"PF: {profit_factor:.2f}")

    st.divider()

    tab_overview, tab_brain, tab_history = st.tabs(["📊 Performance & Active Positions", "🧠 Detailed AI Brain Analysis", "📜 Closed Trade History & Logs"])

    with tab_overview:
        col_left, col_right = st.columns([0.65, 0.35])
        
        with col_left:
            st.subheader("📈 Equity Growth Curve")
            if len(equity_history) > 1:
                df_eq = pd.DataFrame(equity_history)
                fig = px.line(df_eq, x="timestamp", y="total_equity", title="Portfolio Total Equity ($ USD)", markers=True)
                fig.update_layout(template="plotly_dark", margin=dict(l=20, r=20, t=30, b=20), height=300)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Equity progression chart populates live as scans complete.")

        with col_right:
            st.subheader("🎯 Capital Allocation")
            alloc_data = {"Liquid Cash": max(cash, 0), "Active Investments": max(active_value, 0)}
            fig_pie = px.pie(names=list(alloc_data.keys()), values=list(alloc_data.values()), hole=0.5, title="Cash vs Invested")
            fig_pie.update_layout(template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10), height=300)
            st.plotly_chart(fig_pie, use_container_width=True)

        st.subheader("📊 Active Open Positions & Live Trade Charts")
        if active_positions:
            active_symbols = [p["symbol"] for p in active_positions]
            selected_symbol = st.selectbox("📈 Select Active Position to Inspect Live Chart:", active_symbols, index=0)
            selected_pos = next((p for p in active_positions if p["symbol"] == selected_symbol), active_positions[0])
            
            # Ultra-Clean, High-Contrast Live Price Line Chart
            df_klines = fetch_binance_candlesticks(selected_symbol)
            if not df_klines.empty:
                cur_p = market_prices.get(selected_symbol, df_klines["close"].iloc[-1])
                entry_p = float(selected_pos.get("entry_price", 0))
                tp_p = float(selected_pos.get("take_profit", 0)) if selected_pos.get("take_profit") else None
                sl_p = float(selected_pos.get("stop_loss", 0)) if selected_pos.get("stop_loss") else None

                # Clean Metric Cards Header
                c_p1, c_p2, c_p3, c_p4 = st.columns(4)
                c_p1.metric("📍 CURRENT LIVE PRICE", f"${cur_p:,.4f}")
                c_p2.metric("🔵 YOUR BUY ENTRY", f"${entry_p:,.4f}")
                c_p3.metric("🟢 TAKE PROFIT GOAL", f"${tp_p:,.4f}" if tp_p else "N/A")
                c_p4.metric("🔴 STOP LOSS TARGET", f"${sl_p:,.4f}" if sl_p else "N/A")

                # Single Clean Line Chart
                fig_clean = go.Figure()

                # Clean Price Line
                fig_clean.add_trace(
                    go.Scatter(
                        x=df_klines["open_time"],
                        y=df_klines["close"],
                        mode="lines",
                        line=dict(color="#ffffff", width=2.5),
                        name="Price ($ USD)"
                    )
                )

                # 🟡 CURRENT LIVE PRICE LINE (Yellow Solid Line across chart)
                fig_clean.add_hline(
                    y=cur_p, line_dash="solid", line_color="#facc15", line_width=2.5,
                    annotation_text=f" 🟡 CURRENT PRICE: ${cur_p:,.4f} ",
                    annotation_position="top left", annotation_font_color="#000000", annotation_bgcolor="#facc15"
                )

                # 🟢 TAKE PROFIT LINE (Green)
                if tp_p:
                    fig_clean.add_hline(
                        y=tp_p, line_dash="solid", line_color="#10b981", line_width=2.5,
                        annotation_text=f" 🟢 TAKE PROFIT GOAL: ${tp_p:,.4f} ",
                        annotation_position="top right", annotation_font_color="#ffffff", annotation_bgcolor="#10b981"
                    )

                # 🔵 BUY ENTRY LINE (Blue)
                if entry_p > 0:
                    fig_clean.add_hline(
                        y=entry_p, line_dash="dash", line_color="#3b82f6", line_width=2,
                        annotation_text=f" 🔵 BUY ENTRY: ${entry_p:,.4f} ",
                        annotation_position="bottom right", annotation_font_color="#ffffff", annotation_bgcolor="#3b82f6"
                    )

                # 🔴 STOP LOSS LINE (Red)
                if sl_p:
                    fig_clean.add_hline(
                        y=sl_p, line_dash="solid", line_color="#ef4444", line_width=2.5,
                        annotation_text=f" 🔴 STOP LOSS TARGET: ${sl_p:,.4f} ",
                        annotation_position="bottom right", annotation_font_color="#ffffff", annotation_bgcolor="#ef4444"
                    )

                # 🟡 LIVE CURRENT PRICE BADGE (Yellow Marker at end)
                fig_clean.add_trace(
                    go.Scatter(
                        x=[df_klines["open_time"].iloc[-1]],
                        y=[cur_p],
                        mode="markers+text",
                        marker=dict(color="#facc15", size=14, symbol="circle"),
                        text=[f"  📍 NOW: ${cur_p:,.4f}"],
                        textposition="middle right",
                        textfont=dict(color="#facc15", size=14, family="Arial Black"),
                        name="Current Live Price"
                    )
                )

                # Auto-scale Y-axis tightly around entry, SL, TP, and current price
                all_vals = [v for v in [df_klines["close"].min(), df_klines["close"].max(), cur_p, entry_p, tp_p, sl_p] if v]
                min_y = min(all_vals) * 0.998
                max_y = max(all_vals) * 1.002

                fig_clean.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0b0f19",
                    plot_bgcolor="#0f172a",
                    height=450,
                    margin=dict(l=20, r=120, t=30, b=20),
                    showlegend=False
                )
                fig_clean.update_yaxes(range=[min_y, max_y], gridcolor="#1e293b", tickformat="$,.2f")
                fig_clean.update_xaxes(gridcolor="#1e293b")

            else:
                st.warning(f"Could not load live chart data for {selected_symbol}.")

            # Compact Positions Summary List with AI Rationale Expanders
            st.write("---")
            st.subheader("📋 Active Open Positions & Instant Actions")
            for p in active_positions:
                sym = p.get("symbol", "N/A")
                cur = market_prices.get(sym, p.get("entry_price", 0.0))
                entry_p = p.get("entry_price", 1.0)
                allocated = p.get("allocated_amount", 0.0)
                qty = allocated / entry_p if entry_p > 0 else 0.0
                cur_val = qty * cur
                unrealized_pnl = cur_val - allocated
                unrealized_pct = ((cur - entry_p) / entry_p) * 100 if entry_p > 0 else 0.0
                tp_val = p.get('take_profit', 0.0)
                sl_val = p.get('stop_loss', 0.0)
                time_bought = p.get('timestamp', 'N/A')
                rationale_text = p.get('rationale', 'High conviction momentum buy signal.')

                pnl_color = "🟢" if unrealized_pnl >= 0 else "🔴"
                
                with st.expander(f"{pnl_color} **{sym}** | Live: **${cur:,.4f}** | PnL: **${unrealized_pnl:+,.2f} ({unrealized_pct:+.2f}%)** | Bought: **{time_bought}**", expanded=False):
                    c_det1, c_det2, c_det3 = st.columns([0.40, 0.35, 0.25])
                    with c_det1:
                        st.markdown(f"**Bought At:** `${entry_p:,.4f}`")
                        st.markdown(f"**Current Price:** `${cur:,.4f}`")
                        st.markdown(f"**Capital Invested:** `${allocated:,.2f}`")
                    with c_det2:
                        st.markdown(f"**Take Profit Goal:** `${tp_val:,.4f}`")
                        st.markdown(f"**Stop Loss Target:** `${sl_val:,.4f}`")
                        st.markdown(f"**Order Time:** `{time_bought}`")
                    with c_action:
                        confirm_sell_item = st.checkbox("Confirm Sell", key=f"confirm_list_{sym}")
                        if st.button(f"🔴 SELL {sym} NOW", key=f"sell_btn_{sym}", type="primary", use_container_width=True):
                            if not confirm_sell_item:
                                st.warning("Check 'Confirm Sell' first!")
                            else:
                                exit_value = cur_val
                                pnl = unrealized_pnl
                                pnl_pct = unrealized_pct

                                portfolio["cash_balance"] += exit_value
                                portfolio["invested_amount"] = max(portfolio.get("invested_amount", 0) - allocated, 0)

                                closed_record = {
                                    "symbol": sym,
                                    "entry_price": entry_p,
                                    "exit_price": cur,
                                    "allocated_amount": allocated,
                                    "exit_value": exit_value,
                                    "pnl": pnl,
                                    "pnl_pct": pnl_pct,
                                    "stop_loss": sl_val,
                                    "take_profit": tp_val,
                                    "close_reason": "MANUAL_SELL_NOW",
                                    "rationale": rationale_text,
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }
                                if "closed_trades" not in portfolio:
                                    portfolio["closed_trades"] = []
                                portfolio["closed_trades"].insert(0, closed_record)

                                portfolio["active_positions"] = [pos for pos in active_positions if pos["symbol"] != sym]

                                temp_file = f"{STATE_FILE}.tmp"
                                try:
                                    with open(temp_file, "w", encoding="utf-8") as f:
                                        json.dump(portfolio, f, indent=4)
                                    os.replace(temp_file, STATE_FILE)
                                except Exception:
                                    pass

                                st.success(f"🎉 Manually closed position in {sym} at ${cur:,.4f} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)")
                                st.rerun()
                    
                    st.markdown("---")
                    st.markdown(f"**🧠 AI Execution Rationale:** {rationale_text}")

            # Detailed Transaction Logs & Closed History
            st.write("---")
            st.subheader("📜 Detailed Transaction & Trade History Logs")
            fresh_closed = portfolio.get("closed_trades", [])
            if fresh_closed:
                for c in fresh_closed:
                    sym_c = c.get("symbol", "N/A")
                    pnl_c = c.get("pnl", 0.0)
                    pnl_pct_c = c.get("pnl_pct", 0.0)
                    badge_c = "🟢 WIN" if pnl_c >= 0 else "🔴 LOSS"
                    reason_c = c.get("close_reason", "MANUAL")
                    t_closed = c.get("timestamp", "N/A")
                    entry_c = c.get("entry_price", 0.0)
                    exit_c = c.get("exit_price", 0.0)
                    tp_c = c.get("take_profit", 0.0)
                    sl_c = c.get("stop_loss", 0.0)
                    alloc_c = c.get("allocated_amount", 0.0)
                    val_c = c.get("exit_value", 0.0)
                    rat_c = c.get("rationale", "Standard AI momentum execution.")

                    with st.expander(f"{badge_c} **{sym_c}** | PnL: **${pnl_c:+,.2f} ({pnl_pct_c:+.2f}%)** | Exit via `{reason_c}` @ {t_closed}"):
                        c_t1, c_t2, c_t3 = st.columns(3)
                        c_t1.markdown(f"**Bought Price:** `${entry_c:,.4f}`\n\n**Exit Price:** `${exit_c:,.4f}`")
                        c_t2.markdown(f"**Take Profit Goal:** `${tp_c:,.4f}`\n\n**Stop Loss Target:** `${sl_c:,.4f}`")
                        c_t3.markdown(f"**Invested Capital:** `${alloc_c:,.2f}`\n\n**Final Realized Value:** `${val_c:,.2f}`")
                        st.markdown("---")
                        st.markdown(f"**🧠 AI Trade Rationale:** {rat_c}")
            else:
                st.info("No closed trades recorded yet.")
        else:
            st.info("No active open positions. AI is scanning for high-conviction momentum setups...")
            st.write("---")
            st.subheader("📜 Detailed Transaction & Trade History Logs")
            fresh_closed = portfolio.get("closed_trades", [])
            if fresh_closed:
                for c in fresh_closed:
                    sym_c = c.get("symbol", "N/A")
                    pnl_c = c.get("pnl", 0.0)
                    pnl_pct_c = c.get("pnl_pct", 0.0)
                    badge_c = "🟢 WIN" if pnl_c >= 0 else "🔴 LOSS"
                    reason_c = c.get("close_reason", "MANUAL")
                    t_closed = c.get("timestamp", "N/A")
                    entry_c = c.get("entry_price", 0.0)
                    exit_c = c.get("exit_price", 0.0)
                    tp_c = c.get("take_profit", 0.0)
                    sl_c = c.get("stop_loss", 0.0)
                    alloc_c = c.get("allocated_amount", 0.0)
                    val_c = c.get("exit_value", 0.0)
                    rat_c = c.get("rationale", "Standard AI momentum execution.")

                    with st.expander(f"{badge_c} **{sym_c}** | PnL: **${pnl_c:+,.2f} ({pnl_pct_c:+.2f}%)** | Exit via `{reason_c}` @ {t_closed}"):
                        c_t1, c_t2, c_t3 = st.columns(3)
                        c_t1.markdown(f"**Bought Price:** `${entry_c:,.4f}`\n\n**Exit Price:** `${exit_c:,.4f}`")
                        c_t2.markdown(f"**Take Profit Goal:** `${tp_c:,.4f}`\n\n**Stop Loss Target:** `${sl_c:,.4f}`")
                        c_t3.markdown(f"**Invested Capital:** `${alloc_c:,.2f}`\n\n**Final Realized Value:** `${val_c:,.2f}`")
                        st.markdown("---")
            else:
                st.info("No closed trades recorded yet.")

    with tab_brain:
        st.subheader("🧠 Gemini AI Brain - Detailed Scan Analysis")
        st.caption("Complete view of AI evaluations: why it bought, why it passed, target buy entry, take profit, stop loss, and confidence levels.")
        
        if scan_decisions:
            for s in scan_decisions:
                action = s.get("action", "NO_TRADE")
                symbol = s.get("symbol", "N/A")
                conf = s.get("confidence", 0)
                rationale = s.get("rationale", "No rationale provided.")
                target_entry = s.get("target_entry", "N/A")
                tp = s.get("take_profit", "N/A")
                sl = s.get("stop_loss", "N/A")
                alloc = s.get("suggested_alloc", "N/A")

                badge = f"🟢 BUY (Confidence {conf}%)" if action == "EXECUTE_PAPER_BUY" else f"⚪ PASS (Confidence {conf}%)"
                
                with st.expander(f"{badge} | **{symbol}** @ {s.get('timestamp', '')}"):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.markdown(f"**Action:** `{action}`")
                    c2.markdown(f"**Target Entry:** `${target_entry}`" if isinstance(target_entry, (int, float)) else f"**Target Entry:** `{target_entry}`")
                    c3.markdown(f"**Take Profit Goal:** `${tp}`" if isinstance(tp, (int, float)) else f"**Take Profit Goal:** `{tp}`")
                    c4.markdown(f"**Stop Loss Level:** `${sl}`" if isinstance(sl, (int, float)) else f"**Stop Loss Level:** `{sl}`")
                    
                    st.markdown(f"**Suggested Allocation:** `${alloc:,.2f}`" if isinstance(alloc, (int, float)) else f"**Suggested Allocation:** `{alloc}`")
                    st.markdown(f"**AI Reasoning:** {rationale}")
        else:
            st.info("AI scan matrix will update automatically as the background bot completes its market scan.")

    with tab_history:
        st.subheader("📜 Closed Trade History")
        if closed_trades:
            closed_rows = []
            for c in closed_trades:
                closed_rows.append({
                    "Symbol": c.get("symbol", "N/A"),
                    "Close Reason": c.get("close_reason", "N/A"),
                    "Entry Price": f"${c.get('entry_price', 0.0):,.4f}",
                    "Exit Price": f"${c.get('exit_price', 0.0):,.4f}",
                    "Invested Capital": f"${c.get('allocated_amount', 0.0):,.2f}",
                    "Final Value": f"${c.get('exit_value', 0.0):,.2f}",
                    "PnL ($)": f"${c.get('pnl', 0.0):+,.2f}",
                    "PnL (%)": f"{c.get('pnl_pct', 0.0):+.2f}%",
                    "Close Timestamp": c.get("timestamp", "N/A")
                })
            st.dataframe(pd.DataFrame(closed_rows), use_container_width=True)
        else:
            st.write("No closed trades recorded yet.")

# Sidebar Controls & Bot Parameter Sliders
st.sidebar.title("⚡ Control Panel")
st.sidebar.caption("ChartPulse AI v2.3.0 Pro")

if st.sidebar.button("🔄 Sync & Refresh UI", use_container_width=True):
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("🎛️ AI Bot Criteria Sliders")

# Read current portfolio settings
portfolio_data = load_portfolio()
cur_settings = portfolio_data.get("bot_settings", {
    "min_confidence": 75,
    "take_profit_pct": 4.0,
    "stop_loss_pct": 2.0,
    "max_positions": 5,
    "max_trade_size": 3000.0
})

min_conf_val = st.sidebar.slider(
    "🎯 Min Confidence Threshold (%)",
    min_value=50, max_value=95,
    value=int(cur_settings.get("min_confidence", 75)),
    step=5,
    help="Minimum AI confidence required to execute a paper buy order."
)

tp_pct_val = st.sidebar.slider(
    "🟢 Take Profit Target (+%)",
    min_value=1.0, max_value=15.0,
    value=float(cur_settings.get("take_profit_pct", 4.0)),
    step=0.5,
    help="Target gain percentage to trigger automatic Take Profit exit."
)

sl_pct_val = st.sidebar.slider(
    "🔴 Stop Loss Protection (-%)",
    min_value=0.5, max_value=10.0,
    value=float(cur_settings.get("stop_loss_pct", 2.0)),
    step=0.5,
    help="Maximum loss percentage before automatic Stop Loss exit."
)

max_pos_val = st.sidebar.slider(
    "📊 Max Open Positions",
    min_value=1, max_value=10,
    value=int(cur_settings.get("max_positions", 5)),
    step=1,
    help="Maximum number of simultaneous active positions allowed."
)

max_trade_val = st.sidebar.slider(
    "💰 Max Trade Allocation ($)",
    min_value=500.0, max_value=5000.0,
    value=float(cur_settings.get("max_trade_size", 3000.0)),
    step=250.0,
    help="Maximum dollar amount allocated per paper trade."
)

# Save settings if changed
new_settings = {
    "min_confidence": min_conf_val,
    "take_profit_pct": tp_pct_val,
    "stop_loss_pct": sl_pct_val,
    "max_positions": max_pos_val,
    "max_trade_size": max_trade_val
}

if new_settings != cur_settings:
    portfolio_data["bot_settings"] = new_settings
    temp_file = f"{STATE_FILE}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(portfolio_data, f, indent=4)
        os.replace(temp_file, STATE_FILE)
        st.sidebar.success("✅ Criteria Saved!")
    except Exception as e:
        st.sidebar.error(f"Error saving criteria: {e}")

st.sidebar.divider()
st.sidebar.markdown("**Active Engine Status:**")
st.sidebar.write("• Watchlist: 20 Assets")
st.sidebar.write("• Scan Loop: Every 60s (Auto-Failover)")
st.sidebar.write(f"• Buy Trigger: >={min_conf_val}% Confidence")
st.sidebar.write(f"• TP Goal: +{tp_pct_val}% | SL Guard: -{sl_pct_val}%")

render_live_dashboard()
