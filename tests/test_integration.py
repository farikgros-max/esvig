import pytest
import asyncpg
import os
from datetime import date, timedelta

# Используем отдельную тестовую БД, чтобы не трогать основную
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgres://esvig_user:esvig_pass@localhost:5432/esvig_test")

@pytest.mark.asyncio
async def test_full_cycle_order_and_cancel():
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    # Создаём таблицы, если их нет (как в основной)
    await conn.execute("""
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
        );
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            subscribers INTEGER NOT NULL,
            url TEXT NOT NULL,
            description TEXT DEFAULT '',
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
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
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            order_id INTEGER REFERENCES orders(id),
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS carts (
            user_id BIGINT PRIMARY KEY,
            items JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS slot_bookings (
            id SERIAL PRIMARY KEY,
            channel_id TEXT NOT NULL,
            seller_user_id BIGINT NOT NULL,
            date DATE NOT NULL,
            booked_by BIGINT,
            status TEXT DEFAULT 'free',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(channel_id, date)
        );
    """)
    # Очищаем таблицы (безопасно, это тестовая база)
    await conn.execute("DELETE FROM orders; DELETE FROM transactions; DELETE FROM carts; DELETE FROM slot_bookings; DELETE FROM users; DELETE FROM channels; DELETE FROM categories;")
    # Наполняем тестовыми данными
    await conn.execute("INSERT INTO users (user_id, username, balance, daily_limit, daily_orders_count, last_order_date) VALUES ($1, $2, $3, $4, $5, $6)", 999, "testuser", 1000, 5, 0, date.today())
    await conn.execute("INSERT INTO categories (name, display_name) VALUES ('testcat', 'Тестовая категория') ON CONFLICT DO NOTHING")
    await conn.execute("INSERT INTO channels (id, name, price, subscribers, url, description, category_id, active) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)", "ch1", "Test Channel", 100, 1000, "https://t.me/test", "Тестовый канал", 1, True)
    await conn.execute("INSERT INTO slot_bookings (channel_id, seller_user_id, date, status) VALUES ($1, $2, $3, 'free')", "ch1", 123, date.today() + timedelta(days=1))

    # Импортируем реальные функции (они будут использовать TEST_DATABASE_URL, если мы временно подменим DATABASE_URL)
    # Чтобы не менять глобальные переменные, мы протестируем логику, вызывая функции напрямую с переданным соединением?
    # Но наши функции используют глобальный пул. Для теста подменим DATABASE_URL
    import database
    original_url = database.DATABASE_URL
    database.DATABASE_URL = TEST_DATABASE_URL
    # Принудительно сбросим пул, чтобы он пересоздался с новым URL
    database._pool = None
    database._channels_dict = {}

    try:
        from database import (
            save_order, get_order_by_id, update_order_status, return_balance, release_slot,
            get_user_balance, get_free_slots, debit_balance, book_slot
        )

        # 1. Создаём заказ
        cart = [{"id": "ch1", "name": "Test Channel", "price": 100, "date": str(date.today() + timedelta(days=1))}]
        order_id = await save_order(999, "testuser", cart, 100, 100, "", "в обработке")

        # 2. Оплата
        success = await debit_balance(999, 100, order_id, "Оплата заказа")
        assert success, "Списание не удалось"
        await update_order_status(order_id, "оплачена")
        for item in cart:
            if 'date' in item and item['date']:
                await book_slot(item['id'], item['date'], 999)

        free_slots = await get_free_slots("ch1")
        assert str(date.today() + timedelta(days=1)) not in free_slots, "Слот должен быть занят"

        # 3. Отмена
        order = await get_order_by_id(order_id)
        await update_order_status(order_id, "отменена")
        await return_balance(order['user_id'], order['total'], order_id, "Возврат")
        for item in order['cart']:
            if 'date' in item and item['date'] and item.get('id'):
                await release_slot(item['id'], item['date'])

        balance = await get_user_balance(999)
        assert balance == 1000, f"Баланс должен быть 1000, а сейчас {balance}"

        free_slots = await get_free_slots("ch1")
        assert str(date.today() + timedelta(days=1)) in free_slots, "Слот должен быть снова свободен"

    finally:
        # Восстанавливаем оригинальный URL и сбрасываем пул
        database.DATABASE_URL = original_url
        database._pool = None
        database._channels_dict = {}

    await conn.close()
