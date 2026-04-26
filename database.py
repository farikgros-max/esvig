import asyncpg
import json
import os
import asyncio

DATABASE_URL = os.environ.get("DATABASE_URL")

pool: asyncpg.Pool | None = None


# ---------- INIT DB ----------
async def init_db():
    global pool
    if pool:
        return

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)

    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL
        )""")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INT NOT NULL,
            subscribers INT NOT NULL,
            url TEXT NOT NULL,
            description TEXT DEFAULT '',
            category_id INT REFERENCES categories(id) ON DELETE SET NULL
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
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            type TEXT,
            amount INT,
            order_id INT,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""")

        await _ensure_categories(conn)


async def _ensure_categories(conn):
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
            ("memes", "Мемкоины"),
            ("defi", "DeFi"),
        ])


# ---------- USERS ----------
async def get_or_create_user(user_id: int, username: str = None):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)

        if not user:
            await conn.execute("""
            INSERT INTO users (user_id, username)
            VALUES ($1, $2)
            """, user_id, username)
            return {"user_id": user_id, "username": username, "balance": 0}

        if username:
            await conn.execute("UPDATE users SET username=$1 WHERE user_id=$2", username, user_id)

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
            VALUES ($1, 'balance', $2, $3)
            """, user_id, amount, description)


# alias (у тебя в коде встречается update_balance)
update_balance = update_user_balance


async def debit_balance(user_id, amount, order_id=None, description=""):
    async with pool.acquire() as conn:
        bal = await conn.fetchval(
            "SELECT balance FROM users WHERE user_id=$1", user_id
        )

        if bal is None or bal < amount:
            return False

        async with conn.transaction():
            await conn.execute("""
            UPDATE users SET balance = balance - $1 WHERE user_id=$2
            """, amount, user_id)

            await conn.execute("""
            INSERT INTO transactions (user_id, type, amount, order_id, description)
            VALUES ($1, 'debit', $2, $3, $4)
            """, user_id, amount, order_id, description)

        return True


async def return_balance(user_id, amount, order_id=None, description=""):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
            UPDATE users SET balance = balance + $1 WHERE user_id=$2
            """, amount, user_id)

            await conn.execute("""
            INSERT INTO transactions (user_id, type, amount, order_id, description)
            VALUES ($1, 'refund', $2, $3, $4)
            """, user_id, amount, order_id, description)


# ---------- DAILY LIMIT ----------
async def check_daily_order_limit(user_id: int):
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT daily_limit, daily_orders_count, last_order_date FROM users WHERE user_id=$1",
            user_id
        )
        if not user:
            return False

        await conn.execute("""
        UPDATE users SET daily_orders_count = daily_orders_count + 1
        WHERE user_id=$1
        """, user_id)

        return user["daily_orders_count"] < user["daily_limit"]


async def get_user_daily_info(user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
        SELECT daily_limit, daily_orders_count FROM users WHERE user_id=$1
        """, user_id)

        if not row:
            return 0, 0

        return row["daily_limit"], row["daily_orders_count"]


# ---------- CATEGORIES ----------
async def get_all_categories():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM categories ORDER BY id")
        return [dict(r) for r in rows]


async def get_category_by_id(cat_id):
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM categories WHERE id=$1", cat_id
        )
        return dict(r) if r else None


# ---------- CHANNELS ----------
async def get_all_channels(category_id=None):
    async with pool.acquire() as conn:
        if category_id:
            rows = await conn.fetch(
                "SELECT * FROM channels WHERE category_id=$1", category_id
            )
        else:
            rows = await conn.fetch("SELECT * FROM channels")

        return {
            r["id"]: {
                "name": r["name"],
                "price": r["price"],
                "subscribers": r["subscribers"],
                "url": r["url"],
                "description": r["description"],
                "category_id": r["category_id"]
            }
            for r in rows
        }


# alias (у тебя в коде встречается get_channel)
async def get_channel(channel_id):
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM channels WHERE id=$1", channel_id
        )
        return dict(r) if r else None


async def add_channel(ch_id, name, price, subs, url, desc="", category_id=None):
    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO channels (id, name, price, subscribers, url, description, category_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (id) DO UPDATE SET
        name=$2, price=$3, subscribers=$4, url=$5, description=$6, category_id=$7
        """, ch_id, name, price, subs, url, desc, category_id)


async def update_channel(ch_id, **kwargs):
    async with pool.acquire() as conn:
        for k, v in kwargs.items():
            await conn.execute(
                f"UPDATE channels SET {k}=$1 WHERE id=$2", v, ch_id
            )


async def delete_channel(ch_id):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM channels WHERE id=$1", ch_id)


# ---------- ORDERS ----------
async def save_order(user_id, username, cart, total, budget, contact, status="new"):
    async with pool.acquire() as conn:
        return await conn.fetchval("""
        INSERT INTO orders (user_id, username, cart, total, budget, contact, status)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        RETURNING id
        """, user_id, username, json.dumps(cart), total, budget, contact, status)


async def get_orders(limit=50):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
        SELECT * FROM orders ORDER BY id DESC LIMIT $1
        """, limit)
        return [dict(r) for r in rows]


async def get_orders_by_user(user_id, limit=10):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
        SELECT * FROM orders WHERE user_id=$1 ORDER BY id DESC LIMIT $2
        """, user_id, limit)

        for r in rows:
            r = dict(r)
            r["cart"] = json.loads(r["cart"])
            yield r


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
