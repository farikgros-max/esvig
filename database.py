import asyncpg
import json
import os
import asyncio

DATABASE_URL = os.environ.get("DATABASE_URL")

_conn: asyncpg.Connection = None
_lock = asyncio.Lock()

_channels_dict = {}

async def get_connection() -> asyncpg.Connection:
    global _conn
    if _conn is None or _conn.is_closed():
        async with _lock:
            if _conn is None or _conn.is_closed():
                try:
                    _conn = await asyncpg.connect(DATABASE_URL)
                    print("[DB] Установлено новое подключение к БД")
                except Exception as e:
                    print(f"[DB] Ошибка подключения: {e}")
                    raise
    return _conn

async def close_db():
    global _conn
    if _conn:
        await _conn.close()
        _conn = None

async def _load_channels_from_db():
    global _channels_dict
    for attempt in range(5):
        try:
            conn = await get_connection()
            rows = await conn.fetch(
                '''SELECT id, name, price, subscribers, url, description, category_id,
                   COALESCE(active, TRUE) AS active
                FROM channels'''
            )
            ch = {}
            for r in rows:
                ch[r['id']] = {
                    "name": r['name'],
                    "price": r['price'],
                    "subscribers": r['subscribers'],
                    "url": r['url'],
                    "description": r['description'] or "",
                    "category_id": r['category_id'],
                    "active": r['active']
                }
            _channels_dict = ch
            print(f"[MEM] Каналы загружены в память: {len(ch)}")
            return
        except Exception as e:
            print(f"[MEM] Попытка {attempt+1}: {e}")
            await close_db()
            await asyncio.sleep(1)
    print("[MEM] Не удалось загрузить каналы после 5 попыток")

async def init_db():
    conn = await get_connection()
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
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            active BOOLEAN DEFAULT TRUE
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

    # Убедимся, что столбец active существует (миграция)
    try:
        await conn.execute('ALTER TABLE channels ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE')
    except Exception:
        pass

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

    await _load_channels_from_db()

# ---------- Пользователи и баланс ----------
async def get_or_create_user(user_id: int, username: str = None):
    conn = await get_connection()
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
    conn = await get_connection()
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
    conn = await get_connection()
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
    conn = await get_connection()
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
    conn = await get_connection()
    return await conn.fetchval('SELECT balance FROM users WHERE user_id = $1', user_id) or 0

async def get_user_transactions(user_id, limit=10):
    conn = await get_connection()
    rows = await conn.fetch(
        'SELECT type, amount, description, created_at FROM transactions WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2',
        user_id, limit
    )
    return [{"type": r['type'], "amount": r['amount'], "description": r['description'], "created_at": str(r['created_at'])} for r in rows]

# ---------- Дневной лимит ----------
async def check_daily_order_limit(user_id: int) -> bool:
    conn = await get_connection()
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
    conn = await get_connection()
    row = await conn.fetchrow('SELECT daily_limit, daily_orders_count, last_order_date FROM users WHERE user_id = $1', user_id)
    if not row:
        return 0, 0
    today = await conn.fetchval('SELECT CURRENT_DATE')
    used = row['daily_orders_count'] if row['last_order_date'] == today else 0
    return row['daily_limit'], used

# ---------- Категории ----------
async def get_all_categories():
    conn = await get_connection()
    rows = await conn.fetch('SELECT id, name, display_name FROM categories ORDER BY id')
    if not rows:
        await conn.executemany(
            'INSERT INTO categories (name, display_name) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING',
            [('news', 'Новостные'), ('trading', 'Торговые'), ('analytics', 'Аналитика'),
             ('nft', 'NFT'), ('memes', 'Мемкоины'), ('defi', 'DeFi')]
        )
        rows = await conn.fetch('SELECT id, name, display_name FROM categories ORDER BY id')
    return [{"id": r['id'], "name": r['name'], "display_name": r['display_name']} for r in rows]

async def add_category(name, display_name):
    conn = await get_connection()
    await conn.execute('INSERT INTO categories (name, display_name) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING', name, display_name)

async def delete_category(cat_id):
    conn = await get_connection()
    async with conn.transaction():
        await conn.execute('UPDATE channels SET category_id = NULL WHERE category_id = $1', cat_id)
        await conn.execute('DELETE FROM categories WHERE id = $1', cat_id)
    await _load_channels_from_db()

async def get_category_by_id(cat_id):
    conn = await get_connection()
    r = await conn.fetchrow('SELECT id, name, display_name FROM categories WHERE id = $1', cat_id)
    return {"id": r['id'], "name": r['name'], "display_name": r['display_name']} if r else None

# ---------- Каналы (с полем active) ----------
async def get_all_channels(category_id=None):
    global _channels_dict
    if not _channels_dict:
        await _load_channels_from_db()
    if category_id is not None:
        return {k: v for k, v in _channels_dict.items() if v.get('category_id') == category_id}
    return _channels_dict

async def get_active_channels(category_id=None):
    all_ch = await get_all_channels(category_id)
    return {k: v for k, v in all_ch.items() if v.get('active', True)}

# Алиасы
async def get_channels(category_id=None):
    return await get_all_channels(category_id)

async def get_channel(channel_id):
    global _channels_dict
    if not _channels_dict:
        await _load_channels_from_db()
    return _channels_dict.get(str(channel_id))

async def add_channel(ch_id, name, price, subscribers, url, desc="", category_id=None):
    conn = await get_connection()
    await conn.execute('''
        INSERT INTO channels (id, name, price, subscribers, url, description, category_id, active)
        VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE)
        ON CONFLICT (id) DO UPDATE SET name=$2, price=$3, subscribers=$4, url=$5, description=$6, category_id=$7
    ''', ch_id, name, price, subscribers, url, desc, category_id)
    _channels_dict[ch_id] = {
        "name": name, "price": price, "subscribers": subscribers,
        "url": url, "description": desc or "", "category_id": category_id, "active": True
    }

async def update_channel(ch_id, name=None, price=None, subs=None, url=None, desc=None, category_id=None):
    conn = await get_connection()
    if name is not None:
        await conn.execute('UPDATE channels SET name = $1 WHERE id = $2', name, ch_id)
        if ch_id in _channels_dict: _channels_dict[ch_id]['name'] = name
    if price is not None:
        await conn.execute('UPDATE channels SET price = $1 WHERE id = $2', price, ch_id)
        if ch_id in _channels_dict: _channels_dict[ch_id]['price'] = price
    if subs is not None:
        await conn.execute('UPDATE channels SET subscribers = $1 WHERE id = $2', subs, ch_id)
        if ch_id in _channels_dict: _channels_dict[ch_id]['subscribers'] = subs
    if url is not None:
        await conn.execute('UPDATE channels SET url = $1 WHERE id = $2', url, ch_id)
        if ch_id in _channels_dict: _channels_dict[ch_id]['url'] = url
    if desc is not None:
        await conn.execute('UPDATE channels SET description = $1 WHERE id = $2', desc, ch_id)
        if ch_id in _channels_dict: _channels_dict[ch_id]['description'] = desc
    if category_id is not None:
        await conn.execute('UPDATE channels SET category_id = $1 WHERE id = $2', category_id, ch_id)
        if ch_id in _channels_dict: _channels_dict[ch_id]['category_id'] = category_id

async def toggle_channel_active(ch_id):
    conn = await get_connection()
    current = await conn.fetchval('SELECT active FROM channels WHERE id = $1', ch_id)
    new_active = not current if current is not None else False
    await conn.execute('UPDATE channels SET active = $1 WHERE id = $2', new_active, ch_id)
    if ch_id in _channels_dict:
        _channels_dict[ch_id]['active'] = new_active
    return new_active

async def delete_channel(ch_id):
    conn = await get_connection()
    await conn.execute('DELETE FROM channels WHERE id = $1', ch_id)
    if ch_id in _channels_dict:
        del _channels_dict[ch_id]

# ---------- Статистика ----------
async def get_top_channels(limit=10):
    """Возвращает список каналов с количеством заказов и общей суммой."""
    conn = await get_connection()
    rows = await conn.fetch('SELECT cart FROM orders')
    channel_stats = {}
    for r in rows:
        try:
            cart = json.loads(r['cart'])
        except Exception:
            continue
        for item in cart:
            cid = str(item.get('id'))
            if cid not in channel_stats:
                channel_stats[cid] = {"orders": 0, "total": 0}
            channel_stats[cid]["orders"] += 1
            channel_stats[cid]["total"] += item.get('price', 0)
    # Сортируем по количеству заказов
    sorted_ids = sorted(channel_stats, key=lambda x: channel_stats[x]['orders'], reverse=True)[:limit]
    result = []
    for cid in sorted_ids:
        ch = _channels_dict.get(cid, {})
        result.append({
            "name": ch.get('name', f'ID {cid}'),
            "orders": channel_stats[cid]['orders'],
            "total": channel_stats[cid]['total']
        })
    return result

# ---------- Заказы ----------
async def save_order(user_id, username, cart, total, budget, contact, status='в обработке'):
    conn = await get_connection()
    async with conn.transaction():
        cart_json = json.dumps(cart)
        oid = await conn.fetchval(
            'INSERT INTO orders (user_id, username, cart, total, budget, contact, status) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id',
            user_id, username, cart_json, total, budget, contact, status
        )
        return oid

async def get_orders(limit=20):
    conn = await get_connection()
    rows = await conn.fetch(
        'SELECT id, user_id, username, cart, total, budget, contact, status, created_at FROM orders ORDER BY created_at DESC LIMIT $1',
        limit
    )
    return [{"id": r['id'], "user_id": r['user_id'], "username": r['username'],
             "cart": json.loads(r['cart']), "total": r['total'], "budget": r['budget'],
             "contact": r['contact'], "status": r['status'], "created_at": str(r['created_at'])} for r in rows]

async def get_orders_by_user(user_id, limit=5, only_completed=False):
    conn = await get_connection()
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
    conn = await get_connection()
    await conn.execute('UPDATE orders SET status = $1 WHERE id = $2', new_status, order_id)

async def get_order_by_id(order_id):
    conn = await get_connection()
    r = await conn.fetchrow('SELECT id, user_id, username, total, status, cart FROM orders WHERE id = $1', order_id)
    if r:
        return {"id": r['id'], "user_id": r['user_id'], "username": r['username'], "total": r['total'],
                "status": r['status'], "cart": json.loads(r['cart'])}
    return None

async def clear_non_successful_orders():
    conn = await get_connection()
    async with conn.transaction():
        await conn.execute(
            "DELETE FROM transactions WHERE order_id IN (SELECT id FROM orders WHERE status IN ('в обработке', 'отменена'))"
        )
        await conn.execute("DELETE FROM orders WHERE status IN ('в обработке', 'отменена')")

async def clear_all_orders():
    conn = await get_connection()
    async with conn.transaction():
        await conn.execute("DELETE FROM transactions WHERE order_id IS NOT NULL")
        await conn.execute("DELETE FROM orders")
