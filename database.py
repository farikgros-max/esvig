import json
import sqlite3
from datetime import datetime
from typing import Any

DB_PATH = "bot.db"


def _connect():
    return sqlite3.connect(DB_PATH)


def _table_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _channel_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "category_id": row[1],
        "name": row[2],
        "url": row[3],
        "subscribers": row[4],
        "price": row[5],
        "description": row[6] or "",
    }


def _order_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    items_raw = row[3] or "[]"
    try:
        cart = json.loads(items_raw)
    except Exception:
        cart = []

    return {
        "id": row[0],
        "user_id": row[1],
        "username": row[2],
        "cart": cart,
        "items": cart,
        "total": row[4],
        "budget": row[5],
        "contact": row[6],
        "status": row[7],
        "created_at": row[8],
    }


async def init_db():
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0,
        daily_limit INTEGER DEFAULT 5,
        daily_used INTEGER DEFAULT 0,
        last_reset TEXT
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER,
        name TEXT,
        url TEXT,
        subscribers INTEGER DEFAULT 0,
        price REAL DEFAULT 0,
        description TEXT
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        display_name TEXT
    )
    """
    )

    cur.execute(
        """
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
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS balance_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        description TEXT,
        created_at TEXT
    )
    """
    )

    category_cols = _table_columns(cur, "categories")
    if "display_name" not in category_cols:
        cur.execute("ALTER TABLE categories ADD COLUMN display_name TEXT")
        cur.execute("UPDATE categories SET display_name = name WHERE display_name IS NULL")

    conn.commit()
    conn.close()


async def get_or_create_user(user_id: int, username: str = None):
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id, username, balance, daily_limit, daily_used, last_reset FROM users WHERE user_id=?",
        (user_id,),
    )
    row = cur.fetchone()

    if not row:
        now = str(datetime.now())
        cur.execute(
            """
            INSERT INTO users (user_id, username, balance, daily_limit, daily_used, last_reset)
            VALUES (?, ?, 0, 5, 0, ?)
            """,
            (user_id, username, now),
        )
        conn.commit()
        row = (user_id, username, 0, 5, 0, now)

    conn.close()
    return {
        "user_id": row[0],
        "username": row[1],
        "balance": row[2],
        "daily_limit": row[3],
        "daily_used": row[4],
        "last_reset": row[5],
    }


async def get_user_balance(user_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


async def update_user_balance(user_id: int, amount: float, description: str = ""):
    await get_or_create_user(user_id)
    conn = _connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    cur.execute(
        """
        INSERT INTO balance_log (user_id, amount, description, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, amount, description or "Пополнение/изменение баланса", str(datetime.now())),
    )
    conn.commit()
    conn.close()


async def update_balance(user_id: int, amount: float):
    await update_user_balance(user_id, amount, "Пополнение через платежный шлюз")


async def debit_balance(user_id: int, amount: float, order_id=None, description=""):
    conn = _connect()
    cur = conn.cursor()

    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    bal = cur.fetchone()
    if not bal or bal[0] < amount:
        conn.close()
        return False

    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
    note = description or (f"Оплата заказа #{order_id}" if order_id else "Списание")
    cur.execute(
        """
        INSERT INTO balance_log (user_id, amount, description, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, -amount, note, str(datetime.now())),
    )

    conn.commit()
    conn.close()
    return True


async def check_daily_order_limit(user_id: int):
    conn = _connect()
    cur = conn.cursor()

    cur.execute("SELECT daily_used, daily_limit FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return True

    used, limit = row

    if used >= limit:
        conn.close()
        return False

    cur.execute("UPDATE users SET daily_used = daily_used + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return True


async def get_user_daily_info(user_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT daily_used, daily_limit FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"used": 0, "limit": 5}
    return {"used": row[0], "limit": row[1]}


async def get_channels(category_id: int = None):
    conn = _connect()
    cur = conn.cursor()

    if category_id:
        cur.execute("SELECT * FROM channels WHERE category_id=? ORDER BY id DESC", (category_id,))
    else:
        cur.execute("SELECT * FROM channels ORDER BY id DESC")

    rows = cur.fetchall()
    conn.close()

    result = {}
    for r in rows:
        channel = _channel_from_row(r)
        result[str(channel["id"])] = channel
    return result


get_all_channels = get_channels


async def get_channel(channel_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM channels WHERE id=?", (channel_id,))
    r = cur.fetchone()
    conn.close()
    return _channel_from_row(r) if r else None


async def add_channel(_external_id, name, price, subscribers, url, description, category_id=None):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO channels (category_id, name, url, subscribers, price, description)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (category_id, name, url, int(subscribers or 0), float(price or 0), description or ""),
    )
    conn.commit()
    inserted_id = cur.lastrowid
    conn.close()
    return inserted_id


async def delete_channel(channel_id):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM channels WHERE id=?", (int(channel_id),))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted > 0


async def update_channel(channel_id, **kwargs):
    field_map = {
        "name": "name",
        "price": "price",
        "subs": "subscribers",
        "subscribers": "subscribers",
        "url": "url",
        "desc": "description",
        "description": "description",
        "category_id": "category_id",
    }
    updates = []
    values = []

    for key, value in kwargs.items():
        db_field = field_map.get(key)
        if not db_field:
            continue
        updates.append(f"{db_field} = ?")
        values.append(value)

    if not updates:
        return False

    values.append(int(channel_id))

    conn = _connect()
    cur = conn.cursor()
    cur.execute(f"UPDATE channels SET {', '.join(updates)} WHERE id = ?", tuple(values))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return changed > 0


async def get_all_categories():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id, name, COALESCE(display_name, name) FROM categories ORDER BY id")
    rows = cur.fetchall()
    conn.close()

    return [{"id": r[0], "name": r[1], "display_name": r[2]} for r in rows]


get_categories = get_all_categories


async def add_category(name: str, display_name: str):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO categories (name, display_name) VALUES (?, ?)",
        (name.strip(), display_name.strip()),
    )
    conn.commit()
    inserted_id = cur.lastrowid
    conn.close()
    return inserted_id


async def delete_category(cat_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted > 0


async def get_category_by_id(cat_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id, name, COALESCE(display_name, name) FROM categories WHERE id=?", (cat_id,))
    r = cur.fetchone()
    conn.close()

    if not r:
        return None

    return {"id": r[0], "name": r[1], "display_name": r[2]}


async def save_order(user_id, username, cart, total, budget, contact, status="new"):
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO orders (user_id, username, items, total, budget, contact, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            json.dumps(cart, ensure_ascii=False),
            total,
            budget,
            contact,
            status,
            str(datetime.now()),
        ),
    )

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
    return [_order_from_row(r) for r in rows]


async def get_orders(limit: int | None = None):
    conn = _connect()
    cur = conn.cursor()
    if limit:
        cur.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (int(limit),))
    else:
        cur.execute("SELECT * FROM orders ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return [_order_from_row(r) for r in rows]


async def clear_all_orders():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM orders")
    conn.commit()
    conn.close()
    return True


async def clear_non_successful_orders():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM orders WHERE status IN ('в обработке', 'отменена')")
    conn.commit()
    conn.close()
    return True


async def get_order_by_id(order_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    r = cur.fetchone()
    conn.close()
    return _order_from_row(r) if r else None


async def update_order_status(order_id: int, status: str):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    conn.commit()
    conn.close()


async def return_balance(user_id: int, amount: float, order_id=None, description=""):
    note = description or (f"Возврат за заказ #{order_id}" if order_id else "Возврат")
    await update_user_balance(user_id, amount, note)
    return True
