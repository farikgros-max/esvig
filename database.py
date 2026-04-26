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
                balance INTEGER DEFAULT 0
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


async def get_categories():
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT * FROM categories ORDER BY id')
        return [dict(r) for r in rows]


async def get_category(cat_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT * FROM categories WHERE id = $1', cat_id)
        return dict(row) if row else None


# ================= CHANNELS =================
async def get_channels(category_id=None):
    async with pool.acquire() as conn:
        if category_id:
            rows = await conn.fetch(
                'SELECT * FROM channels WHERE category_id = $1',
                category_id
            )
        else:
            rows = await conn.fetch('SELECT * FROM channels')

    return {r['id']: dict(r) for r in rows}


async def get_channel(channel_id: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            'SELECT * FROM channels WHERE id = $1',
            channel_id
        )
        return dict(row) if row else None


# ================= USERS =================
async def get_user(user_id: int, username=None):
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

        return dict(user)


async def update_balance(user_id: int, amount: int):
    async with pool.acquire() as conn:
        await conn.execute(
            'UPDATE users SET balance = balance + $1 WHERE user_id = $2',
            amount, user_id
        )


# ================= COMPAT =================
async def get_all_channels(category_id=None):
    return await get_channels(category_id)

async def get_all_categories():
    return await get_categories()

async def get_category_by_id(cat_id):
    return await get_category(cat_id)

async def get_or_create_user(user_id, username=None):
    return await get_user(user_id, username)

async def update_user_balance(user_id, amount, description=None):
    return await update_balance(user_id, amount)
