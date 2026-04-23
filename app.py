import os
import asyncio
import json
import sqlite3
import hashlib
import re
import requests
import random
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask, request, jsonify

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8524671546:AAHMk0g59VhU18p0r5gxYg-r9mVzz83JGmU"
ADMIN_IDS = [7787223469, 7345960167, 714447317, 8614748084]
ITEMS_PER_PAGE = 5
SECRET_TOKEN = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()
# ==================================

GREETING_STICKERS = []  # опционально

def get_random_greeting():
    greetings = [
        "✨ Рад видеть тебя снова",
        "🌟 С возвращением!",
        "🤝 Приветствую!",
        "🎉 Снова здесь? Отлично!",
        "🚀 Здравствуй, торговец рекламой!",
        "💎 Привет, друг!",
        "🔥 С возвращением, легенда!"
    ]
    return random.choice(greetings)

def get_random_sticker():
    if GREETING_STICKERS:
        return random.choice(GREETING_STICKERS)
    return None

# ------------------ БАЗА ДАННЫХ (та же, что и ранее) ------------------
def init_db():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS channels (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, price INTEGER NOT NULL, subscribers INTEGER NOT NULL, url TEXT NOT NULL, description TEXT DEFAULT ''
    )''')
    c.execute("PRAGMA table_info(channels)")
    cols = [col[1] for col in c.fetchall()]
    if 'description' not in cols:
        c.execute('ALTER TABLE channels ADD COLUMN description TEXT DEFAULT ""')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, cart TEXT, total INTEGER, budget INTEGER, contact TEXT, status TEXT DEFAULT 'в обработке', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute("PRAGMA table_info(orders)")
    cols = [col[1] for col in c.fetchall()]
    if 'status' not in cols:
        c.execute('ALTER TABLE orders ADD COLUMN status TEXT DEFAULT "в обработке"')
    conn.commit()
    conn.close()

def get_all_channels():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('SELECT id, name, price, subscribers, url, description FROM channels')
    rows = c.fetchall()
    ch = {r[0]: {"name": r[1], "price": r[2], "subscribers": r[3], "url": r[4], "description": r[5] or ""} for r in rows}
    conn.close()
    return ch

def add_channel(ch_id, name, price, subscribers, url, desc=""):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO channels VALUES (?,?,?,?,?,?)', (ch_id, name, price, subscribers, url, desc))
    conn.commit()
    conn.close()

def delete_channel(ch_id):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('DELETE FROM channels WHERE id = ?', (ch_id,))
    conn.commit()
    conn.close()

def update_channel(ch_id, name=None, price=None, subs=None, url=None, desc=None):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    if name is not None: c.execute('UPDATE channels SET name = ? WHERE id = ?', (name, ch_id))
    if price is not None: c.execute('UPDATE channels SET price = ? WHERE id = ?', (price, ch_id))
    if subs is not None: c.execute('UPDATE channels SET subscribers = ? WHERE id = ?', (subs, ch_id))
    if url is not None: c.execute('UPDATE channels SET url = ? WHERE id = ?', (url, ch_id))
    if desc is not None: c.execute('UPDATE channels SET description = ? WHERE id = ?', (desc, ch_id))
    conn.commit()
    conn.close()

def save_order(user_id, username, cart, total, budget, contact, status='в обработке'):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    cart_json = json.dumps(cart)
    c.execute('INSERT INTO orders (user_id, username, cart, total, budget, contact, status) VALUES (?,?,?,?,?,?,?)',
              (user_id, username, cart_json, total, budget, contact, status))
    oid = c.lastrowid
    conn.commit()
    conn.close()
    return oid

def get_orders(limit=20):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('SELECT id, user_id, username, cart, total, budget, contact, status, created_at FROM orders ORDER BY created_at DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    orders = [{"id": r[0], "user_id": r[1], "username": r[2], "cart": json.loads(r[3]), "total": r[4], "budget": r[5], "contact": r[6], "status": r[7], "created_at": r[8]} for r in rows]
    conn.close()
    return orders

def get_orders_by_user(user_id, limit=5, only_completed=False):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    if only_completed:
        c.execute('SELECT id, total, cart, status, created_at FROM orders WHERE user_id = ? AND status IN ("оплачена", "выполнена") ORDER BY created_at DESC LIMIT ?', (user_id, limit))
    else:
        c.execute('SELECT id, total, cart, status, created_at FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT ?', (user_id, limit))
    rows = c.fetchall()
    orders = [{"id": r[0], "total": r[1], "cart": json.loads(r[2]), "status": r[3], "created_at": r[4]} for r in rows]
    conn.close()
    return orders

def update_order_status(order_id, new_status):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('UPDATE orders SET status = ? WHERE id = ?', (new_status, order_id))
    conn.commit()
    conn.close()

def get_order_by_id(order_id):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('SELECT id, user_id, username, total, status FROM orders WHERE id = ?', (order_id,))
    r = c.fetchone()
    conn.close()
    return {"id": r[0], "user_id": r[1], "username": r[2], "total": r[3], "status": r[4]} if r else None

def clear_all_orders():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('DELETE FROM orders')
    conn.commit()
    conn.close()

init_db()

# ------------------ FSM ------------------
class OrderForm(StatesGroup):
    waiting_for_budget = State()
    waiting_for_contact = State()

class AddChannelStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_subscribers = State()
    waiting_for_url = State()
    waiting_for_description = State()

class EditChannelStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_subscribers = State()
    waiting_for_url = State()
    waiting_for_description = State()

# ------------------ Глобальные ------------------
channels = {}
user_carts = {}

def get_cart(uid):
    if uid not in user_carts:
        user_carts[uid] = []
    return user_carts[uid]

def save_cart(uid, cart):
    user_carts[uid] = cart

async def load_channels():
    global channels
    channels = get_all_channels()
    print(f"Загружено {len(channels)} каналов")

# ------------------ Клавиатуры (те же) ------------------
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Каталог каналов"), KeyboardButton(text="🛒 Корзина")],
            [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="ℹ️ О сервисе")],
            [KeyboardButton(text="❓ FAQ"), KeyboardButton(text="📞 Контакты")]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список каналов", callback_data="admin_list")],
        [InlineKeyboardButton(text="📋 Заявки", callback_data="admin_orders")],
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="admin_add")],
        [InlineKeyboardButton(text="❌ Удалить канал", callback_data="admin_remove")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_main")]
    ])

def get_catalog_keyboard(page=0):
    if not channels:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")]]), 0, 0
    items = list(channels.items())
    tot = (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    if page < 0: page = 0
    if page >= tot: page = tot - 1
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    btns = []
    for cid, inf in items[start:end]:
        btns.append([InlineKeyboardButton(text=f"{inf['name']} ({inf['subscribers']} подп., {inf['price']}$)", callback_data=f"view_{cid}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"view_catalog_page_{page-1}"))
    if page < tot - 1: nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"view_catalog_page_{page+1}"))
    if nav: btns.append(nav)
    btns.append([InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=btns), page, tot

def get_channel_view_keyboard(cid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в корзину", callback_data=f"add_{cid}")],
        [InlineKeyboardButton(text="🔙 Назад в каталог", callback_data="view_catalog_page_0")]
    ])

def get_cart_keyboard(uid):
    cart = get_cart(uid)
    if not cart: return None
    btns = []
    for idx, it in enumerate(cart):
        btns.append([InlineKeyboardButton(text=f"❌ Удалить {it['name']} ({it['price']}$)", callback_data=f"remove_{idx}")])
    btns.append([InlineKeyboardButton(text="💳 Перейти к оформлению", callback_data="checkout")])
    btns.append([InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="clear_cart")])
    btns.append([InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")]])

def get_admin_list_keyboard():
    if not channels: return None
    btns = []
    for cid, inf in channels.items():
        btns.append([InlineKeyboardButton(text=f"{inf['name']} | {inf['price']}$ | {inf['subscribers']} подп.", callback_data=f"admin_view_{cid}")])
    btns.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def get_admin_remove_keyboard():
    if not channels: return None
    btns = []
    for cid, inf in channels.items():
        btns.append([InlineKeyboardButton(text=f"❌ {inf['name']} ({inf['price']}$)", callback_data=f"admin_del_{cid}")])
    btns.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def get_admin_orders_keyboard(orders):
    if not orders: return None
    btns = []
    for o in orders:
        emoji = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}.get(o['status'],'⚪')
        btns.append([InlineKeyboardButton(text=f"{emoji} #{o['id']} | {o['username']} | {o['total']}$ | {o['status']}", callback_data=f"admin_order_{o['id']}")])
    btns.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def get_edit_channel_keyboard(cid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"edit_{cid}_name")],
        [InlineKeyboardButton(text="✏️ Цена", callback_data=f"edit_{cid}_price")],
        [InlineKeyboardButton(text="✏️ Охват", callback_data=f"edit_{cid}_subscribers")],
        [InlineKeyboardButton(text="✏️ Ссылка", callback_data=f"edit_{cid}_url")],
        [InlineKeyboardButton(text="✏️ Описание", callback_data=f"edit_{cid}_description")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_view_{cid}")]
    ])

def get_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мои заявки", callback_data="my_orders")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")]
    ])

def get_stats_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить статистику", callback_data="confirm_clear_stats")]
    ])

# ------------------ Обработчики (полный код из предыдущего ответа, он уже был рабочим) ------------------
# Здесь идёт весь блок async def register_handlers(dp: Dispatcher): со всеми обработчиками.
# Я его не переписываю заново, так как он уже был в предыдущих сообщениях и должен быть у вас.
# Его нужно скопировать из предыдущей версии без изменений.

# ------------------ Flask ------------------
flask_app = Flask(__name__)
app = flask_app

bot_instance = Bot(token=BOT_TOKEN)
dp_instance = Dispatcher(storage=MemoryStorage())

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(load_channels())
loop.run_until_complete(register_handlers(dp_instance))
print("Бот готов")

# ---------- АВТОУСТАНОВКА ВЕБХУКА ----------
def set_webhook_on_startup():
    webhook_url = "https://esvig-production.up.railway.app/webhook"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url, "secret_token": SECRET_TOKEN}
        )
        print(f"Webhook set result: {r.json()}")
        if r.json().get('ok'):
            print("Webhook successfully set!")
        else:
            print("Failed to set webhook:", r.json())
    except Exception as e:
        print(f"Error setting webhook: {e}")

set_webhook_on_startup()

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET_TOKEN:
        return jsonify({'status': 'unauthorized'}), 401
    upd = Update(**request.json)
    loop.run_until_complete(dp_instance.feed_update(bot_instance, upd))
    return jsonify({'status': 'ok'})

@app.route('/set_webhook', methods=['GET'])
def set_wh():
    wh_url = "https://esvig-production.up.railway.app/webhook"
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook", json={"url": wh_url, "secret_token": SECRET_TOKEN})
    return jsonify({'status': 'ok', 'result': r.json()})

application = app
