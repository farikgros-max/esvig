import asyncpg
import json
import os
from typing import Optional, Dict, Any, List

DATABASE_URL = os.getenv("DATABASE_URL")
pool: Optional[asyncpg.Pool] = None

# ================= INIT =================
async def init_db():
    global pool
    if pool:
        return

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)

    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                subscribers INTEGER NOT NULL,
                url TEXT NOT NULL,
                description TEXT DEFAULT '',
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                cart TEXT,
                total INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        ''')

        await ensure_default_categories(conn)


async def close_db():
    global pool
    if pool:
        await pool.close()
        pool = None


# ================= CATEGORIES =================
async def ensure_default_categories(conn):
    await conn.executemany(
        '''INSERT INTO categories (name, display_name)
           VALUES ($1, $2)
           ON CONFLICT (name) DO NOTHING''',
        [
            ('news', 'Новостные'),
            ('trading', 'Торговые'),
            ('analytics', 'Аналитика'),
            ('nft', 'NFT')
        ]
    )


async def get_categories() -> List[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT * FROM categories ORDER BY id')
        return [dict(r) for r in rows]


async def get_category(cat_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT * FROM categories WHERE id = $1', cat_id)
        return dict(row) if row else None


# ================= CHANNELS =================
async def get_channels(category_id: Optional[int] = None) -> Dict[str, Dict]:
    async with pool.acquire() as conn:
        if category_id is None:
            rows = await conn.fetch('SELECT * FROM channels')
        else:
            rows = await conn.fetch(
                'SELECT * FROM channels WHERE category_id = $1',
                category_id
            )

    return {
        r['id']: {
            "name": r['name'],
            "price": r['price'],
            "subscribers": r['subscribers'],
            "url": r['url'],
            "description": r['description'],
            "category_id": r['category_id']
        }
        for r in rows
    }


async def get_channel(channel_id: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            'SELECT * FROM channels WHERE id = $1',
            channel_id
        )
        return dict(row) if row else None


async def add_channel(data: Dict[str, Any]):
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO channels (id, name, price, subscribers, url, description, category_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (id) DO UPDATE SET
                name=$2,
                price=$3,
                subscribers=$4,
                url=$5,
                description=$6,
                category_id=$7
        ''',
        data['id'], data['name'], data['price'], data['subscribers'],
        data['url'], data.get('description', ''), data.get('category_id'))


async def delete_channel(channel_id: str):
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM channels WHERE id = $1', channel_id)


# ================= USERS =================
async def get_user(user_id: int, username: Optional[str] = None):
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            'SELECT * FROM users WHERE user_id = $1', user_id
        )

        if not user:
            await conn.execute(
                'INSERT INTO users (user_id, username) VALUES ($1, $2)',
                user_id, username
            )
            return {"user_id": user_id, "balance": 0}

        if username and user['username'] != username:
            await conn.execute(
                'UPDATE users SET username = $1 WHERE user_id = $2',
                username, user_id
            )

        return dict(user)


async def update_balance(user_id: int, amount: int):
    async with pool.acquire() as conn:
        await conn.execute(
            'UPDATE users SET balance = balance + $1 WHERE user_id = $2',
            amount, user_id
        )


# ================= ORDERS =================
async def create_order(user_id: int, cart: Dict, total: int):
    async with pool.acquire() as conn:
        order_id = await conn.fetchval(
            '''INSERT INTO orders (user_id, cart, total)
               VALUES ($1, $2, $3)
               RETURNING id''',
            user_id, json.dumps(cart), total
        )
        return order_id


async def get_order(order_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            'SELECT * FROM orders WHERE id = $1', order_id
        )
        if not row:
            return None
        data = dict(row)
        data['cart'] = json.loads(data['cart'])
        return data
