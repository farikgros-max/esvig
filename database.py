import asyncpg
import json
import os

DATABASE_URL = os.getenv("DATABASE_URL")
pool = None


# ---------- INIT ----------
async def init_db():
    global pool
    if pool:
        return

    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            display_name TEXT
        )""")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT,
            price INT,
            subscribers INT,
            url TEXT,
            description TEXT,
            category_id INT
        )""")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance INT DEFAULT 0,
            daily_limit INT DEFAULT 3,
            daily_orders_count INT DEFAULT 0,
            last_order_date DATE DEFAULT CURRENT_DATE
        )""")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            cart TEXT,
            total INT,
            budget INT,
            contact TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )""")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            type TEXT,
            amount INT,
            order_id INT,
            description TEXT
        )""")


# ---------- ALIASES FIX (ВАЖНО) ----------
# чтобы НЕ ЛОМАЛИСЬ импорты

async def get_channels(category_id=None):
    return await get_all_channels(category_id)


async def get_categories():
    return await get_all_categories()


async def get_channel(channel_id):
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM channels WHERE id=$1", channel_id)
        return dict(r) if r else None


# ---------- CATEGORIES ----------
async def get_all_categories():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM categories ORDER BY id")
        return [dict(r) for r in rows]


# ---------- CHANNELS ----------
async def get_all_channels(category_id=None):
    async with pool.acquire() as conn:
        if category_id:
            rows = await conn.fetch(
                "SELECT * FROM channels WHERE category_id=$1",
                category_id
            )
        else:
            rows = await conn.fetch("SELECT * FROM channels")

        return {
            r["id"]: dict(r)
            for r in rows
        }


# ---------- USERS ----------
async def get_or_create_user(user_id, username=None):
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id=$1", user_id
        )

        if not user:
            await conn.execute("""
            INSERT INTO users (user_id, username)
            VALUES ($1, $2)
            """, user_id, username)

            return {"user_id": user_id, "username": username, "balance": 0}

        return dict(user)


async def get_user_balance(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT balance FROM users WHERE user_id=$1", user_id
        ) or 0


async def update_user_balance(user_id, amount, description=""):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
            UPDATE users SET balance = balance + $1
            WHERE user_id=$2
            """, amount, user_id)

            await conn.execute("""
            INSERT INTO transactions (user_id, type, amount, description)
            VALUES ($1,'balance',$2,$3)
            """, user_id, amount, description)


# alias (у тебя в проекте встречается update_balance)
update_balance = update_user_balance


async def debit_balance(user_id, amount, order_id=None, description=""):
    async with pool.acquire() as conn:
        bal = await conn.fetchval(
            "SELECT balance FROM users WHERE user_id=$1", user_id
        )

        if not bal or bal < amount:
            return False

        async with conn.transaction():
            await conn.execute("""
            UPDATE users SET balance = balance - $1
            WHERE user_id=$2
            """, amount, user_id)

        return True


# ---------- ORDERS ----------
async def save_order(user_id, username, cart, total, budget, contact, status):
    async with pool.acquire() as conn:
        return await conn.fetchval("""
        INSERT INTO orders (user_id, username, cart, total, budget, contact, status)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        RETURNING id
        """, user_id, username, json.dumps(cart), total, budget, contact, status)


async def get_orders(limit=50):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM orders ORDER BY id DESC LIMIT $1",
            limit
        )


async def get_orders_by_user(user_id, limit=10):
    async with pool.acquire() as conn:
        return await conn.fetch("""
        SELECT * FROM orders
        WHERE user_id=$1
        ORDER BY id DESC
        LIMIT $2
        """, user_id, limit)


async def get_order_by_id(order_id):
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM orders WHERE id=$1", order_id
        )
        return dict(r) if r else None


async def update_order_status(order_id, status):
    async with pool.acquire() as conn:
        await conn.execute("""
        UPDATE orders SET status=$1 WHERE id=$2
        """, status, order_id)


# ---------- ADMIN CLEAN ----------
async def clear_non_successful_orders():
    async with pool.acquire() as conn:
        await conn.execute("""
        DELETE FROM orders WHERE status!='success'
        """)


async def clear_all_orders():
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM orders")
