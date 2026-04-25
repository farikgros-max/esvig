import asyncpg
import json
import os
import asyncio
from typing import Optional, Dict, List, Any

DATABASE_URL = os.environ.get("DATABASE_URL")
pool = None

# ---------- Вспомогательная функция для повторных попыток ----------
async def _retry_fetch(query: str, *args, fetch_all: bool = True, max_retries: int = 3, delay: float = 0.5):
    """Выполняет SELECT-запрос и повторяет, если результат пустой (для списков) или None (для одного значения)."""
    for attempt in range(max_retries):
        async with pool.acquire() as conn:
            if fetch_all:
                rows = await conn.fetch(query, *args)
                if rows:
                    return rows
            else:
                row = await conn.fetchrow(query, *args)
                if row is not None:
                    return row
        if attempt < max_retries - 1:
            await asyncio.sleep(delay * (attempt + 1))  # увеличиваем задержку с каждой попыткой
    # Если после всех попыток ничего не найдено, возвращаем пустой список/None
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args) if fetch_all else await conn.fetchrow(query, *args)

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
        # ... остальные таблицы без изменений ...
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
        # ... остальные таблицы ...
        # (оставьте все ваши CREATE TABLE как есть, они здесь не показаны для краткости, но обязательно должны быть)

        # Заполнение категорий по умолчанию (если пусто)
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
                'INSERT INTO categories (name, display_name) VALUES ($1, $2)',
                default_cats
            )

async def close_db():
    global pool
    if pool:
        await pool.close()
        pool = None

# ---------- Пользователи и баланс (функции без изменений, только добавим _retry где нужно) ----------
# ... все остальные функции из вашего database.py оставьте без изменений, кроме get_all_channels и get_all_categories, где мы применим _retry_fetch ...

# ---------- Категории ----------
async def get_all_categories():
    rows = await _retry_fetch('SELECT id, name, display_name FROM categories ORDER BY id', fetch_all=True)
    return [{"id": r['id'], "name": r['name'], "display_name": r['display_name']} for r in rows]

# ---------- Каналы ----------
async def get_all_channels(category_id=None):
    if category_id is not None:
        rows = await _retry_fetch(
            'SELECT id, name, price, subscribers, url, description, category_id FROM channels WHERE category_id = $1',
            category_id, fetch_all=True
        )
    else:
        rows = await _retry_fetch(
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

# ---------- Заказы и всё остальное оставьте вашим кодом без изменений ----------
# ... вставьте сюда все остальные функции из вашего database.py, которые я не показал (пользователи, заказы, статистика и т.д.)
# Они должны остаться точно такими же, кроме тех мест, где вы хотите применить _retry_fetch.
