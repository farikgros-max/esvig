import sqlite3
import json

DB_NAME = 'channels.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            subscribers INTEGER NOT NULL,
            url TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT ''
        )
    ''')
    c.execute("PRAGMA table_info(channels)")
    cols = [col[1] for col in c.fetchall()]
    if 'category' not in cols:
        c.execute('ALTER TABLE channels ADD COLUMN category TEXT DEFAULT ""')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            cart TEXT,
            total INTEGER,
            budget INTEGER,
            contact TEXT,
            status TEXT DEFAULT 'в обработке',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute("PRAGMA table_info(orders)")
    cols = [col[1] for col in c.fetchall()]
    if 'status' not in cols:
        c.execute('ALTER TABLE orders ADD COLUMN status TEXT DEFAULT "в обработке"')
    conn.commit()
    conn.close()

def get_all_channels(category=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if category:
        c.execute('SELECT id, name, price, subscribers, url, description, category FROM channels WHERE category = ?', (category,))
    else:
        c.execute('SELECT id, name, price, subscribers, url, description, category FROM channels')
    rows = c.fetchall()
    ch = {}
    for r in rows:
        ch[r[0]] = {
            "name": r[1],
            "price": r[2],
            "subscribers": r[3],
            "url": r[4],
            "description": r[5] or "",
            "category": r[6] or ""
        }
    conn.close()
    return ch

def add_channel(ch_id, name, price, subscribers, url, desc="", category=""):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO channels (id, name, price, subscribers, url, description, category)
        VALUES (?,?,?,?,?,?,?)
    ''', (ch_id, name, price, subscribers, url, desc, category))
    conn.commit()
    conn.close()

def update_channel(ch_id, name=None, price=None, subs=None, url=None, desc=None, category=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if name is not None: c.execute('UPDATE channels SET name = ? WHERE id = ?', (name, ch_id))
    if price is not None: c.execute('UPDATE channels SET price = ? WHERE id = ?', (price, ch_id))
    if subs is not None: c.execute('UPDATE channels SET subscribers = ? WHERE id = ?', (subs, ch_id))
    if url is not None: c.execute('UPDATE channels SET url = ? WHERE id = ?', (url, ch_id))
    if desc is not None: c.execute('UPDATE channels SET description = ? WHERE id = ?', (desc, ch_id))
    if category is not None: c.execute('UPDATE channels SET category = ? WHERE id = ?', (category, ch_id))
    conn.commit()
    conn.close()

def delete_channel(ch_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM channels WHERE id = ?', (ch_id,))
    conn.commit()
    conn.close()

# Функции для заказов (без изменений)
def save_order(user_id, username, cart, total, budget, contact, status='в обработке'):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    cart_json = json.dumps(cart)
    c.execute('INSERT INTO orders (user_id, username, cart, total, budget, contact, status) VALUES (?,?,?,?,?,?,?)',
              (user_id, username, cart_json, total, budget, contact, status))
    oid = c.lastrowid
    conn.commit()
    conn.close()
    return oid

def get_orders(limit=20):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, user_id, username, cart, total, budget, contact, status, created_at FROM orders ORDER BY created_at DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    orders = [{"id": r[0], "user_id": r[1], "username": r[2], "cart": json.loads(r[3]), "total": r[4], "budget": r[5], "contact": r[6], "status": r[7], "created_at": r[8]} for r in rows]
    conn.close()
    return orders

def get_orders_by_user(user_id, limit=5, only_completed=False):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if only_completed:
        c.execute('SELECT id, total, cart, status, created_at FROM orders WHERE user_id = ? AND status IN ("оплачена", "выполнена") ORDER BY created_at DESC LIMIT ?', (user_id, limit))
    else:
        c.execute('SELECT id, total, cart, status, created_at FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT ?', (user_id, limit))
    rows = c.fetchall()
    orders = [{"id": r[0], "total": r[1], "cart": json.loads(r[2]), "status": r[3], "created_at": r[4]} for r in rows]
    conn.close()
    return orders

def update_order_status(order_id, new_status):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE orders SET status = ? WHERE id = ?', (new_status, order_id))
    conn.commit()
    conn.close()

def get_order_by_id(order_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, user_id, username, total, status FROM orders WHERE id = ?', (order_id,))
    r = c.fetchone()
    conn.close()
    return {"id": r[0], "user_id": r[1], "username": r[2], "total": r[3], "status": r[4]} if r else None

def clear_non_successful_orders():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM orders WHERE status IN ('в обработке', 'отменена')")
    conn.commit()
    conn.close()

def clear_all_orders():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM orders')
    conn.commit()
    conn.close()
