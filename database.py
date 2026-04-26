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

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            cart TEXT,
            total INTEGER,
            budget INTEGER,
            contact TEXT,
            status TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """)

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


# ================= USERS =================
async def get_or_create_user(user_id: int, username: str = None):
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id=$1",
            user_id
        )

        if not user:
            await conn.execute("""
                INSERT INTO users (user_id, username, balance, daily_limit, daily_orders_count, last_order_date)
                VALUES ($1, $2, 0, 3, 0, CURRENT_DATE)
            """, user_id, username)

            return {
                "user_id": user_id,
                "username": username,
                "balance": 0,
                "daily_limit": 3,
                "daily_orders_count": 0
            }

        return dict(user)


async def get_user_balance(user_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT balance FROM users WHERE user_id=$1",
            user_id
        ) or 0


async def update_user_balance(user_id: int, amount: int, description: str = ""):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, balance)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET balance = users.balance + $2
        """, user_id, amount)


async def debit_balance(user_id: int, amount: int, order_id: int, description=""):
    async with pool.acquire() as conn:
        balance = await conn.fetchval(
            "SELECT balance FROM users WHERE user_id=$1",
            user_id
        )

        if balance is None or balance < amount:
            return False

        await conn.execute("""
            UPDATE users
            SET balance = balance - $1
            WHERE user_id=$2
        """, amount, user_id)

        return True


# ================= DAILY LIMIT =================
async def check_daily_order_limit(user_id: int):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("""
            SELECT daily_limit, daily_orders_count, last_order_date
            FROM users WHERE user_id=$1
        """, user_id)

        if not user:
            return False

        today = await conn.fetchval("SELECT CURRENT_DATE")

        if user["last_order_date"] != today:
            await conn.execute("""
                UPDATE users
                SET daily_orders_count = 0, last_order_date = CURRENT_DATE
                WHERE user_id=$1
            """, user_id)
            return True

        if user["daily_orders_count"] >= user["daily_limit"]:
            return False

        await conn.execute("""
            UPDATE users
            SET daily_orders_count = daily_orders_count + 1,
                last_order_date = CURRENT_DATE
            WHERE user_id=$1
        """, user_id)

        return True


async def get_user_daily_info(user_id: int):
    async with pool.acquire() as conn:
        r = await conn.fetchrow("""
            SELECT daily_limit, daily_orders_count
            FROM users WHERE user_id=$1
        """, user_id)

        if not r:
            return 0, 0

        return r["daily_limit"], r["daily_orders_count"]


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


get_all_channels = get_channels


async def get_channel(channel_id: str):
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM channels WHERE id=$1",
            channel_id
        )
        return dict(r) if r else None


# ================= CATEGORIES =================
async def get_categories():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM categories ORDER BY id")
        return [
            {"id": r["id"], "name": r["name"], "display_name": r["display_name"]}
            for r in rows
        ]


get_all_categories = get_categories


# ================= ORDERS =================
async def save_order(user_id, username, cart, total, budget, contact, status):
    async with pool.acquire() as conn:
        order_id = await conn.fetchval("""
            INSERT INTO orders (user_id, username, cart, total, budget, contact, status)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING id
        """, user_id, username, json.dumps(cart), total, budget, contact, status)

        return order_id


async def update_order_status(order_id: int, status: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE orders SET status=$1 WHERE id=$2",
            status, order_id
        )


async def get_order_by_id(order_id: int):
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", order_id)

        if not r:
            return None

        data = dict(r)
        data["cart"] = json.loads(data["cart"])
        return data


async def get_orders_by_user(user_id: int, limit: int = 5):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM orders
            WHERE user_id=$1
            ORDER BY created_at DESC
            LIMIT $2
        """, user_id, limit)

        return [
            {
                "id": r["id"],
                "total": r["total"],
                "status": r["status"],
                "cart": json.loads(r["cart"]),
                "created_at": str(r["created_at"])
            }
            for r in rows
        ]


# ================= COMPAT (страховка от старых импортов) =================
update_balance = update_user_balance
