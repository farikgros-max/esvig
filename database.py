import asyncpg
import json
import os

DATABASE_URL = os.environ.get("DATABASE_URL")
pool = None

async def init_db():
    global pool
    if pool is not None:
        return
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)

    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL
            )''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                subscribers INTEGER NOT NULL,
                url TEXT NOT NULL,
                description TEXT DEFAULT '',
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL
            )''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                cart TEXT,
                total INTEGER,
                budget INTEGER,
                contact TEXT,
                status TEXT DEFAULT 'в обработке',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                slot_id INTEGER REFERENCES slots(id) ON DELETE SET NULL
            )''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                daily_limit INTEGER DEFAULT 3,
                daily_orders_count INTEGER DEFAULT 0,
                last_order_date DATE DEFAULT CURRENT_DATE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                order_id INTEGER REFERENCES orders(id),
                description TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )''')
        # Новая таблица слотов
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS slots (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                max_orders INTEGER DEFAULT 1,
                current_orders INTEGER DEFAULT 0
            )''')
        # Добавляем колонку slot_id в orders, если её ещё нет
        await conn.execute('ALTER TABLE orders ADD COLUMN IF NOT EXISTS slot_id INTEGER REFERENCES slots(id) ON DELETE SET NULL')

        # Стандартные категории
        exists = await conn.fetchval('SELECT COUNT(*) FROM categories')
        if exists == 0:
            default_cats = [
                ('news', 'Новостные'),
                ('trading', 'Торговые'),
                ('analytics', 'Аналитика'),
                ('nft', 'NFT'),
                ('memes', 'Мемкоины'),
                ('defi', 'DeFi')
            ]
            await conn.executemany(
                'INSERT INTO categories (name, display_name) VALUES ($1, $2)',
                default_cats
            )

async def close_db():
    global pool
    if pool:
        await pool.close()
        pool = None

# ---------- Пользователи и баланс ----------
async def get_or_create_user(user_id: int, username: str = None):
    async with pool.acquire() as conn:
        user = await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
        if not user:
            await conn.execute(
                'INSERT INTO users (user_id, username, balance, daily_limit, daily_orders_count, last_order_date) VALUES ($1, $2, 0, 3, 0, CURRENT_DATE)',
                user_id, username
            )
            return {'user_id': user_id, 'username': username, 'balance': 0, 'daily_limit': 3, 'daily_orders_count': 0}
        if username and user['username'] != username:
            await conn.execute('UPDATE users SET username = $1 WHERE user_id = $2', username, user_id)
        return {'user_id': user['user_id'], 'username': user['username'], 'balance': user['balance'],
                'daily_limit': user['daily_limit'], 'daily_orders_count': user['daily_orders_count']}

async def update_user_balance(user_id: int, amount: int, description: str = "Пополнение баланса"):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                'UPDATE users SET balance = balance + $1, updated_at = NOW() WHERE user_id = $2',
                amount, user_id
            )
            await conn.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1, 'пополнение', $2, $3)",
                user_id, amount, description
            )

async def debit_balance(user_id: int, amount: int, order_id: int, description: str = "Списание за заказ"):
    async with pool.acquire() as conn:
        async with conn.transaction():
            cur_balance = await conn.fetchval(
                'SELECT balance FROM users WHERE user_id = $1 FOR UPDATE', user_id
            )
            if cur_balance is None or cur_balance < amount:
                return False
            await conn.execute(
                'UPDATE users SET balance = balance - $1, updated_at = NOW() WHERE user_id = $2',
                amount, user_id
            )
            await conn.execute(
                "INSERT INTO transactions (user_id, type, amount, order_id, description) VALUES ($1, 'списание', $2, $3, $4)",
                user_id, amount, order_id, description
            )
            return True

async def return_balance(user_id: int, amount: int, order_id: int, description: str = "Возврат за отмену заказа"):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                'UPDATE users SET balance = balance + $1, updated_at = NOW() WHERE user_id = $2',
                amount, user_id
            )
            await conn.execute(
                "INSERT INTO transactions (user_id, type, amount, order_id, description) VALUES ($1, 'возврат', $2, $3, $4)",
                user_id, amount, order_id, description
            )

async def get_user_balance(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchval('SELECT balance FROM users WHERE user_id = $1', user_id) or 0

async def get_user_transactions(user_id, limit=10):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            'SELECT type, amount, description, created_at FROM transactions WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2',
            user_id, limit
        )
        return [{"type": r['type'], "amount": r['amount'], "description": r['description'], "created_at": str(r['created_at'])} for r in rows]

# ---------- Дневной лимит ----------
async def check_daily_order_limit(user_id: int) -> bool:
    async with pool.acquire() as conn:
        user = await conn.fetchrow('SELECT daily_limit, daily_orders_count, last_order_date FROM users WHERE user_id = $1', user_id)
        if not user:
            return False
        today = await conn.fetchval('SELECT CURRENT_DATE')
        if user['last_order_date'] != today:
            await conn.execute('UPDATE users SET daily_orders_count = 0, last_order_date = CURRENT_DATE WHERE user_id = $1', user_id)
            count = 0
        else:
            count = user['daily_orders_count']
        if count >= user['daily_limit']:
            return False
        await conn.execute('UPDATE users SET daily_orders_count = daily_orders_count + 1, last_order_date = CURRENT_DATE WHERE user_id = $1', user_id)
        return True

async def get_user_daily_info(user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT daily_limit, daily_orders_count, last_order_date FROM users WHERE user_id = $1', user_id)
        if not row:
            return 0, 0
        today = await conn.fetchval('SELECT CURRENT_DATE')
        if row['last_order_date'] != today:
            used = 0
        else:
            used = row['daily_orders_count']
        return row['daily_limit'], used

# ---------- Категории ----------
async def get_all_categories():
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT id, name, display_name FROM categories ORDER BY id')
        return [{"id": r['id'], "name": r['name'], "display_name": r['display_name']} for r in rows]

async def add_category(name, display_name):
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO categories (name, display_name) VALUES ($1, $2)', name, display_name)

async def delete_category(cat_id):
    async with pool.acquire() as conn:
        await conn.execute('UPDATE channels SET category_id = NULL WHERE category_id = $1', cat_id)
        await conn.execute('DELETE FROM categories WHERE id = $1', cat_id)

async def get_category_by_id(cat_id):
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT id, name, display_name FROM categories WHERE id = $1', cat_id)
        return {"id": r['id'], "name": r['name'], "display_name": r['display_name']} if r else None

# ---------- Каналы ----------
async def get_all_channels(category_id=None):
    async with pool.acquire() as conn:
        if category_id:
            rows = await conn.fetch(
                'SELECT id, name, price, subscribers, url, description, category_id FROM channels WHERE category_id = $1',
                category_id
            )
        else:
            rows = await conn.fetch('SELECT id, name, price, subscribers, url, description, category_id FROM channels')
        ch = {}
        for r in rows:
            ch[r['id']] = {
                "name": r['name'],
                "price": r['price'],
                "subscribers": r['subscribers'],
                "url": r['url'],
                "description": r['description'] or "",
                "category_id": r['category_id']
            }
        return ch

async def add_channel(ch_id, name, price, subscribers, url, desc="", category_id=None):
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO channels (id, name, price, subscribers, url, description, category_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (id) DO UPDATE SET name=$2, price=$3, subscribers=$4, url=$5, description=$6, category_id=$7
        ''', ch_id, name, price, subscribers, url, desc, category_id)

async def update_channel(ch_id, name=None, price=None, subs=None, url=None, desc=None, category_id=None):
    async with pool.acquire() as conn:
        if name is not None:
            await conn.execute('UPDATE channels SET name = $1 WHERE id = $2', name, ch_id)
        if price is not None:
            await conn.execute('UPDATE channels SET price = $1 WHERE id = $2', price, ch_id)
        if subs is not None:
            await conn.execute('UPDATE channels SET subscribers = $1 WHERE id = $2', subs, ch_id)
        if url is not None:
            await conn.execute('UPDATE channels SET url = $1 WHERE id = $2', url, ch_id)
        if desc is not None:
            await conn.execute('UPDATE channels SET description = $1 WHERE id = $2', desc, ch_id)
        if category_id is not None:
            await conn.execute('UPDATE channels SET category_id = $1 WHERE id = $2', category_id, ch_id)

async def delete_channel(ch_id):
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM channels WHERE id = $1', ch_id)

# ---------- Заказы ----------
async def save_order(user_id, username, cart, total, budget, contact, slot_id=None, status='в обработке'):
    async with pool.acquire() as conn:
        cart_json = json.dumps(cart)
        oid = await conn.fetchval(
            'INSERT INTO orders (user_id, username, cart, total, budget, contact, status, slot_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id',
            user_id, username, cart_json, total, budget, contact, status, slot_id
        )
        return oid

async def get_orders(limit=20):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            'SELECT id, user_id, username, cart, total, budget, contact, status, created_at, slot_id FROM orders ORDER BY created_at DESC LIMIT $1',
            limit
        )
        orders = []
        for r in rows:
            slot_info = None
            if r['slot_id']:
                slot_row = await conn.fetchrow('SELECT date, start_time, end_time FROM slots WHERE id = $1', r['slot_id'])
                if slot_row:
                    slot_info = f"{slot_row['date']} {slot_row['start_time']}-{slot_row['end_time']}"
            orders.append({
                "id": r['id'], "user_id": r['user_id'], "username": r['username'],
                "cart": json.loads(r['cart']), "total": r['total'], "budget": r['budget'],
                "contact": r['contact'], "status": r['status'], "created_at": str(r['created_at']),
                "slot": slot_info
            })
        return orders

async def get_orders_by_user(user_id, limit=5, only_completed=False):
    async with pool.acquire() as conn:
        if only_completed:
            rows = await conn.fetch(
                'SELECT id, total, cart, status, created_at, slot_id FROM orders WHERE user_id = $1 AND status IN ($2, $3) ORDER BY created_at DESC LIMIT $4',
                user_id, 'оплачена', 'выполнена', limit
            )
        else:
            rows = await conn.fetch(
                'SELECT id, total, cart, status, created_at, slot_id FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2',
                user_id, limit
            )
        return [{"id": r['id'], "total": r['total'], "cart": json.loads(r['cart']), "status": r['status'],
                 "created_at": str(r['created_at']), "slot_id": r['slot_id']} for r in rows]

async def update_order_status(order_id, new_status):
    async with pool.acquire() as conn:
        await conn.execute('UPDATE orders SET status = $1 WHERE id = $2', new_status, order_id)

async def get_order_by_id(order_id):
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT id, user_id, username, total, status, cart, slot_id FROM orders WHERE id = $1', order_id)
        if r:
            return {"id": r['id'], "user_id": r['user_id'], "username": r['username'], "total": r['total'],
                    "status": r['status'], "cart": json.loads(r['cart']), "slot_id": r['slot_id']}
        return None

# ---------- Очистка заказов ----------
async def clear_non_successful_orders():
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM transactions WHERE order_id IN (SELECT id FROM orders WHERE status IN ('в обработке', 'отменена'))"
        )
        await conn.execute("DELETE FROM orders WHERE status IN ('в обработке', 'отменена')")

async def clear_all_orders():
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM transactions WHERE order_id IS NOT NULL")
        await conn.execute("DELETE FROM orders")

# ---------- Слоты ----------
async def add_slot(date, start_time, end_time, max_orders=1):
    async with pool.acquire() as conn:
        await conn.execute(
            'INSERT INTO slots (date, start_time, end_time, max_orders, current_orders) VALUES ($1, $2, $3, $4, 0)',
            date, start_time, end_time, max_orders
        )

async def get_all_slots():
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT id, date, start_time, end_time, max_orders, current_orders FROM slots ORDER BY date, start_time')
        return [{"id": r['id'], "date": str(r['date']), "start_time": str(r['start_time']), "end_time": str(r['end_time']),
                 "max_orders": r['max_orders'], "current_orders": r['current_orders']} for r in rows]

async def get_available_slots():
    """Возвращает слоты, где ещё есть места."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            'SELECT id, date, start_time, end_time, max_orders, current_orders FROM slots WHERE current_orders < max_orders ORDER BY date, start_time'
        )
        return [{"id": r['id'], "date": str(r['date']), "start_time": str(r['start_time']), "end_time": str(r['end_time']),
                 "max_orders": r['max_orders'], "current_orders": r['current_orders']} for r in rows]

async def delete_slot(slot_id):
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM slots WHERE id = $1', slot_id)

async def increment_slot_orders(slot_id):
    """Увеличивает счётчик заказов в слоте на 1. Возвращает True, если ещё есть места, иначе False."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            slot = await conn.fetchrow('SELECT current_orders, max_orders FROM slots WHERE id = $1 FOR UPDATE', slot_id)
            if not slot or slot['current_orders'] >= slot['max_orders']:
                return False
            await conn.execute('UPDATE slots SET current_orders = current_orders + 1 WHERE id = $1', slot_id)
            return True
