import sqlite3
import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "app_data.db")

def get_connection():
    """Returns a SQLite connection to app_data.db."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema if tables do not exist."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolios (
            user_id INTEGER PRIMARY KEY,
            cash_balance REAL DEFAULT 10000.0,
            active_positions TEXT DEFAULT '[]',
            closed_trades TEXT DEFAULT '[]',
            bot_settings TEXT DEFAULT '{}',
            last_scan_time TEXT DEFAULT 'N/A',
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT NOT NULL,
            entry_price REAL,
            exit_price REAL,
            quantity REAL,
            allocated_amount REAL,
            exit_value REAL,
            pnl_usd REAL,
            pnl_pct REAL,
            exit_reason TEXT,
            rationale TEXT,
            timestamp TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
    conn.commit()
    conn.close()

def get_or_create_portfolio(user_id):
    """Fetches portfolio dictionary for a user, or creates default $10,000 state if new."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM portfolios WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    default_state = {
        "user_id": user_id,
        "cash_balance": 10000.00,
        "invested_amount": 0.00,
        "active_positions": [],
        "closed_trades": [],
        "latest_scan_decisions": [],
        "equity_history": [],
        "bot_settings": {},
        "last_scan_time": "N/A"
    }

    if row:
        try:
            active_positions = json.loads(row["active_positions"]) if row["active_positions"] else []
            closed_trades = json.loads(row["closed_trades"]) if row["closed_trades"] else []
            bot_settings = json.loads(row["bot_settings"]) if row["bot_settings"] else {}
            
            # Calculate invested_amount dynamically
            invested = sum(p.get("allocated_amount", 0.0) for p in active_positions)
            
            result = {
                "user_id": row["user_id"],
                "cash_balance": float(row["cash_balance"]),
                "invested_amount": float(invested),
                "active_positions": active_positions,
                "closed_trades": closed_trades,
                "bot_settings": bot_settings,
                "last_scan_time": row["last_scan_time"] or "N/A",
                "latest_scan_decisions": [],
                "equity_history": []
            }
            conn.close()
            return result
        except Exception:
            pass

    # Create default entry if not found
    cursor.execute("""
        INSERT OR REPLACE INTO portfolios (user_id, cash_balance, active_positions, closed_trades, bot_settings, last_scan_time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        default_state["cash_balance"],
        json.dumps(default_state["active_positions"]),
        json.dumps(default_state["closed_trades"]),
        json.dumps(default_state["bot_settings"]),
        default_state["last_scan_time"]
    ))
    conn.commit()
    conn.close()
    
    return default_state

def save_portfolio_db(user_id, portfolio_dict):
    """Updates the user's row in SQLite safely using JSON string dumps."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
    cash = float(portfolio_dict.get("cash_balance", 10000.00))
    positions_json = json.dumps(portfolio_dict.get("active_positions", []))
    trades_json = json.dumps(portfolio_dict.get("closed_trades", []))
    settings_json = json.dumps(portfolio_dict.get("bot_settings", {}))
    last_scan = portfolio_dict.get("last_scan_time", "N/A")
    
    cursor.execute("""
        INSERT OR REPLACE INTO portfolios (user_id, cash_balance, active_positions, closed_trades, bot_settings, last_scan_time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, cash, positions_json, trades_json, settings_json, last_scan))
    
    conn.commit()
    conn.close()

def execute_position_exit(user_id, symbol, exit_price, exit_reason="MANUAL_SELL", rationale=""):
    """
    Unified position exit execution logic:
    - Calculates PnL
    - Constructs closed trade record
    - Inserts into trades table
    - Updates portfolio cash balance and active positions in SQLite
    - Returns updated portfolio dictionary and closed_record
    """
    init_db()
    portfolio = get_or_create_portfolio(user_id)
    active_positions = portfolio.get("active_positions", [])
    pos = next((p for p in active_positions if p.get("symbol") == symbol), None)
    
    if not pos:
        return portfolio, None

    entry_price = float(pos.get("entry_price", 1.0))
    alloc = float(pos.get("allocated_amount", 0.0))
    qty = float(pos.get("quantity")) if pos.get("quantity") is not None else (alloc / entry_price if entry_price > 0 else 0.0)
    
    exit_value = qty * float(exit_price)
    pnl_usd = (float(exit_price) - entry_price) * qty
    pnl_pct = ((float(exit_price) - entry_price) / entry_price) * 100 if entry_price > 0 else 0.0
    
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rat_str = rationale or pos.get("rationale", "")

    closed_record = {
        "symbol": symbol,
        "entry_price": entry_price,
        "exit_price": float(exit_price),
        "quantity": qty,
        "allocated_amount": alloc,
        "exit_value": exit_value,
        "pnl": pnl_usd,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "exit_reason": exit_reason,
        "close_reason": exit_reason,
        "rationale": rat_str,
        "timestamp": timestamp_str
    }

    # Update portfolio dict state
    portfolio["cash_balance"] = portfolio.get("cash_balance", 10000.0) + exit_value
    portfolio["invested_amount"] = max(0.0, portfolio.get("invested_amount", 0.0) - alloc)
    portfolio["active_positions"] = [p for p in active_positions if p.get("symbol") != symbol]
    
    if "closed_trades" not in portfolio:
        portfolio["closed_trades"] = []
    portfolio["closed_trades"].insert(0, closed_record)

    # Save portfolio update
    save_portfolio_db(user_id, portfolio)

    # Record in SQL trades table
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trades (user_id, symbol, entry_price, exit_price, quantity, allocated_amount, exit_value, pnl_usd, pnl_pct, exit_reason, rationale, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, symbol, entry_price, float(exit_price), qty, alloc, exit_value, pnl_usd, pnl_pct, exit_reason, rat_str, timestamp_str))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Error recording trade into trades table: {e}")

    return portfolio, closed_record

def register_user(username, password):
    """Registers a new user and returns user_id, or None if username already exists."""
    import hashlib
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
    pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    try:
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pwd_hash))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        # Initialize default portfolio for new user
        get_or_create_portfolio(user_id)
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None
    except Exception:
        conn.close()
        return None

def authenticate_user(username, password):
    """Authenticates username and password, returning (user_id, username) tuple or None."""
    import hashlib
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
    pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    cursor.execute("SELECT id, username FROM users WHERE username = ? AND password_hash = ?", (username, pwd_hash))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return row["id"], row["username"]
    return None

def get_username(user_id):
    """Returns username for a given user_id or Guest."""
    if user_id == 1:
        return "Guest"
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
def get_all_users():
    """Returns a list of all user IDs from SQLite, ensuring default guest user_id 1 is included."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users")
    rows = cursor.fetchall()
    conn.close()
    
    user_ids = set([row["id"] for row in rows])
    user_ids.add(1) # Ensure Guest ID 1 is always included
    return sorted(list(user_ids))

if __name__ == "__main__":
    init_db()
    print(get_or_create_portfolio(1))
