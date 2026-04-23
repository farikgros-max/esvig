import sqlite3
import json

DB_NAME = 'channels.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            subscribers INTEGER NOT NULL,
            url TEXT NOT NULL,
            description TEXT DEFAULT ''
        )
    ''')
    cur.execute("PRAGMA table_info(channels)")
    columns = [col[1] for col in cur.fetchall()]
    if 'description' not in columns:
        cur.execute('ALTER TABLE channels ADD COLUMN description TEXT DEFAULT ""')
    cur.execute('''
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
    cur.execute("PRAGMA table_info(orders)")
    columns = [col[1] for col in cur.fetchall()]
    if 'status' not in columns:
        cur.execute('ALTER TABLE orders ADD COLUMN status TEXT DEFAULT "в обработке"')
    conn.commit()
    conn.close()

def get_all_channels():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('SELECT id, name, price, subscribers, url, description FROM channels')
    rows = cur.fetchall()
    channels = {}
    for row in rows:
        ch_id, name, price, subscribers, url, description = row
        channels[ch_id] = {
            "name": name,
            "price": price,
            "subscribers": subscribers,
            "url": url,
            "description": description or ""
        }
    conn.close()
    return channels

def add_channel(ch_id, name, price, subscribers, url, description=""):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO channels (id, name, price, subscribers, url, description)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (ch_id, name, price, subscribers, url, description))
    conn.commit()
    conn.close()

def delete_channel(ch_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('DELETE FROM channels WHERE id = ?', (ch_id,))
    conn.commit()
    conn.close()

def update_channel(ch_id, name=None, price=None, subscribers=None, url=None, description=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if name is not None:
        cur.execute('UPDATE channels SET name = ? WHERE id = ?', (name, ch_id))
    if price is not None:
        cur.execute('UPDATE channels SET price = ? WHERE id = ?', (price, ch_id))
    if subscribers is not None:
        cur.execute('UPDATE channels SET subscribers = ? WHERE id = ?', (subscribers, ch_id))
    if url is not None:
        cur.execute('UPDATE channels SET url = ? WHERE id = ?', (url, ch_id))
    if description is not None:
        cur.execute('UPDATE channels SET description = ? WHERE id = ?', (description, ch_id))
    conn.commit()
    conn.close()

def save_order(user_id, username, cart, total, budget, contact, status='в обработке'):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cart_json = json.dumps(cart)
    cur.execute('''
        INSERT INTO orders (user_id, username, cart, total, budget, contact, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, username, cart_json, total, budget, contact, status))
    conn.commit()
    conn.close()

def get_orders(limit=10):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, user_id, username, cart, total, budget, contact, status, created_at
        FROM orders
        ORDER BY created_at DESC
        LIMIT ?
    ''', (limit,))
    rows = cur.fetchall()
    orders = []
    for row in rows:
        orders.append({
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "cart": json.loads(row[3]),
            "total": row[4],
            "budget": row[5],
            "contact": row[6],
            "status": row[7],
            "created_at": row[8]
        })
    conn.close()
    return orders

def get_orders_by_user(user_id, limit=5):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, total, cart, status, created_at
        FROM orders
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = cur.fetchall()
    orders = []
    for row in rows:
        orders.append({
            "id": row[0],
            "total": row[1],
            "cart": json.loads(row[2]),
            "status": row[3],
            "created_at": row[4]
        })
    conn.close()
    return orders

def update_order_status(order_id, new_status):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('UPDATE orders SET status = ? WHERE id = ?', (new_status, order_id))
    conn.commit()
    conn.close()
    return cur.rowcount > 0

def get_order_by_id(order_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('SELECT id, user_id, username, total, status FROM orders WHERE id = ?', (order_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "total": row[3],
            "status": row[4]
        }
    return None