import psycopg2
import json
import os

DATABASE_URL = "postgresql://postgres:srYFfPDjtixYVhbGMDakfDebfXSBAEDd@postgres.railway.internal:5432/railway"

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            subscribers INTEGER NOT NULL,
            url TEXT NOT NULL,
            description TEXT DEFAULT '',
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            cart TEXT,
            total INTEGER,
            budget INTEGER,
            contact TEXT,
            status TEXT DEFAULT 'в обработке',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # дефолт категории
    c.execute("SELECT COUNT(*) FROM categories")
    if c.fetchone()[0] == 0:
        default_cats = [
            ('news', 'Новостные'),
            ('trading', 'Торговые'),
            ('analytics', 'Аналитика'),
            ('nft', 'NFT'),
            ('memes', 'Мемкоины'),
            ('defi', 'DeFi')
        ]
        for name, display in default_cats:
            c.execute("INSERT INTO categories (name, display_name) VALUES (%s, %s)", (name, display))

    conn.commit()
    conn.close()


# ---------- категории ----------
def get_all_categories():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name, display_name FROM categories ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "display_name": r[2]} for r in rows]


def add_category(name, display_name):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO categories (name, display_name) VALUES (%s, %s)", (name, display_name))
    conn.commit()
    conn.close()


def delete_category(cat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE channels SET category_id = NULL WHERE category_id = %s", (cat_id,))
    c.execute("DELETE FROM categories WHERE id = %s", (cat_id,))
    conn.commit()
    conn.close()


def get_category_by_id(cat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name, display_name FROM categories WHERE id = %s", (cat_id,))
    r = c.fetchone()
    conn.close()
    return {"id": r[0], "name": r[1], "display_name": r[2]} if r else None


# ---------- каналы ----------
def get_all_channels(category_id=None):
    conn = get_conn()
    c = conn.cursor()

    if category_id:
        c.execute("SELECT * FROM channels WHERE category_id = %s", (category_id,))
    else:
        c.execute("SELECT * FROM channels")

    rows = c.fetchall()
    conn.close()

    ch = {}
    for r in rows:
        ch[r[0]] = {
            "name": r[1],
            "price": r[2],
            "subscribers": r[3],
            "url": r[4],
            "description": r[5],
            "category_id": r[6]
        }
    return ch


def add_channel(ch_id, name, price, subscribers, url, desc="", category_id=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO channels (id, name, price, subscribers, url, description, category_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        price = EXCLUDED.price,
        subscribers = EXCLUDED.subscribers,
        url = EXCLUDED.url,
        description = EXCLUDED.description,
        category_id = EXCLUDED.category_id
    """, (ch_id, name, price, subscribers, url, desc, category_id))
    conn.commit()
    conn.close()


def update_channel(ch_id, name=None, price=None, subscribers=None, url=None, description=None, category_id=None):
    conn = get_conn()
    c = conn.cursor()

    if name:
        c.execute("UPDATE channels SET name=%s WHERE id=%s", (name, ch_id))
    if price:
        c.execute("UPDATE channels SET price=%s WHERE id=%s", (price, ch_id))
    if subscribers:
        c.execute("UPDATE channels SET subscribers=%s WHERE id=%s", (subscribers, ch_id))
    if url:
        c.execute("UPDATE channels SET url=%s WHERE id=%s", (url, ch_id))
    if description:
        c.execute("UPDATE channels SET description=%s WHERE id=%s", (description, ch_id))
    if category_id is not None:
        c.execute("UPDATE channels SET category_id=%s WHERE id=%s", (category_id, ch_id))

    conn.commit()
    conn.close()


def delete_channel(ch_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE id = %s", (ch_id,))
    conn.commit()
    conn.close()


# ---------- заявки ----------
def save_order(user_id, username, cart, total, budget, contact, status='в обработке'):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO orders (user_id, username, cart, total, budget, contact, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (user_id, username, json.dumps(cart), total, budget, contact, status))

    oid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return oid


def get_orders(limit=20):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        SELECT id, user_id, username, cart, total, budget, contact, status, created_at
        FROM orders ORDER BY created_at DESC LIMIT %s
    """, (limit,))

    rows = c.fetchall()
    conn.close()

    return [{
        "id": r[0],
        "user_id": r[1],
        "username": r[2],
        "cart": json.loads(r[3]),
        "total": r[4],
        "budget": r[5],
        "contact": r[6],
        "status": r[7],
        "created_at": r[8]
    } for r in rows]


def get_orders_by_user(user_id, limit=5, only_completed=False):
    conn = get_conn()
    c = conn.cursor()

    if only_completed:
        c.execute("""
            SELECT id, total, cart, status, created_at
            FROM orders
            WHERE user_id = %s AND status IN ('оплачена','выполнена')
            ORDER BY created_at DESC LIMIT %s
        """, (user_id, limit))
    else:
        c.execute("""
            SELECT id, total, cart, status, created_at
            FROM orders
            WHERE user_id = %s
            ORDER BY created_at DESC LIMIT %s
        """, (user_id, limit))

    rows = c.fetchall()
    conn.close()

    return [{
        "id": r[0],
        "total": r[1],
        "cart": json.loads(r[2]),
        "status": r[3],
        "created_at": r[4]
    } for r in rows]


def update_order_status(order_id, new_status):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE orders SET status=%s WHERE id=%s", (new_status, order_id))
    conn.commit()
    conn.close()


def get_order_by_id(order_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, user_id, username, total, status FROM orders WHERE id=%s", (order_id,))
    r = c.fetchone()
    conn.close()
    return {"id": r[0], "user_id": r[1], "username": r[2], "total": r[3], "status": r[4]} if r else None


def clear_non_successful_orders():
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM orders WHERE status IN ('в обработке','отменена')")
    conn.commit()
    conn.close()


def clear_all_orders():
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM orders")
    conn.commit()
    conn.close()
