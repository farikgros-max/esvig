import asyncpg
import os
import json

DATABASE_URL = os.environ.get("DATABASE_URL")
pool = None


# ================= INIT =================
async def init_db():
    global pool
    if pool:
        return

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)

    async with pool.acquire() as conn:

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL
        )
        """)

        await conn.execute("""
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

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            daily_limit INTEGER DEFAULT 3,
            daily_orders_count INTEGER DEFAULT 0,
            last_order_date DATE DEFAULT CURRENT_DATE
        )
        """)

        # дефолт категории
        count = await conn.fetchval("SELECT COUNT(*) FROM categories")
        if count == 0:
            await conn.executemany("""
                INSERT INTO categories (name, display_name)
                VALUES ($1, $2)
            """, [
                ("news", "Новостные"),
                ("trading", "Торговые"),
                ("analytics", "Аналитика"),
                ("nft", "NFT"),
                ("memes", "Мемы"),
                ("defi", "DeFi")
            ])


# ================= CATEGORIES =================
async def get_categories():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM categories ORDER BY id")
        return [
            {"id": r["id"], "name": r["name"], "display_name": r["display_name"]}
            for r in rows
        ]


# ================= CHANNELS =================
async def get_channels(category_id=None):
    async with pool.acquire() as conn:

        if category_id:
            rows = await conn.fetch(
                "SELECT * FROM channels WHERE category_id=$1",
                category_id
            )
        else:
            rows = await conn.fetch("SELECT * FROM channels")

        return {
            r["id"]: {
                "name": r["name"],
                "price": r["price"],
                "subscribers": r["subscribers"],
                "url": r["url"],
                "description": r["description"] or "",
                "category_id": r["category_id"]
            }
            for r in rows
        }


async def get_channel(channel_id: str):
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM channels WHERE id=$1",
            channel_id
        )

        if not r:
            return None

        return {
            "id": r["id"],
            "name": r["name"],
            "price": r["price"],
            "subscribers": r["subscribers"],
            "url": r["url"],
            "description": r["description"] or "",
            "category_id": r["category_id"]
        }


# ================= USERS =================
async def get_user_balance(user_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT balance FROM users WHERE user_id=$1",
            user_id
        ) or 0


async def update_balance(user_id: int, amount: int):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, balance)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET balance = users.balance + $2
        """, user_id, amount)


# ================= PROFILE (FIX ERROR) =================
async def get_user_daily_info(user_id: int):
    async with pool.acquire() as conn:
        r = await conn.fetchrow("""
            SELECT daily_limit, daily_orders_count, last_order_date
            FROM users
            WHERE user_id=$1
        """, user_id)

        if not r:
            return 0, 0

        return r["daily_limit"], r["daily_orders_count"]


# ================= COMPAT LAYER =================
get_all_channels = get_channels
get_all_categories = get_categories
