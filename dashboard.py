import streamlit as st
import json
import os
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import threading
import uuid

import db

# Initialize SQLite database schema
db.init_db()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "portfolio_state.json")
SESSIONS_FILE = os.path.join(BASE_DIR, "active_sessions.json")

def track_and_get_active_viewers():
    """Tracks session heartbeats in active_sessions.json and returns active viewer count within last 30s."""
    try:
        if "user_session_id" not in st.session_state:
            st.session_state["user_session_id"] = str(uuid.uuid4())
        
        session_id = st.session_state["user_session_id"]
        now_ts = time.time()
        
        sessions = {}
        if os.path.exists(SESSIONS_FILE):
            try:
                with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                    sessions = json.load(f)
            except Exception:
                sessions = {}

        # Update current session heartbeat
        sessions[session_id] = now_ts

        # Prune sessions older than 30 seconds
        active_sessions = {s_id: ts for s_id, ts in sessions.items() if (now_ts - ts) <= 30}

        # Atomic write
        temp_file = f"{SESSIONS_FILE}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(active_sessions, f, indent=2)
            os.replace(temp_file, SESSIONS_FILE)
        except Exception:
            pass

        return max(1, len(active_sessions))
    except Exception:
        return 1

def render_live_viewer_badge(viewer_count):
    """Renders a styled UI badge showing a pulsing green indicator and live viewer count."""
    badge_html = f"""
    <style>
    .viewer-badge {{
        display: inline-flex;
        align-items: center;
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid rgba(16, 185, 129, 0.4);
        padding: 4px 12px;
        border-radius: 20px;
        font-family: 'Inter', sans-serif;
        font-size: 13px;
        font-weight: 600;
        color: #f8fafc;
        margin-left: 10px;
    }}
    .pulse-dot {{
        width: 8px;
        height: 8px;
        background-color: #10b981;
        border-radius: 50%;
        margin-right: 8px;
        box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
        animation: pulse 1.8s infinite;
    }}
    @keyframes pulse {{
        0% {{
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
        }}
        70% {{
            transform: scale(1);
            box-shadow: 0 0 0 6px rgba(16, 185, 129, 0);
        }}
        100% {{
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
        }}
    }}
    </style>
    <div class="viewer-badge">
        <div class="pulse-dot"></div>
        <span>👁️ {viewer_count} Live Viewer{"s" if viewer_count != 1 else ""}</span>
    </div>
    """
    st.markdown(badge_html, unsafe_allow_html=True)

# Auto-start backend bot in a background thread if running on Streamlit Cloud
def start_background_bot_thread():
    try:
        import backend_bot
        ui_key = None
        try:
            if hasattr(st, "secrets"):
                if "GEMINI_API_KEY" in st.secrets:
                    ui_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                elif "gemini_api_key" in st.secrets:
                    ui_key = str(st.secrets["gemini_api_key"]).strip()
        except Exception:
            ui_key = None
        
        if not ui_key:
            ui_key = os.getenv("GEMINI_API_KEY") or os.getenv("gemini_api_key")

        existing_thread = next((t for t in threading.enumerate() if t.name == "ChartPulseBackendThread"), None)
        if existing_thread is None or not existing_thread.is_alive():
            t = threading.Thread(target=backend_bot.main, args=(ui_key,), daemon=True, name="ChartPulseBackendThread")
            t.start()
            st.session_state["bot_thread_started"] = True
        
        # Fallback check: if last scan is missing or older than 90s, launch non-blocking scan thread
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_scan = data.get("last_scan_time")
                need_sync = True
                if last_scan and last_scan != "N/A":
                    try:
                        last_dt = datetime.strptime(last_scan, "%Y-%m-%d %H:%M:%S")
                        if (datetime.now() - last_dt).total_seconds() <= 90:
                            need_sync = False
                    except Exception:
                        need_sync = True
                if need_sync:
                    threading.Thread(target=backend_bot.run_single_scan_pass, args=(ui_key,), daemon=True).start()
    except Exception:
        pass

start_background_bot_thread()

st.set_page_config(
    page_title="ChartPulse AI — Pro Trading Hub",
    page_icon="⚡",
    layout="wide"
)

# Smooth non-disruptive state refresh (prevents full browser page flash/flicker)
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=15000, key="chartpulse_autorefresh")
except Exception:
    pass

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
    .block-container, .main .block-container {
        padding-top: 1rem !important;
    }
    </style>
""", unsafe_allow_html=True)

WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "NEARUSDT",
    "SUIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
    "RENDERUSDT", "FETUSDT", "PEPEUSDT", "SHIBUSDT", "ATOMUSDT"
]

@st.cache_data(ttl=300)
def fetch_live_crypto_news():
    """Fetches live crypto news headlines from RSS feeds."""
    news_items = []
    rss_urls = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss"
    ]
    try:
        import feedparser
        for url in rss_urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:6]:
                    news_items.append({
                        "title": entry.title,
                        "link": entry.link
                    })
            except Exception:
                pass
    except ImportError:
        # Fallback if feedparser is not installed
        try:
            for url in rss_urls:
                res = requests.get(url, timeout=3)
                if res.status_code == 200:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(res.content)
                    for item in root.findall(".//item")[:6]:
                        title = item.find("title")
                        link = item.find("link")
                        if title is not None and title.text and link is not None and link.text:
                            news_items.append({"title": title.text, "link": link.text})
        except Exception:
            pass

    if not news_items:
        news_items = [
            {"title": "Bitcoin Consolidates Above Key Support Ahead of Market Shift", "link": "#"},
            {"title": "Ethereum Staking Yields Reach New Monthly High", "link": "#"},
            {"title": "Solana Ecosystem Activity Surge Drives DEX Volume", "link": "#"},
            {"title": "Crypto Market Structure Shows Rising Institutional Interest", "link": "#"}
        ]
    return news_items

def render_sticky_dual_ticker_header(market_data, watchlist):
    """Injects a sticky dual-marquee ticker directly into Streamlit's header layer."""
    
    # 1. Price & % Change Items
    price_items_html = ""
    for sym in watchlist:
        info = market_data.get(sym, {})
        if isinstance(info, dict):
            price = info.get("price")
            pct = info.get("change_pct", 0.0)
        else:
            price = float(info) if info is not None else None
            pct = 0.0
        
        clean_sym = sym.replace("USDT", "")
        
        if price is not None:
            price_str = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
            color = "#10b981" if pct >= 0 else "#ef4444"
            sign = "+" if pct >= 0 else ""
            pct_str = f"{sign}{pct:.2f}%"
        else:
            price_str = "Loading..."
            color = "#94a3b8"
            pct_str = ""

        price_items_html += f"""
        <div style="display: inline-block; padding: 0 20px; font-weight: 600;">
            <span style="color: #94a3b8;">{clean_sym}:</span> 
            <span style="color: #f4f4f5;">{price_str}</span>
            <span style="color: {color}; font-size: 12px; margin-left: 4px;">({pct_str})</span>
        </div>
        """

    # 2. News Items
    news_items = fetch_live_crypto_news()
    news_items_html = ""
    if news_items:
        for item in news_items:
            news_items_html += f"""
            <div style="display: inline-block; padding: 0 25px; font-weight: 500;">
                <span style="color: #3b82f6; font-weight: 700;">[NEWS]</span> 
                <a href="{item['link']}" target="_blank" style="color: #cbd5e1; text-decoration: none;">
                    {item['title']}
                </a>
            </div>
            """
    else:
        news_items_html = '<div style="display: inline-block; padding: 0 20px; color: #94a3b8;">Loading latest financial news stream...</div>'

    # 3. Clean Streamlit Container Marquee Injection
    sticky_header_html = f"""
    <style>
    .ticker-container {{
        width: 100%;
        background-color: #0b0f19;
        border: 1px solid #1e293b;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        font-family: 'Inter', sans-serif;
        margin-bottom: 15px;
        overflow: hidden;
    }}
    .ticker-row {{
        width: 100%;
        overflow: hidden;
        white-space: nowrap;
        padding: 6px 0;
    }}
    .price-row {{
        background-color: #0f172a;
        font-size: 13px;
        border-bottom: 1px solid #1e293b;
    }}
    .news-row {{
        background-color: #080d1a;
        font-size: 12px;
    }}
    .marquee-content {{
        display: inline-block;
        white-space: nowrap;
        padding-left: 100%;
        animation: marquee_anim 38s linear infinite;
    }}
    .marquee-content:hover {{
        animation-play-state: paused;
    }}
    @keyframes marquee_anim {{
        0% {{ transform: translate3d(0, 0, 0); }}
        100% {{ transform: translate3d(-100%, 0, 0); }}
    }}
    </style>
    
    <div class="ticker-container">
        <div class="ticker-row price-row">
            <div class="marquee-content">{price_items_html}</div>
        </div>
        <div class="ticker-row news-row">
            <div class="marquee-content">{news_items_html}</div>
        </div>
    </div>
    """
    with st.container():
        st.markdown(sticky_header_html, unsafe_allow_html=True)
    return None

@st.cache_data(ttl=5)
def fetch_all_market_prices():
    """Fetches Binance 24h market prices and percentage changes cached for 5 seconds."""
    try:
        res = requests.get("https://api.binance.us/api/v3/ticker/24hr", timeout=3).json()
        data = {}
        for item in res:
            sym = item.get("symbol")
            price = item.get("lastPrice")
            pct = item.get("priceChangePercent")
            if sym and price is not None and pct is not None:
                data[sym] = {
                    "price": float(price),
                    "change_pct": float(pct)
                }
        return data
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

def load_portfolio(user_id=None):
    if user_id is None:
        user_id = st.session_state.get("user_id", 1)
    
    # Primary: fetch from SQLite database
    portfolio = db.get_or_create_portfolio(user_id)
    
    # Merge local state file overlay ONLY if user is Guest (user_id=1) and state file exists
    if user_id == 1 and os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                file_data = json.load(f)
                for key in ["active_positions", "closed_trades", "latest_scan_decisions", "equity_history", "bot_logs", "last_scan_time", "challenge_active", "challenge_start_time"]:
                    if key in file_data and file_data[key]:
                        portfolio[key] = file_data[key]
                if "cash_balance" in file_data and file_data["cash_balance"] is not None:
                    portfolio["cash_balance"] = file_data["cash_balance"]
                # Recalculate guest cash_balance dynamically if positions exist and cash_balance equals initial $10,000
                total_invested = sum(p.get("allocated_amount", 0.0) for p in portfolio.get("active_positions", []))
                if total_invested > 0 and portfolio.get("cash_balance", 10000.0) == 10000.0:
                    portfolio["cash_balance"] = max(0.0, 10000.0 - total_invested)
        except Exception:
            pass
            
    return portfolio

def save_portfolio(portfolio, user_id=None):
    if user_id is None:
        user_id = st.session_state.get("user_id", 1)
    
    # Save to SQLite database
    db.save_portfolio_db(user_id, portfolio)
    
    # Also save to local JSON file for background bot synchronization if user is Guest (1)
    if user_id == 1:
        temp_file = f"{STATE_FILE}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(portfolio, f, indent=4)
            os.replace(temp_file, STATE_FILE)
        except Exception:
            pass

def render_live_dashboard():
    portfolio = load_portfolio()
    market_prices = fetch_all_market_prices()
    viewer_count = track_and_get_active_viewers()

    # Ticker header disabled to preserve clean Streamlit dashboard UI
    # with st.container():
    #     render_sticky_dual_ticker_header(market_prices, WATCHLIST)

    col_title, col_btn = st.columns([0.65, 0.35])
    with col_title:
        title_col, badge_col = st.columns([0.65, 0.35])
        with title_col:
            st.title("⚡ ChartPulse AI: $10,000 Trading Hub")
        with badge_col:
            st.write("")
            render_live_viewer_badge(viewer_count)
        st.caption("v2.4.0 | Autonomous Gemini AI scanning 20 crypto assets every 60s with full technical momentum analysis.")

    is_challenge_active = portfolio.get("challenge_active", False)

    with col_btn:
        st.write("")
        if not is_challenge_active:
            if st.button("🚀 START 48-HOUR CHALLENGE", type="primary", use_container_width=True):
                new_state = {
                    "cash_balance": 10000.00,
                    "invested_amount": 0.00,
                    "active_positions": [],
                    "closed_trades": [],
                    "latest_scan_decisions": [],
                    "bot_logs": [f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 48-Hour Autonomous AI Trading Challenge Started! Balance reset to $10,000.00."],
                    "challenge_active": True,
                    "challenge_start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "equity_history": [
                        {
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "cash": 10000.00,
                            "invested": 0.00,
                            "total_equity": 10000.00
                        }
                    ]
                }
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(new_state, f, indent=4)
                
                # Trigger instant immediate market scan pass upon challenge start
                try:
                    import backend_bot
                    ui_key = None
                    if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
                        ui_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                    elif os.getenv("GEMINI_API_KEY"):
                        ui_key = os.getenv("GEMINI_API_KEY")
                    threading.Thread(target=backend_bot.run_single_scan_pass, args=(ui_key,), daemon=True).start()
                except Exception:
                    pass

                st.success("🏆 48-Hour Challenge Initiated! Initial instant market scan launched.")
                st.rerun()
        else:
            if st.button("🔴 RESET & STOP CHALLENGE", use_container_width=True):
                default_state = {
                    "cash_balance": 10000.00,
                    "invested_amount": 0.00,
                    "active_positions": [],
                    "closed_trades": [],
                    "latest_scan_decisions": [],
                    "challenge_active": False,
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

    if is_challenge_active:
        start_t = portfolio.get("challenge_start_time", "N/A")
        st.info(f"🏆 **48-HOUR CHALLENGE IS LIVE!** (Started: `{start_t}`) — Bot parameters are locked. Gemini AI is analyzing price charts, momentum indicators, and market forecasts to execute trades.")

    cash = portfolio.get("cash_balance", 10000.00)
    active_positions = portfolio.get("active_positions", [])
    closed_trades = portfolio.get("closed_trades", [])
    scan_decisions = portfolio.get("latest_scan_decisions", [])
    equity_history = portfolio.get("equity_history", [])

    # Dynamic calculation of total active market value
    active_value = 0.0
    for pos in active_positions:
        p_info = market_prices.get(pos["symbol"], pos.get("entry_price", 1.0))
        cur_price = p_info.get("price", pos.get("entry_price", 1.0)) if isinstance(p_info, dict) else float(p_info)
        qty = pos.get("allocated_amount", 0.0) / pos.get("entry_price", 1.0) if pos.get("entry_price", 0) > 0 else 0
        active_value += qty * cur_price

    total_equity = cash + active_value
    total_pnl = total_equity - 10000.00
    pnl_pct = (total_pnl / 10000.00) * 100

    # Stats Calculation reading directly from closed_trades
    wins = [t for t in closed_trades if (t.get("pnl_usd") if t.get("pnl_usd") is not None else t.get("pnl", 0)) > 0]
    win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0.0
    total_profit = sum([(t.get("pnl_usd") if t.get("pnl_usd") is not None else t.get("pnl", 0)) for t in wins]) if wins else 0.0
    losses = [t for t in closed_trades if (t.get("pnl_usd") if t.get("pnl_usd") is not None else t.get("pnl", 0)) <= 0]
    total_loss = abs(sum([(t.get("pnl_usd") if t.get("pnl_usd") is not None else t.get("pnl", 0)) for t in losses])) if losses else 0.0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else (total_profit if total_profit > 0 else 1.0)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Equity", f"${total_equity:,.2f}", f"{pnl_pct:+.2f}%")
    c2.metric("Liquid Cash", f"${cash:,.2f}")
    c3.metric("Active Investments", f"${active_value:,.2f}")
    c4.metric("Active Open Positions", len(active_positions))
    c5.metric("Win Rate / Profit Factor", f"{win_rate:.1f}%", f"PF: {profit_factor:.2f}")

    st.divider()

    tab_overview, tab_status, tab_brain, tab_history = st.tabs([
        "📊 Performance & Active Positions",
        "📡 Engine Scan Status & Logs",
        "🧠 Detailed AI Brain Analysis",
        "📜 Closed Trade History & Logs"
    ])

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
                p_raw = market_prices.get(selected_symbol, df_klines["close"].iloc[-1])
                cur_p = p_raw.get("price", df_klines["close"].iloc[-1]) if isinstance(p_raw, dict) else float(p_raw)
                entry_p = float(selected_pos.get("entry_price", 0))
                tp_p = float(selected_pos.get("take_profit", 0)) if selected_pos.get("take_profit") else None
                sl_p = float(selected_pos.get("stop_loss", 0)) if selected_pos.get("stop_loss") else None

                # Compact Inline Price & Target Summary Bar
                tp_str = f"${tp_p:,.4f}" if tp_p else "N/A"
                sl_str = f"${sl_p:,.4f}" if sl_p else "N/A"
                st.caption(f"Live: **${cur_p:,.4f}** | Entry: **${entry_p:,.4f}** | TP Goal: **{tp_str}** | SL Target: **{sl_str}**")

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
                    annotation_text=f" CURRENT PRICE: ${cur_p:,.4f} ",
                    annotation_position="top left", annotation_font_color="#000000", annotation_bgcolor="#facc15"
                )

                # 🟢 TAKE PROFIT LINE (Green)
                if tp_p:
                    fig_clean.add_hline(
                        y=tp_p, line_dash="solid", line_color="#10b981", line_width=2.5,
                        annotation_text=f" TAKE PROFIT GOAL: ${tp_p:,.4f} ",
                        annotation_position="top right", annotation_font_color="#ffffff", annotation_bgcolor="#10b981"
                    )

                # 🔵 BUY ENTRY LINE (Blue)
                if entry_p > 0:
                    fig_clean.add_hline(
                        y=entry_p, line_dash="dash", line_color="#3b82f6", line_width=2,
                        annotation_text=f" BUY ENTRY: ${entry_p:,.4f} ",
                        annotation_position="bottom right", annotation_font_color="#ffffff", annotation_bgcolor="#3b82f6"
                    )

                # 🔴 STOP LOSS LINE (Red)
                if sl_p:
                    fig_clean.add_hline(
                        y=sl_p, line_dash="solid", line_color="#ef4444", line_width=2.5,
                        annotation_text=f" STOP LOSS TARGET: ${sl_p:,.4f} ",
                        annotation_position="bottom right", annotation_font_color="#ffffff", annotation_bgcolor="#ef4444"
                    )

                # 🟡 LIVE CURRENT PRICE BADGE (Yellow Marker at end)
                fig_clean.add_trace(
                    go.Scatter(
                        x=[df_klines["open_time"].iloc[-1]],
                        y=[cur_p],
                        mode="markers+text",
                        marker=dict(color="#facc15", size=14, symbol="circle"),
                        text=[f"  NOW: ${cur_p:,.4f}"],
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
                    margin=dict(l=40, r=140, t=30, b=30),
                    showlegend=False
                )
                fig_clean.update_yaxes(range=[min_y, max_y], gridcolor="#1e293b", tickformat="$,.2f", automargin=False)
                fig_clean.update_xaxes(gridcolor="#1e293b", automargin=False)

            else:
                st.warning(f"Could not load live chart data for {selected_symbol}.")

            # Compact Positions Summary List with AI Rationale Expanders
            st.write("---")
            st.subheader("📋 Active Open Positions & Instant Actions")
            for p in active_positions:
                sym = p.get("symbol", "N/A")
                p_info = market_prices.get(sym, p.get("entry_price", 0.0))
                cur = p_info.get("price", p.get("entry_price", 0.0)) if isinstance(p_info, dict) else float(p_info)
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
                    c_det1, c_det2, c_det3 = st.columns([0.45, 0.35, 0.20])
                    with c_det1:
                        st.caption(f"Entry: `${entry_p:,.4f}` | Live: `${cur:,.4f}` | Value: `${cur_val:,.2f}` (${allocated:,.2f})")
                    with c_det2:
                        st.caption(f"TP: `${tp_val:,.4f}` | SL: `${sl_val:,.4f}` | Time: `{time_bought}`")
                    with c_det3:
                        confirm_sell_item = st.checkbox("Confirm", key=f"confirm_list_{sym}")
                        if st.button(f"🔴 SELL", key=f"sell_btn_{sym}", type="primary", use_container_width=True):
                            if not confirm_sell_item:
                                st.warning("Check 'Confirm' first!")
                            else:
                                active_u_id = st.session_state.get("user_id", 1)
                                updated_p, closed_rec = db.execute_position_exit(active_u_id, sym, cur, exit_reason="MANUAL_SELL_NOW", rationale=rationale_text)
                                if updated_p:
                                    portfolio.update(updated_p)
                                
                                if active_u_id == 1:
                                    temp_file = f"{STATE_FILE}.tmp"
                                    try:
                                        with open(temp_file, "w", encoding="utf-8") as f:
                                            json.dump(portfolio, f, indent=4)
                                        os.replace(temp_file, STATE_FILE)
                                    except Exception:
                                        pass

                                pnl = closed_rec["pnl_usd"] if closed_rec else unrealized_pnl
                                pnl_pct = closed_rec["pnl_pct"] if closed_rec else unrealized_pct
                                st.success(f"🎉 Closed {sym} at ${cur:,.4f} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)")
                                st.rerun()
                    
                    st.caption(f"🧠 **AI Rationale:** {rationale_text}")

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

    with tab_status:
        st.subheader("📡 Background Trading Engine Status & Real-Time Logs")
        st.caption("Live status stream showing exact backend operations, Binance market fetches, Gemini model calls, and failover health.")
        
        last_scan = portfolio.get("last_scan_time", "N/A")
        bot_logs = portfolio.get("bot_logs", [])

        # Calculate target timestamp for live JS ticking timer
        import time as _time
        seconds_left = 60
        target_timestamp_ms = int((_time.time() + 60) * 1000)
        if last_scan != "N/A":
            try:
                last_dt = datetime.strptime(last_scan, "%Y-%m-%d %H:%M:%S")
                elapsed = (_time.time() - last_dt.timestamp())
                rem = max(0, int(60 - (elapsed % 60)))
                target_timestamp_ms = int((_time.time() + rem) * 1000)
                seconds_left = rem
            except Exception:
                pass

        # Calculate engine status based on active thread or recent log events
        import time as _time
        is_engine_active = False
        
        # Check thread status
        active_thread = next((t for t in threading.enumerate() if t.name == "ChartPulseBackendThread"), None)
        if active_thread and active_thread.is_alive():
            is_engine_active = True
        elif last_scan != "N/A":
            try:
                last_dt = datetime.strptime(last_scan, "%Y-%m-%d %H:%M:%S")
                elapsed_since_scan = (_time.time() - last_dt.timestamp())
                if elapsed_since_scan <= 300: # Within last 5 mins
                    is_engine_active = True
            except Exception:
                is_engine_active = False

        s_col1, s_col2, s_col3, s_col4 = st.columns(4)
        with s_col1:
            with st.container(border=True):
                st.caption("ENGINE HEALTH")
                if is_engine_active:
                    st.markdown("### 🟢 ONLINE")
                    st.caption("Active Scanner Thread")
                else:
                    st.markdown("### 🟡 INITIALIZING")
                    st.caption("Starting Scanner Thread")
        with s_col2:
            with st.container(border=True):
                st.caption("LAST SCAN TIME")
                st.markdown(f"### {last_scan.split()[-1] if ' ' in last_scan else last_scan}")
                st.caption(f"Date: {last_scan.split()[0] if ' ' in last_scan else 'Today'}")
        with s_col3:
            with st.container(border=True):
                st.caption("NEXT SCAN IN")
                # Live HTML/JS Ticking Countdown Component
                countdown_html = f"""
                <div style="font-family: sans-serif; text-align: left; background: transparent; color: white;">
                    <div id="countdown" style="font-size: 24px; font-weight: bold; color: #facc15;">⏳ {seconds_left}s</div>
                </div>
                <script>
                    var targetTime = {target_timestamp_ms};
                    var x = setInterval(function() {{
                        var now = new Date().getTime();
                        var distance = Math.max(0, Math.floor((targetTime - now) / 1000));
                        var el = document.getElementById("countdown");
                        if (el) {{
                            if (distance <= 0) {{
                                el.innerHTML = "⚡ SCANNING NOW...";
                                el.style.color = "#10b981";
                            }} else {{
                                el.innerHTML = "⏳ " + distance + "s";
                            }}
                        }}
                    }}, 1000);
                </script>
                """
                st.components.v1.html(countdown_html, height=45)
                st.caption("Cycle Interval: 60s")
        with s_col4:
            with st.container(border=True):
                st.caption("ACTIVITY LOGS")
                st.markdown(f"### {len(bot_logs)} Events")
                st.caption("Retention: 50 Entries")

        # Filter logs for errors and warnings
        error_logs = [log for log in bot_logs if ("❌" in log or "⚠️" in log or "Error" in log or "429" in log or "404" in log)]

        if error_logs:
            st.markdown("### 🚨 Backend Exception & Error Alerts")
            for err_item in error_logs[:5]:
                if "❌" in err_item or "Error" in err_item:
                    st.error(err_item)
                else:
                    st.warning(err_item)

        st.markdown("### 🖥️ Real-Time Engine Operations Console")
        r_col1, r_col2 = st.columns([0.65, 0.35])
        with r_col1:
            if st.button("⚡ FORCE INSTANT SCAN PASS NOW", type="secondary", use_container_width=True):
                try:
                    import backend_bot
                    ui_key = None
                    if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
                        ui_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                    elif os.getenv("GEMINI_API_KEY"):
                        ui_key = os.getenv("GEMINI_API_KEY")
                    
                    threading.Thread(target=backend_bot.run_single_scan_pass, args=(ui_key,), daemon=True).start()
                    st.toast("🚀 Instant market scan pass triggered! Updating logs...", icon="⚡")
                except Exception as e:
                    st.error(f"Scan trigger error: {e}")
        with r_col2:
            if st.button("🗑️ RESET ALL CLOUD DATA", type="primary", use_container_width=True):
                clean_state = {
                    "cash_balance": 10000.00,
                    "invested_amount": 0.00,
                    "active_positions": [],
                    "closed_trades": [],
                    "latest_scan_decisions": [],
                    "bot_logs": [f"[{datetime.now().strftime('%H:%M:%S')}] 🧹 Cloud portfolio state wiped clean."],
                    "last_scan_time": "N/A",
                    "challenge_active": False
                }
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(clean_state, f, indent=4)
                st.toast("🧹 Cloud storage reset! Refreshing...", icon="🧹")
                st.rerun()
        if bot_logs:
            log_box_content = "\n".join(bot_logs)
            st.code(log_box_content, language="text")
        else:
            st.info("Initializing engine console logs... Initial scan cycle in progress.")

        with st.expander("📡 Raw Backend Live Telemetry & API Payload Feed", expanded=False):
            st.caption("Direct raw inspection of backend JSON state payload, Gemini stream text, and engine parameters.")
            st.json({
                "last_scan_timestamp": last_scan,
                "total_logged_events": len(bot_logs),
                "latest_raw_signals": portfolio.get("latest_scan_decisions", []),
                "recent_raw_log_stream": bot_logs[:10]
            })

        with st.expander("📄 Persistent Error Log File (error_log.txt)", expanded=True if error_logs else False):
            st.caption("Full persistent error log history saved to disk with exact dates and timestamps.")
            if os.path.exists("error_log.txt"):
                try:
                    with open("error_log.txt", "r", encoding="utf-8") as ef:
                        err_content = ef.read()
                    if err_content.strip():
                        st.code(err_content, language="text")
                    else:
                        st.info("No persistent errors recorded in error_log.txt.")
                except Exception as e:
                    st.error(f"Could not read error_log.txt: {e}")
            else:
                st.info("error_log.txt file not created yet (no errors encountered).")

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
st.sidebar.caption("ChartPulse AI v2.4.0 Pro")

# --- User Authentication Sidebar Section ---
if "user_id" not in st.session_state:
    st.session_state["user_id"] = 1

active_uid = st.session_state["user_id"]
active_uname = db.get_username(active_uid)

with st.sidebar.expander("👤 User Account & Authentication", expanded=(active_uid == 1)):
    if active_uid != 1:
        st.success(f"Logged in as: **{active_uname}**")
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state["user_id"] = 1
            st.toast("Logged out. Continuing as Guest.", icon="👋")
            st.rerun()
    else:
        st.info("Currently viewing as **Guest** (Default Account)")
        auth_mode = st.radio("Account Action:", ["Login", "Sign Up"], horizontal=True)
        
        if auth_mode == "Login":
            login_user = st.text_input("Username", key="auth_login_user")
            login_pwd = st.text_input("Password", type="password", key="auth_login_pwd")
            if st.button("🔑 Log In", type="primary", use_container_width=True):
                if login_user and login_pwd:
                    res = db.authenticate_user(login_user.strip(), login_pwd)
                    if res:
                        u_id, u_name = res
                        st.session_state["user_id"] = u_id
                        st.toast(f"Welcome back, {u_name}!", icon="🎉")
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")
                else:
                    st.warning("Please enter username and password.")
        else: # Sign Up
            signup_user = st.text_input("Username", key="signup_user")
            signup_pwd = st.text_input("Password", type="password", key="signup_pass")
            if st.button("📝 Register Account", type="primary", use_container_width=True):
                if signup_user and signup_pwd:
                    user_id = db.register_user(signup_user.strip(), signup_pwd)
                    if user_id:
                        st.session_state["user_id"] = user_id
                        st.session_state["username"] = signup_user.strip()
                        st.success("Account created successfully!")
                        st.toast(f"Account created! Welcome, {signup_user.strip()}!", icon="🚀")
                        st.rerun()
                    else:
                        st.error("Username already exists or registration failed.")
                else:
                    st.warning("Please fill in all registration fields.")

if st.sidebar.button("🔄 Sync & Refresh UI", use_container_width=True):
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("🎛️ AI Bot Criteria Sliders")

# Read current portfolio settings
portfolio_data = load_portfolio()
is_challenge_active = portfolio_data.get("challenge_active", False)

cur_settings = portfolio_data.get("bot_settings", {
    "min_confidence": 75,
    "take_profit_pct": 4.0,
    "stop_loss_pct": 2.0,
    "max_positions": 5,
    "max_trade_size": 3000.0,
    "bot_attitude": "Balanced",
    "strategy": "Scalping"
})

if is_challenge_active:
    st.sidebar.warning("🔒 48-Hour Challenge Active: Criteria Sliders & Strategy Locked.")

attitude_val = st.sidebar.selectbox(
    "🎭 Bot Attitude",
    options=["Aggressive", "Balanced", "Conservative"],
    index=["Aggressive", "Balanced", "Conservative"].index(cur_settings.get("bot_attitude", "Balanced")),
    disabled=is_challenge_active,
    help="Controls AI conviction threshold and trade entry aggressiveness."
)

strategy_val = st.sidebar.selectbox(
    "📐 Execution Strategy",
    options=["Scalping", "Trend Following"],
    index=["Scalping", "Trend Following"].index(cur_settings.get("strategy", "Scalping")),
    disabled=is_challenge_active,
    help="Determines target profit margins and holding style."
)

min_conf_val = st.sidebar.slider(
    "🎯 Min Confidence Threshold (%)",
    min_value=50, max_value=95,
    value=int(cur_settings.get("min_confidence", 75)),
    step=5,
    disabled=is_challenge_active,
    help="Minimum AI confidence required to execute a paper buy order."
)

tp_pct_val = st.sidebar.slider(
    "🟢 Take Profit Target (+%)",
    min_value=1.0, max_value=15.0,
    value=float(cur_settings.get("take_profit_pct", 4.0)),
    step=0.5,
    disabled=is_challenge_active,
    help="Target gain percentage to trigger automatic Take Profit exit."
)

sl_pct_val = st.sidebar.slider(
    "🔴 Stop Loss Protection (-%)",
    min_value=0.5, max_value=10.0,
    value=float(cur_settings.get("stop_loss_pct", 2.0)),
    step=0.5,
    disabled=is_challenge_active,
    help="Maximum loss percentage before automatic Stop Loss exit."
)

max_pos_val = st.sidebar.slider(
    "📊 Max Open Positions",
    min_value=1, max_value=10,
    value=int(cur_settings.get("max_positions", 5)),
    step=1,
    disabled=is_challenge_active,
    help="Maximum number of simultaneous active positions allowed."
)

max_trade_val = st.sidebar.slider(
    "💰 Max Trade Allocation ($)",
    min_value=500.0, max_value=5000.0,
    value=float(cur_settings.get("max_trade_size", 3000.0)),
    step=250.0,
    disabled=is_challenge_active,
    help="Maximum dollar amount allocated per paper trade."
)

# Save settings if changed (only when challenge is not active)
if not is_challenge_active:
    new_settings = {
        "min_confidence": min_conf_val,
        "take_profit_pct": tp_pct_val,
        "stop_loss_pct": sl_pct_val,
        "max_positions": max_pos_val,
        "max_trade_size": max_trade_val,
        "bot_attitude": attitude_val,
        "strategy": strategy_val
    }

    if new_settings != cur_settings:
        portfolio_data["bot_settings"] = new_settings
        try:
            save_portfolio(portfolio_data)
            st.sidebar.success("✅ Settings Saved!")
        except Exception as e:
            st.sidebar.error(f"Error saving settings: {e}")

st.sidebar.divider()
st.sidebar.markdown("**Active Engine Status:**")
st.sidebar.write("• Watchlist: 20 Assets")
st.sidebar.write("• Mode: Autonomous Gemini AI Deep Analysis")
st.sidebar.write(f"• Criteria: {'🔒 LOCKED (48h Challenge)' if is_challenge_active else '✏️ Customizable'}")

render_live_dashboard()
