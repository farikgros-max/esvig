import os
import asyncio
import json
import sqlite3
import hashlib
import requests
import traceback
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Update
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

# ------------------ БАЗА ДАННЫХ ------------------
def init_db():
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            subscribers INTEGER NOT NULL,
            url TEXT NOT NULL,
            description TEXT DEFAULT ''
        )
    ''')
    cur.execute("PRAGMA table_info(channels)")
    cols = [c[1] for c in cur.fetchall()]
    if 'description' not in cols:
        cur.execute('ALTER TABLE channels ADD COLUMN description TEXT DEFAULT ""')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            cart TEXT,
            total INTEGER,
            budget INTEGER,
            contact TEXT,
            status TEXT DEFAULT 'в обработке',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute("PRAGMA table_info(orders)")
    cols = [c[1] for c in cur.fetchall()]
    if 'status' not in cols:
        cur.execute('ALTER TABLE orders ADD COLUMN status TEXT DEFAULT "в обработке"')
    conn.commit()
    conn.close()

def get_all_channels():
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    cur.execute('SELECT id, name, price, subscribers, url, description FROM channels')
    rows = cur.fetchall()
    ch = {}
    for r in rows:
        ch[r[0]] = {"name": r[1], "price": r[2], "subscribers": r[3], "url": r[4], "description": r[5] or ""}
    conn.close()
    return ch

def add_channel(ch_id, name, price, subscribers, url, description=""):
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO channels VALUES (?,?,?,?,?,?)', (ch_id, name, price, subscribers, url, description))
    conn.commit()
    conn.close()

def delete_channel(ch_id):
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    cur.execute('DELETE FROM channels WHERE id = ?', (ch_id,))
    conn.commit()
    conn.close()

def update_channel(ch_id, name=None, price=None, subscribers=None, url=None, description=None):
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    if name is not None: cur.execute('UPDATE channels SET name = ? WHERE id = ?', (name, ch_id))
    if price is not None: cur.execute('UPDATE channels SET price = ? WHERE id = ?', (price, ch_id))
    if subscribers is not None: cur.execute('UPDATE channels SET subscribers = ? WHERE id = ?', (subscribers, ch_id))
    if url is not None: cur.execute('UPDATE channels SET url = ? WHERE id = ?', (url, ch_id))
    if description is not None: cur.execute('UPDATE channels SET description = ? WHERE id = ?', (description, ch_id))
    conn.commit()
    conn.close()

def save_order(user_id, username, cart, total, budget, contact, status='в обработке'):
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    cart_json = json.dumps(cart)
    cur.execute('INSERT INTO orders (user_id, username, cart, total, budget, contact, status) VALUES (?,?,?,?,?,?,?)',
                (user_id, username, cart_json, total, budget, contact, status))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id

def get_orders(limit=20):
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    cur.execute('SELECT id, user_id, username, cart, total, budget, contact, status, created_at FROM orders ORDER BY created_at DESC LIMIT ?', (limit,))
    rows = cur.fetchall()
    orders = []
    for r in rows:
        orders.append({"id": r[0], "user_id": r[1], "username": r[2], "cart": json.loads(r[3]), "total": r[4], "budget": r[5], "contact": r[6], "status": r[7], "created_at": r[8]})
    conn.close()
    return orders

def get_orders_by_user(user_id, limit=5):
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    cur.execute('SELECT id, total, cart, status, created_at FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT ?', (user_id, limit))
    rows = cur.fetchall()
    orders = []
    for r in rows:
        orders.append({"id": r[0], "total": r[1], "cart": json.loads(r[2]), "status": r[3], "created_at": r[4]})
    conn.close()
    return orders

def update_order_status(order_id, new_status):
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    cur.execute('UPDATE orders SET status = ? WHERE id = ?', (new_status, order_id))
    conn.commit()
    conn.close()

def get_order_by_id(order_id):
    conn = sqlite3.connect('channels.db')
    cur = conn.cursor()
    cur.execute('SELECT id, user_id, username, total, status FROM orders WHERE id = ?', (order_id,))
    r = cur.fetchone()
    conn.close()
    if r:
        return {"id": r[0], "user_id": r[1], "username": r[2], "total": r[3], "status": r[4]}
    return None

init_db()

# ------------------ СОСТОЯНИЯ FSM ------------------
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

# ------------------ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ------------------
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

# ------------------ КЛАВИАТУРЫ ------------------
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Каталог каналов", callback_data="view_catalog_page_0"), InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")],
        [InlineKeyboardButton(text="📞 Оформить заявку", callback_data="checkout"), InlineKeyboardButton(text="👤 Мой профиль", callback_data="my_profile")],
        [InlineKeyboardButton(text="ℹ️ О сервисе", callback_data="about"), InlineKeyboardButton(text="❓ FAQ", callback_data="faq")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="contacts")]
    ])

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
    total = (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    if page < 0: page = 0
    if page >= total: page = total - 1
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    buttons = []
    for ch_id, info in items[start:end]:
        buttons.append([InlineKeyboardButton(text=f"{info['name']} ({info['subscribers']} подп., {info['price']}$)", callback_data=f"view_{ch_id}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"view_catalog_page_{page-1}"))
    if page < total - 1: nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"view_catalog_page_{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons), page, total

def get_channel_view_keyboard(ch_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в корзину", callback_data=f"add_{ch_id}")],
        [InlineKeyboardButton(text="🔙 Назад в каталог", callback_data="view_catalog_page_0")]
    ])

def get_cart_keyboard(uid):
    cart = get_cart(uid)
    if not cart: return None
    buttons = []
    for idx, item in enumerate(cart):
        buttons.append([InlineKeyboardButton(text=f"❌ Удалить {item['name']} ({item['price']}$)", callback_data=f"remove_{idx}")])
    buttons.append([InlineKeyboardButton(text="💳 Перейти к оформлению", callback_data="checkout")])
    buttons.append([InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="clear_cart")])
    buttons.append([InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")]])

def get_admin_list_keyboard():
    if not channels: return None
    buttons = []
    for ch_id, info in channels.items():
        buttons.append([InlineKeyboardButton(text=f"{info['name']} | {info['price']}$ | {info['subscribers']} подп.", callback_data=f"admin_view_{ch_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_remove_keyboard():
    if not channels: return None
    buttons = []
    for ch_id, info in channels.items():
        buttons.append([InlineKeyboardButton(text=f"❌ {info['name']} ({info['price']}$)", callback_data=f"admin_del_{ch_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_orders_keyboard(orders):
    if not orders: return None
    buttons = []
    for o in orders:
        emoji = {'в обработке': '🟡', 'оплачена': '🟢', 'выполнена': '✅', 'отменена': '❌'}.get(o['status'], '⚪')
        buttons.append([InlineKeyboardButton(text=f"{emoji} #{o['id']} | {o['username']} | {o['total']}$ | {o['status']}", callback_data=f"admin_order_{o['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_edit_channel_keyboard(ch_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"edit_{ch_id}_name")],
        [InlineKeyboardButton(text="✏️ Цена", callback_data=f"edit_{ch_id}_price")],
        [InlineKeyboardButton(text="✏️ Охват", callback_data=f"edit_{ch_id}_subscribers")],
        [InlineKeyboardButton(text="✏️ Ссылка", callback_data=f"edit_{ch_id}_url")],
        [InlineKeyboardButton(text="✏️ Описание", callback_data=f"edit_{ch_id}_description")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_view_{ch_id}")]
    ])

def get_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мои заявки", callback_data="my_orders")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")]
    ])

# ------------------ ОБРАБОТЧИКИ БОТА (все ваши, но сокращены для краткости) ------------------
async def register_handlers(dp: Dispatcher):
    @dp.message(Command("start"))
    async def cmd_start(m: Message):
        await m.answer("🤖 Добро пожаловать в ESVIG Service! Используйте кнопки меню.", reply_markup=get_main_keyboard())

    @dp.message(Command("admin"))
    async def cmd_admin(m: Message):
        if m.from_user.id in ADMIN_IDS:
            await m.answer("👑 Админ-панель", reply_markup=get_admin_keyboard())
        else:
            await m.answer("У вас нет прав.")

    @dp.callback_query(F.data == "admin_back")
    async def admin_back(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        await cb.message.edit_text("👑 Админ-панель", reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_orders")
    async def admin_orders(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        orders = get_orders(20)
        if not orders: await cb.message.edit_text("📭 Заявок пока нет.", reply_markup=get_back_keyboard()); await cb.answer(); return
        await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(orders))
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_order_"))
    async def admin_view_order(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        order_id = int(cb.data.split("_")[2])
        order = get_order_by_id(order_id)
        if not order: await cb.answer("Заявка не найдена", show_alert=True); return
        emoji = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}.get(order['status'],'⚪')
        text = f"📄 Заявка #{order['id']}\n👤 @{order['username']}\n💰 Сумма: {order['total']}$\n📌 Статус: {emoji} {order['status']}\n\nВыберите новый статус:"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟡 В обработке", callback_data=f"set_status_{order_id}_в обработке")],
            [InlineKeyboardButton(text="🟢 Оплачена", callback_data=f"set_status_{order_id}_оплачена")],
            [InlineKeyboardButton(text="✅ Выполнена", callback_data=f"set_status_{order_id}_выполнена")],
            [InlineKeyboardButton(text="❌ Отменена", callback_data=f"set_status_{order_id}_отменена")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_orders")]
        ])
        await cb.message.edit_text(text, reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("set_status_"))
    async def set_status(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        parts = cb.data.split("_")
        order_id = int(parts[2])
        new_status = "_".join(parts[3:])
        update_order_status(order_id, new_status)
        await cb.answer(f"✅ Статус заявки #{order_id} изменён на {new_status}", show_alert=False)
        order = get_order_by_id(order_id)
        if order:
            try:
                await cb.bot.send_message(order['user_id'], f"📢 Статус вашей заявки #{order_id} изменён на: {new_status}")
            except: pass
        orders = get_orders(20)
        await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(orders))

    @dp.callback_query(F.data == "admin_list")
    async def admin_list(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        await load_channels()
        if not channels: await cb.message.edit_text("📭 Список каналов пуст.", reply_markup=get_back_keyboard()); await cb.answer(); return
        await cb.message.edit_text("📋 Список каналов\n\nНажмите на канал для подробностей:", reply_markup=get_admin_list_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_view_"))
    async def admin_view_channel(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        await load_channels()
        ch_id = cb.data.replace("admin_view_", "")
        ch = channels.get(ch_id)
        if not ch: await cb.answer("Канал не найден", show_alert=True); return
        text = f"📌 {ch['name']}\n🔗 {ch['url']}\n💰 {ch['price']}$\n👥 {ch['subscribers']} подп.\n📝 {ch.get('description','Нет описания')}\n🆔 {ch_id}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_channel_{ch_id}")],[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_list")]])
        await cb.message.edit_text(text, reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("edit_channel_"))
    async def edit_channel_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        ch_id = cb.data.replace("edit_channel_", "")
        await load_channels()
        if ch_id not in channels: await cb.answer("Канал не найден", show_alert=True); return
        await cb.message.edit_text(f"Редактирование канала {channels[ch_id]['name']}\nВыберите, что изменить:", reply_markup=get_edit_channel_keyboard(ch_id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("edit_") & ~F.data.startswith("edit_channel_"))
    async def edit_channel_field(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        parts = cb.data.split("_",2)
        if len(parts)<3: await cb.answer("Ошибка", show_alert=True); return
        ch_id, field = parts[1], parts[2]
        await load_channels()
        if ch_id not in channels: await cb.answer("Канал не найден", show_alert=True); return
        await state.update_data(ch_id=ch_id, field=field)
        prompts = {'name':'Введите новое название:','price':'Введите новую цену (число):','subscribers':'Введите новый охват (число):','url':'Введите новую ссылку (https://t.me/...):','description':'Введите новое описание:'}
        await cb.message.edit_text(prompts.get(field,"Введите значение:"))
        if field=='name': await state.set_state(EditChannelStates.waiting_for_name)
        elif field=='price': await state.set_state(EditChannelStates.waiting_for_price)
        elif field=='subscribers': await state.set_state(EditChannelStates.waiting_for_subscribers)
        elif field=='url': await state.set_state(EditChannelStates.waiting_for_url)
        elif field=='description': await state.set_state(EditChannelStates.waiting_for_description)
        await cb.answer()

    @dp.message(EditChannelStates.waiting_for_name)
    async def edit_name(m: Message, state: FSMContext):
        data = await state.get_data()
        update_channel(data['ch_id'], name=m.text)
        await load_channels()
        await m.answer(f"✅ Название изменено на {m.text}")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_price)
    async def edit_price(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        data = await state.get_data()
        update_channel(data['ch_id'], price=int(m.text))
        await load_channels()
        await m.answer(f"✅ Цена изменена на {m.text}$")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_subscribers)
    async def edit_subs(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        data = await state.get_data()
        update_channel(data['ch_id'], subscribers=int(m.text))
        await load_channels()
        await m.answer(f"✅ Охват изменён на {m.text}")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_url)
    async def edit_url(m: Message, state: FSMContext):
        url = m.text.strip()
        if not url.startswith("https://t.me/"): await m.answer("Ссылка должна начинаться с https://t.me/"); return
        data = await state.get_data()
        update_channel(data['ch_id'], url=url)
        await load_channels()
        await m.answer(f"✅ Ссылка изменена на {url}")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_description)
    async def edit_desc(m: Message, state: FSMContext):
        data = await state.get_data()
        update_channel(data['ch_id'], description=m.text)
        await load_channels()
        await m.answer("✅ Описание изменено")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.callback_query(F.data == "admin_remove")
    async def admin_remove_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        await load_channels()
        if not channels: await cb.message.edit_text("Нет каналов для удаления.", reply_markup=get_back_keyboard()); await cb.answer(); return
        await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_del_"))
    async def admin_delete_channel(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        ch_id = cb.data.replace("admin_del_", "")
        await load_channels()
        if ch_id in channels:
            name = channels[ch_id]['name']
            delete_channel(ch_id)
            await load_channels()
            await cb.answer(f"✅ Канал {name} удалён", show_alert=False)
            if not channels: await cb.message.edit_text("Все каналы удалены.", reply_markup=get_back_keyboard())
            else: await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard())
        else: await cb.answer("Канал не найден", show_alert=True)

    @dp.callback_query(F.data == "admin_add")
    async def admin_add_start(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        await cb.message.edit_text("➕ Добавление канала\n\nВведите название:")
        await state.set_state(AddChannelStates.waiting_for_name)
        await cb.answer()

    @dp.message(AddChannelStates.waiting_for_name)
    async def add_name(m: Message, state: FSMContext):
        await state.update_data(name=m.text)
        await m.answer("Введите цену (число):")
        await state.set_state(AddChannelStates.waiting_for_price)

    @dp.message(AddChannelStates.waiting_for_price)
    async def add_price(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        await state.update_data(price=int(m.text))
        await m.answer("Введите охват (число):")
        await state.set_state(AddChannelStates.waiting_for_subscribers)

    @dp.message(AddChannelStates.waiting_for_subscribers)
    async def add_subs(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        await state.update_data(subscribers=int(m.text))
        await m.answer("Введите ссылку (https://t.me/...):")
        await state.set_state(AddChannelStates.waiting_for_url)

    @dp.message(AddChannelStates.waiting_for_url)
    async def add_url(m: Message, state: FSMContext):
        url = m.text.strip()
        if not url.startswith("https://t.me/"): await m.answer("Ссылка должна начинаться с https://t.me/"); return
        await state.update_data(url=url)
        await m.answer("Введите описание канала:")
        await state.set_state(AddChannelStates.waiting_for_description)

    @dp.message(AddChannelStates.waiting_for_description)
    async def add_desc(m: Message, state: FSMContext):
        data = await state.get_data()
        await load_channels()
        new_id = f"channel_{len(channels)+1}"
        add_channel(new_id, data['name'], data['price'], data['subscribers'], data['url'], m.text)
        await load_channels()
        await m.answer(f"✅ Канал {data['name']} добавлен!")
        await state.clear()
        await m.answer("Вернуться в админ-панель:", reply_markup=get_admin_keyboard())

    @dp.callback_query(F.data == "back_to_main")
    async def back_to_main(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.message.edit_text("Главное меню:", reply_markup=get_main_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("view_catalog_page_"))
    async def view_catalog_page(cb: CallbackQuery):
        await load_channels()
        page = int(cb.data.split("_")[-1])
        kb, cur, total = get_catalog_keyboard(page)
        await cb.message.edit_text(f"📢 Наши каналы (страница {cur+1}/{total})\n\nНажмите на канал для деталей:", reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data == "view_cart")
    async def view_cart(cb: CallbackQuery):
        cart = get_cart(cb.from_user.id)
        if not cart:
            await cb.message.edit_text("🛒 Корзина пуста.", reply_markup=get_back_keyboard())
            await cb.answer()
            return
        total = sum(i['price'] for i in cart)
        text = "🛒 Ваша корзина:\n\n" + "\n".join(f"{i+1}. {item['name']} — {item['price']}$" for i,item in enumerate(cart)) + f"\n\nИтого: {total}$"
        await cb.message.edit_text(text, reply_markup=get_cart_keyboard(cb.from_user.id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("view_") & ~F.data.startswith("view_cart"))
    async def view_channel_details(cb: CallbackQuery):
        ch_id = cb.data.replace("view_", "")
        all_channels = get_all_channels()
        info = all_channels.get(ch_id)
        if not info:
            await cb.answer(f"Канал не найден (ID={ch_id})", show_alert=True)
            return
        text = f"📌 {info['name']}\n👥 Подписчиков: {info['subscribers']}\n💰 Цена: {info['price']}$\n🔗 Ссылка: {info['url']}\n📝 Описание:\n{info.get('description','Нет описания')}"
        await cb.message.edit_text(text, reply_markup=get_channel_view_keyboard(ch_id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("add_"))
    async def add_to_cart(cb: CallbackQuery):
        ch_id = cb.data.replace("add_", "")
        all_channels = get_all_channels()
        info = all_channels.get(ch_id)
        if not info:
            await cb.answer(f"Канал не найден (ID={ch_id})", show_alert=True)
            return
        cart = get_cart(cb.from_user.id)
        cart.append({"id": ch_id, "name": info['name'], "price": info['price']})
        save_cart(cb.from_user.id, cart)
        await cb.answer(f"✅ {info['name']} добавлен в корзину!", show_alert=False)

    @dp.callback_query(F.data == "clear_cart")
    async def clear_cart(cb: CallbackQuery):
        user_carts[cb.from_user.id] = []
        await cb.answer("🗑 Корзина очищена", show_alert=False)
        await cb.message.edit_text("🛒 Корзина пуста.", reply_markup=get_back_keyboard())

    @dp.callback_query(F.data.startswith("remove_"))
    async def remove_from_cart(cb: CallbackQuery):
        idx = int(cb.data.split("_")[1])
        cart = get_cart(cb.from_user.id)
        if 0 <= idx < len(cart):
            removed = cart.pop(idx)
            save_cart(cb.from_user.id, cart)
            await cb.answer(f"❌ {removed['name']} удалён", show_alert=False)
            if not cart:
                await cb.message.edit_text("🛒 Корзина пуста.", reply_markup=get_back_keyboard())
            else:
                total = sum(i['price'] for i in cart)
                text = "🛒 Ваша корзина:\n\n" + "\n".join(f"{i+1}. {item['name']} — {item['price']}$" for i,item in enumerate(cart)) + f"\n\nИтого: {total}$"
                await cb.message.edit_text(text, reply_markup=get_cart_keyboard(cb.from_user.id))
        else: await cb.answer("Ошибка", show_alert=True)

    @dp.callback_query(F.data == "checkout")
    async def checkout(cb: CallbackQuery, state: FSMContext):
        cart = get_cart(cb.from_user.id)
        if not cart:
            await cb.message.edit_text("🛒 Корзина пуста. Добавьте каналы перед оформлением.", reply_markup=get_back_keyboard())
            await cb.answer()
            return
        total = sum(i['price'] for i in cart)
        await state.update_data(cart=cart, total=total)
        await cb.message.edit_text(f"💳 Оформление заказа\n\nСумма: {total}$\nВведите ваш бюджет (цифрами, ≥ суммы):")
        await state.set_state(OrderForm.waiting_for_budget)
        await cb.answer()

    @dp.message(OrderForm.waiting_for_budget)
    async def process_budget(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        budget = int(m.text)
        data = await state.get_data()
        total = data.get("total",0)
        if budget < total:
            await m.answer(f"Бюджет ({budget}$) меньше суммы ({total}$). Введите {total}$ или больше:")
            return
        await state.update_data(budget=budget)
        await m.answer("Напишите ваш Telegram username (например, @username) или другой контакт:")
        await state.set_state(OrderForm.waiting_for_contact)

    @dp.message(OrderForm.waiting_for_contact)
    async def process_contact(m: Message, state: FSMContext):
        data = await state.get_data()
        cart = data.get("cart",[])
        total = data.get("total",0)
        budget = data.get("budget",0)
        contact = m.text.strip()
        username = m.from_user.username or "не указан"
        order_id = save_order(m.from_user.id, username, cart, total, budget, contact, status='в обработке')
        items_list = "\n".join(f"• {i['name']} — {i['price']}$" for i in cart)
        report = f"🟢 НОВАЯ ЗАЯВКА\n👤 @{username}\n📦 Состав:\n{items_list}\n💰 Сумма: {total}$\n💵 Бюджет: {budget}$\n📞 Контакт: {contact}"
        for admin_id in ADMIN_IDS:
            try: await m.bot.send_message(admin_id, report)
            except: pass
        user_carts[m.from_user.id] = []
        await m.answer("✅ Заявка отправлена! Менеджер свяжется с вами.", reply_markup=get_main_keyboard())
        await state.clear()

    @dp.callback_query(F.data == "my_profile")
    async def my_profile(cb: CallbackQuery):
        orders = get_orders_by_user(cb.from_user.id, 100)
        total_orders = len(orders)
        total_spent = sum(o['total'] for o in orders)
        text = f"👤 Мой профиль\n\n🆔 ID: {cb.from_user.id}\n📛 Username: @{cb.from_user.username or 'не указан'}\n📦 Всего заказов: {total_orders}\n💰 Общая сумма трат: {total_spent}$\n💳 Баланс: 0$ (пополнение временно недоступно)"
        await cb.message.edit_text(text, reply_markup=get_profile_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "deposit")
    async def deposit(cb: CallbackQuery):
        await cb.message.edit_text("💰 Пополнение баланса временно недоступно.\n\nСкоро мы добавим эту возможность. Следите за новостями!", reply_markup=get_back_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "my_orders")
    async def my_orders(cb: CallbackQuery):
        orders = get_orders_by_user(cb.from_user.id, 10)
        if not orders:
            await cb.message.edit_text("📭 У вас пока нет заявок.", reply_markup=get_back_keyboard())
            await cb.answer()
            return
        text = "📊 Ваши заявки:\n\n"
        for o in orders:
            emoji = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}.get(o['status'],'⚪')
            text += f"🆔 №{o['id']}\n💰 Сумма: {o['total']}$\n📦 Товаров: {len(o['cart'])}\n📌 Статус: {emoji} {o['status']}\n🕒 {o['created_at']}\n➖➖➖➖➖\n"
        await cb.message.edit_text(text, reply_markup=get_back_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "about")
    async def about(cb: CallbackQuery):
        await cb.message.edit_text("ℹ️ О сервисе ESVIG Service\n\nМы помогаем размещать рекламу в проверенных Telegram-каналах крипто-тематики.\n\n✅ Наши преимущества:\n• Только каналы с высокой вовлечённостью (ER > 2%)\n• Полная предоплата от рекламодателя\n• Отчёт по каждому размещению\n• Быстрая связь с администраторами каналов\n\nРаботаем с 2026 года. Без скама и хайпов.", reply_markup=get_back_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "faq")
    async def faq(cb: CallbackQuery):
        await cb.message.edit_text("❓ Часто задаваемые вопросы\n\n1️⃣ Как я могу оплатить рекламу?\n   Оплата принимается в USDT (TRC20 или BEP20). Вы переводите полную сумму нам, мы гарантируем размещение.\n\n2️⃣ Что если пост не выйдет?\n   Мы вернём 100% предоплаты. Случаев невыхода не было.\n\n3️⃣ Какой срок размещения?\n   Обычно пост выходит в течение 24 часов после оплаты.\n\n4️⃣ Могу ли я выбрать каналы сам?\n   Да, вы можете просмотреть каталог и добавить любые каналы в корзину.\n\n5️⃣ Как узнать статистику поста?\n   Через 24 часа после публикации мы пришлём вам отчёт: просмотры, реакции, ER.\n\n6️⃣ Как долго пост остаётся в канале?\n   Пост остаётся навсегда, если не указано иное.\n\n7️⃣ Есть ли скидки?\n   При заказе от 3 каналов – скидка 10%.\n\nПо остальным вопросам пишите @esvig_support.", reply_markup=get_back_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "contacts")
    async def contacts(cb: CallbackQuery):
        await cb.message.edit_text("📞 Контакты\n\nПо всем вопросам обращайтесь:\n• Telegram: @esvig_support\n• Email: support@esvig.com\n• Канал с новостями: @esvig_news\n\nОбычно отвечаем в течение 1–2 часов.", reply_markup=get_back_keyboard())
        await cb.answer()

# ------------------ FLASK ПРИЛОЖЕНИЕ С ЗАЩИТОЙ ------------------
flask_app = Flask(__name__)
app = flask_app

bot_instance = Bot(token=BOT_TOKEN)
dp_instance = Dispatcher(storage=MemoryStorage())

app.config['_started'] = False

@app.route('/webhook', methods=['POST'])
async def webhook():
    try:
        if not app.config['_started']:
            await load_channels()
            await register_handlers(dp_instance)
            app.config['_started'] = True
            print("Бот инициализирован и обработчики загружены.")
        
        # Проверка секретного токена
        secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if secret != SECRET_TOKEN:
            print(f"Неверный секретный токен: {secret}")
            return jsonify({'status': 'unauthorized'}), 401
        
        # Получаем данные от Telegram
        data = request.get_json()
        if not data:
            return jsonify({'status': 'no data'}), 400
        
        update = Update(**data)
        await dp_instance.feed_update(bot_instance, update)
    except Exception as e:
        print("Ошибка в вебхуке:")
        traceback.print_exc()
    finally:
        # Всегда отвечаем 200, чтобы Telegram не повторял запросы
        return jsonify({'status': 'ok'})

@app.route('/set_webhook', methods=['GET'])
async def set_webhook():
    webhook_url = "https://esvig-production.up.railway.app/webhook"
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
        json={"url": webhook_url, "secret_token": SECRET_TOKEN}
    )
    return jsonify({'status': 'ok', 'result': r.json()})

application = app
