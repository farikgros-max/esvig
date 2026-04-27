import asyncpg
import json
import os
import asyncio
from datetime import datetime, timedelta

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
            referral_code TEXT UNIQUE,
            inviter_id BIGINT,
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
    # Тикетная система
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username TEXT,
            subject TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            closed_at TIMESTAMPTZ
        )''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS ticket_messages (
            id SERIAL PRIMARY KEY,
            ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            message TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )''')
    try:
        await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT UNIQUE')
    except Exception:
        pass
    try:
        await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS inviter_id BIGINT')
    except Exception:
        pass
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

# ---------- Автоматизация ----------
async def auto_process_orders(bot):
    while True:
        try:
            conn = await get_connection()
            now = datetime.now()
            await conn.execute(
                "UPDATE orders SET status = 'отменена' WHERE status = 'ожидает оплаты' AND created_at < $1",
                now - timedelta(hours=24)
            )
            await conn.execute(
                "UPDATE orders SET status = 'выполнена' WHERE status = 'оплачена' AND created_at < $1",
                now - timedelta(hours=48)
            )
        except Exception as e:
            print(f"[AUTO] Ошибка автообработки: {e}")
        await asyncio.sleep(900)

# ---------- Пользователи и баланс ----------
async def get_or_create_user(user_id: int, username: str = None, inviter_id: int = None):
    conn = await get_connection()
    user = await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
    if not user:
        code = f"REF{user_id}"
        await conn.execute(
            '''INSERT INTO users (user_id, username, balance, daily_limit, daily_orders_count, last_order_date, referral_code, inviter_id)
               VALUES ($1, $2, 0, 3, 0, CURRENT_DATE, $3, $4)''',
            user_id, username, code, inviter_id
        )
        return {'user_id': user_id, 'username': username, 'balance': 0, 'daily_limit': 3,
                'daily_orders_count': 0, 'referral_code': code, 'inviter_id': inviter_id}
    if username and user['username'] != username:
        await conn.execute('UPDATE users SET username = $1 WHERE user_id = $2', username, user_id)
    referral_code = user['referral_code']
    if not referral_code:
        referral_code = f"REF{user_id}"
        await conn.execute('UPDATE users SET referral_code = $1 WHERE user_id = $2', referral_code, user_id)
    return {'user_id': user['user_id'], 'username': user['username'], 'balance': user['balance'],
            'daily_limit': user['daily_limit'], 'daily_orders_count': user['daily_orders_count'],
            'referral_code': referral_code, 'inviter_id': user['inviter_id']}

async def update_user_referral_code(user_id: int, code: str):
    conn = await get_connection()
    await conn.execute('UPDATE users SET referral_code = $1 WHERE user_id = $2', code, user_id)

async def get_user_by_referral_code(code: str):
    conn = await get_connection()
    return await conn.fetchrow('SELECT user_id FROM users WHERE referral_code = $1', code)

async def get_user_invited_count(user_id: int) -> int:
    """Сколько человек пригласил данный пользователь (прямые рефералы)."""
    conn = await get_connection()
    count = await conn.fetchval('SELECT COUNT(*) FROM users WHERE inviter_id = $1', user_id)
    return count or 0

def get_referral_level(invited_count: int) -> int:
    """Определяет уровень по количеству приглашённых."""
    if invited_count <= 10:
        return 1
    elif invited_count <= 50:
        return 2
    else:
        return 3

def get_referral_percent(level: int) -> float:
    """Возвращает процент бонуса для заданного уровня."""
    if level == 1:
        return 1.0
    elif level == 2:
        return 2.0
    elif level == 3:
        return 3.5
    return 0.0

async def get_referral_stats(user_id: int):
    """Статистика для реферальной программы."""
    invited = await get_user_invited_count(user_id)
    level = get_referral_level(invited)
    percent = get_referral_percent(level)
    # Общий заработок с рефералов
    bonuses = await conn.fetchval(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id = $1 AND type = 'реферальный бонус'",
        user_id
    ) if (conn := await get_connection()) else 0
    # Прогресс до следующего уровня
    next_level = level + 1 if level < 3 else None
    needed = 0
    if next_level == 2:
        needed = 11 - invited
    elif next_level == 3:
        needed = 51 - invited

    return {
        "invited": invited,
        "level": level,
        "percent": percent,
        "bonuses": bonuses or 0,
        "next_level": next_level,
        "needed": needed
    }

async def process_referral_bonus(order_id: int, order_total: int):
    conn = await get_connection()
    order = await conn.fetchrow('SELECT user_id, total FROM orders WHERE id = $1', order_id)
    if not order:
        return
    user_id = order['user_id']
    # Находим прямого пригласителя
    inviter = await conn.fetchrow('SELECT inviter_id FROM users WHERE user_id = $1', user_id)
    if not inviter or not inviter['inviter_id']:
        return
    inviter_id = inviter['inviter_id']
    # Считаем, сколько у него приглашённых
    invited_count = await get_user_invited_count(inviter_id)
    level = get_referral_level(invited_count)
    percent = get_referral_percent(level)
    if percent == 0:
        return
    bonus = int(order_total * percent / 100)
    if bonus <= 0:
        return
    async with conn.transaction():
        await conn.execute(
            'UPDATE users SET balance = balance + $1 WHERE user_id = $2',
            bonus, inviter_id
        )
        await conn.execute(
            '''INSERT INTO transactions (user_id, type, amount, order_id, description)
               VALUES ($1, 'реферальный бонус', $2, $3, $4)''',
            inviter_id, bonus, order_id,
            f"Реферальный бонус ({percent}%) от заказа #{order_id} пользователя {user_id}"
        )

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
    await process_pending_orders(user_id)

async def process_pending_orders(user_id: int):
    conn = await get_connection()
    pending = await conn.fetch(
        "SELECT id, total FROM orders WHERE user_id = $1 AND status = 'ожидает оплаты' ORDER BY id",
        user_id
    )
    if not pending:
        return
    balance = await get_user_balance(user_id)
    for order in pending:
        if balance >= order['total']:
            success = await debit_balance(user_id, order['total'], order['id'], f"Оплата заказа #{order['id']}")
            if success:
                await update_order_status(order['id'], 'оплачена')
                balance -= order['total']
                await process_referral_bonus(order['id'], order['total'])

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

# ---------- Каналы ----------
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

# ---------- Статистика ----------
async def get_top_channels(limit=10):
    conn = await get_connection()
    rows = await conn.fetch('SELECT cart FROM orders WHERE status IN ($1, $2)', 'оплачена', 'выполнена')
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

async def get_top_buyers(limit=10):
    conn = await get_connection()
    rows = await conn.fetch(
        'SELECT user_id, username, SUM(total) as total_spent, COUNT(*) as order_count FROM orders WHERE status IN ($1, $2) GROUP BY user_id, username ORDER BY total_spent DESC LIMIT $3',
        'оплачена', 'выполнена', limit
    )
    return [{"user_id": r['user_id'], "username": r['username'] or "Unknown",
             "total_spent": r['total_spent'], "order_count": r['order_count']} for r in rows]

async def get_daily_revenue(days=7):
    conn = await get_connection()
    rows = await conn.fetch(
        '''SELECT DATE(created_at) as day, COUNT(*) as orders, COALESCE(SUM(total),0) as revenue
           FROM orders WHERE status IN ('оплачена', 'выполнена') AND created_at >= CURRENT_DATE - $1::integer
           GROUP BY day ORDER BY day ASC''',
        days
    )
    return [{"day": str(r['day']), "orders": r['orders'], "revenue": r['revenue']} for r in rows]

# ---------- Резервное копирование ----------
async def backup_database():
    conn = await get_connection()
    backup = {}
    users = await conn.fetch('SELECT * FROM users')
    backup['users'] = [dict(r) for r in users]
    cats = await conn.fetch('SELECT * FROM categories')
    backup['categories'] = [dict(r) for r in cats]
    channels = await conn.fetch('SELECT * FROM channels')
    backup['channels'] = [dict(r) for r in channels]
    orders = await conn.fetch('SELECT * FROM orders')
    backup['orders'] = [dict(r) for r in orders]
    trans = await conn.fetch('SELECT * FROM transactions')
    backup['transactions'] = [dict(r) for r in trans]
    tickets = await conn.fetch('SELECT * FROM tickets')
    backup['tickets'] = [dict(r) for r in tickets]
    ticket_msgs = await conn.fetch('SELECT * FROM ticket_messages')
    backup['ticket_messages'] = [dict(r) for r in ticket_msgs]

    filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(backup, f, ensure_ascii=False, indent=2, default=str)
    return filename

# ---------- ТИКЕТНАЯ СИСТЕМА ----------
async def create_ticket(user_id: int, username: str, subject: str, message: str) -> int:
    conn = await get_connection()
    async with conn.transaction():
        ticket_id = await conn.fetchval(
            '''INSERT INTO tickets (user_id, username, subject, status)
               VALUES ($1, $2, $3, 'open') RETURNING id''',
            user_id, username, subject
        )
        await conn.execute(
            '''INSERT INTO ticket_messages (ticket_id, user_id, message)
               VALUES ($1, $2, $3)''',
            ticket_id, user_id, message
        )
    return ticket_id

async def get_tickets(status: str = 'open') -> list:
    conn = await get_connection()
    rows = await conn.fetch(
        '''SELECT id, user_id, username, subject, status, created_at FROM tickets
           WHERE status = $1 ORDER BY created_at DESC LIMIT 50''',
        status
    )
    return [dict(r) for r in rows]

async def get_ticket_messages(ticket_id: int) -> list:
    conn = await get_connection()
    rows = await conn.fetch(
        '''SELECT user_id, message, created_at, is_admin FROM ticket_messages
           WHERE ticket_id = $1 ORDER BY created_at ASC''',
        ticket_id
    )
    return [dict(r) for r in rows]

async def add_ticket_message(ticket_id: int, user_id: int, message: str, is_admin: bool = False):
    conn = await get_connection()
    await conn.execute(
        '''INSERT INTO ticket_messages (ticket_id, user_id, message, is_admin)
           VALUES ($1, $2, $3, $4)''',
        ticket_id, user_id, message, is_admin
    )
    await conn.execute(
        'UPDATE tickets SET updated_at = NOW() WHERE id = $1', ticket_id
    )

async def close_ticket(ticket_id: int):
    conn = await get_connection()
    await conn.execute(
        "UPDATE tickets SET status = 'closed', closed_at = NOW() WHERE id = $1", ticket_id
    )

# ---------- РАССЫЛКА ----------
async def get_all_user_ids() -> list:
    conn = await get_connection()
    rows = await conn.fetch('SELECT user_id FROM users')
    return [r['user_id'] for r in rows]
