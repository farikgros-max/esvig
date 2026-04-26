import sqlite3
import asyncio
from datetime import datetime, date

DB_PATH = "bot.db"

# ---------------- DB CORE ----------------

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


async def init_db():
    conn = _connect()
    cur = conn.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0,
        daily_limit INTEGER DEFAULT 5,
        orders_today INTEGER DEFAULT 0,
        last_order_date TEXT
    )
    """)

    # CHANNELS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER,
        name TEXT,
        url TEXT,
        price REAL,
        subscribers INTEGER DEFAULT 0,
        description TEXT
    )
    """)

    # CATEGORIES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT
    )
    """)

    # ORDERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        items TEXT,
        total REAL,
        budget REAL,
        contact TEXT,
        status TEXT,
        created_at TEXT
    )
    """)

    # BALANCE LOGS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS balance_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        description TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


# ---------------- USERS ----------------

async def get_or_create_user(user_id: int, username: str = None):
    conn = _connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()

    if not user:
        cur.execute("""
        INSERT INTO users (user_id, username, balance, daily_limit, orders_today, last_order_date)
        VALUES (?, ?, 0, 5, 0, ?)
        """, (user_id, username, str(date.today())))
        conn.commit()

        cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user = cur.fetchone()

    conn.close()
    return dict(user)


async def get_user_balance(user_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["balance"] if row else 0


async def update_user_balance(user_id: int, amount: float):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()


async def debit_balance(user_id: int, amount: float, order_id: int = None, description: str = ""):
    conn = _connect()
    cur = conn.cursor()

    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()

    if not row or row["balance"] < amount:
        conn.close()
        return False

    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))

    cur.execute("""
        INSERT INTO balance_logs (user_id, amount, description, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, -amount, description, str(datetime.now())))

    conn.commit()
    conn.close()
    return True


# ---------------- ORDERS ----------------

async def save_order(user_id, username, items, total, budget, contact, status="pending"):
    conn = _connect()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders (user_id, username, items, total, budget, contact, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        username,
        str(items),
        total,
        budget,
        contact,
        status,
        str(datetime.now())
    ))

    conn.commit()
    order_id = cur.lastrowid
    conn.close()
    return order_id


async def get_orders_by_user(user_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


async def get_order_by_id(order_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


async def update_order_status(order_id: int, status: str):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    conn.commit()
    conn.close()


async def return_balance(user_id: int, amount: float):
    await update_user_balance(user_id, amount)


# ---------------- DAILY LIMIT ----------------

async def check_daily_order_limit(user_id: int):
    conn = _connect()
    cur = conn.cursor()

    cur.execute("SELECT orders_today, last_order_date FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return True

    today = str(date.today())

    if row["last_order_date"] != today:
        cur.execute("""
            UPDATE users
            SET orders_today = 0,
                last_order_date = ?
            WHERE user_id=?
        """, (today, user_id))
        conn.commit()

    cur.execute("SELECT daily_limit, orders_today FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()

    conn.close()
    return row["orders_today"] < row["daily_limit"]


# ---------------- CATEGORIES ----------------

async def get_all_categories():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM categories")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


async def get_category_by_id(cat_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM categories WHERE id=?", (cat_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------- CHANNELS ----------------

async def get_channels(category_id: int = None):
    conn = _connect()
    cur = conn.cursor()

    if category_id:
        cur.execute("SELECT * FROM channels WHERE category_id=?", (category_id,))
    else:
        cur.execute("SELECT * FROM channels")

    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


async def get_all_channels(category_id: int = None):
    return await get_channels(category_id)


async def get_channel(channel_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM channels WHERE id=?", (channel_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


async def add_channel(category_id, name, url, price, subscribers=0, description=""):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO channels (category_id, name, url, price, subscribers, description)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (category_id, name, url, price, subscribers, description))
    conn.commit()
    conn.close()


async def delete_channel(channel_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM channels WHERE id=?", (channel_id,))
    conn.commit()
    conn.close()


async def update_channel(channel_id: int, **kwargs):
    conn = _connect()
    cur = conn.cursor()

    fields = ", ".join([f"{k}=?" for k in kwargs])
    values = list(kwargs.values())
    values.append(channel_id)

    cur.execute(f"UPDATE channels SET {fields} WHERE id=?", values)

    conn.commit()
    conn.close()


# ---------------- ADMIN HELPERS ----------------

async def get_orders():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


async def clear_non_successful_orders():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM orders WHERE status!='оплачена'")
    conn.commit()
    conn.close()
