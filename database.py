import asyncpg
import json
import os
import asyncio

DATABASE_URL = os.environ.get("DATABASE_URL")
pool = None

# ---------- Быстрая и надёжная загрузка данных ----------
async def _retry_fetch_best(query, *args, fetch_all=True, max_retries=4, delay=0.8):
    """
    Выполняет SELECT-запрос. Если результат непустой - сразу возвращает.
    При пустом результате пересоздаёт пул и пробует снова (до max_retries раз).
    """
    global pool
    for attempt in range(max_retries):
        try:
            async with pool.acquire() as conn:
                if fetch_all:
                    rows = await conn.fetch(query, *args)
                    if rows:
                        return rows
                else:
                    row = await conn.fetchrow(query, *args)
                    if row is not None:
                        return row
        except (OSError, asyncpg.exceptions.ConnectionDoesNotExistError,
                asyncpg.exceptions.InterfaceError, AttributeError) as e:
            print(f"[DB] Ошибка соединения (попытка {attempt+1}): {e}")
            try:
                if pool:
                    await pool.close()
            except:
                pass
            pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
        except Exception as e:
            print(f"[DB] Неожиданная ошибка (попытка {attempt+1}): {e}")
        await asyncio.sleep(delay * (attempt + 1))
    # Если все попытки провалились, возвращаем пустой результат
    return [] if fetch_all else None

# ---------- Инициализация БД ----------
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
                created_at TIMESTAMPTZ DEFAULT NOW()
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

        await _ensure_default_categories(conn)

async def _ensure_default_categories(conn):
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
            'INSERT INTO categories (name, display_name) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING',
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
    rows = await _retry_fetch_best('SELECT id, name, display_name FROM categories ORDER BY id', fetch_all=True)
    if not rows:
        # Если категорий нет, создаём стандартные и пробуем снова
        async with pool.acquire() as conn:
            await _ensure_default_categories(conn)
        rows = await _retry_fetch_best('SELECT id, name, display_name FROM categories ORDER BY id', fetch_all=True)
    return [{"id": r['id'], "name": r['name'], "display_name": r['display_name']} for r in rows]

async def add_category(name, display_name):
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO categories (name, display_name) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING', name, display_name)

async def delete_category(cat_id):
    async with pool.acquire() as conn:
        await conn.execute('UPDATE channels SET category_id = NULL WHERE category_id = $1', cat_id)
        await conn.execute('DELETE FROM categories WHERE id = $1', cat_id)

async def get_category_by_id(cat_id):
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT id, name, display_name FROM categories WHERE id = $1', cat_id)
        return {"id": r['id'], "name": r['name'], "display_name": r['display_name']} if r else None

# ---------- Каналы (теперь работает мгновенно) ----------
async def get_all_channels(category_id=None):
    if category_id is not None:
        rows = await _retry_fetch_best(
            'SELECT id, name, price, subscribers, url, description, category_id FROM channels WHERE category_id = $1',
            category_id, fetch_all=True
        )
    else:
        rows = await _retry_fetch_best(
            'SELECT id, name, price, subscribers, url, description, category_id FROM channels', fetch_all=True
        )
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
async def save_order(user_id, username, cart, total, budget, contact, status='в обработке'):
    async with pool.acquire() as conn:
        cart_json = json.dumps(cart)
        oid = await conn.fetchval(
            'INSERT INTO orders (user_id, username, cart, total, budget, contact, status) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id',
            user_id, username, cart_json, total, budget, contact, status
        )
        return oid

async def get_orders(limit=20):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            'SELECT id, user_id, username, cart, total, budget, contact, status, created_at FROM orders ORDER BY created_at DESC LIMIT $1',
            limit
        )
        return [{"id": r['id'], "user_id": r['user_id'], "username": r['username'],
                 "cart": json.loads(r['cart']), "total": r['total'], "budget": r['budget'],
                 "contact": r['contact'], "status": r['status'], "created_at": str(r['created_at'])} for r in rows]

async def get_orders_by_user(user_id, limit=5, only_completed=False):
    async with pool.acquire() as conn:
        if only_completed:
            rows = await conn.fetch(
                'SELECT id, total, cart, status, created_at FROM orders WHERE user_id = $1 AND status IN ($2, $3) ORDER BY created_at DESC LIMIT $4',
                user_id, 'оплачена', 'выполнена', limit
            )
        else:
            rows = await conn.fetch(
                'SELECT id, total, cart, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2',
                user_id, limit
            )
        return [{"id": r['id'], "total": r['total'], "cart": json.loads(r['cart']),
                 "status": r['status'], "created_at": str(r['created_at'])} for r in rows]

async def update_order_status(order_id, new_status):
    async with pool.acquire() as conn:
        await conn.execute('UPDATE orders SET status = $1 WHERE id = $2', new_status, order_id)

async def get_order_by_id(order_id):
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT id, user_id, username, total, status, cart FROM orders WHERE id = $1', order_id)
        if r:
            return {"id": r['id'], "user_id": r['user_id'], "username": r['username'], "total": r['total'],
                    "status": r['status'], "cart": json.loads(r['cart'])}
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
