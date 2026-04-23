import os
import asyncio
import json
import sqlite3
import hashlib
import re
import requests
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

def escape_md(text):
    if not text: return ""
    esc = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(esc), r'\\\1', str(text))

# ------------------ БАЗА ДАННЫХ ------------------
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

def get_orders_by_user(user_id, limit=5):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
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

# ------------------ Клавиатуры ------------------
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

# ------------------ Обработчики ------------------
async def register_handlers(dp: Dispatcher):
    @dp.message(Command("start"))
    async def start(m: Message):
        await m.answer("🤖 Добро пожаловать в ESVIG Service!\n\nМы помогаем размещать рекламу в проверенных Telegram-каналах крипто-тематики.\n\nИспользуйте кнопки ниже.", reply_markup=get_main_keyboard())

    @dp.message(Command("admin"))
    async def admin(m: Message):
        if m.from_user.id in ADMIN_IDS:
            await m.answer("👑 Админ-панель", reply_markup=get_admin_keyboard())
        else:
            await m.answer("Нет прав")

    @dp.message(Command("stats"))
    async def stats(m: Message):
        if m.from_user.id not in ADMIN_IDS:
            await m.answer("Нет прав")
            return
        conn = sqlite3.connect('channels.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(total) FROM orders")
        tot_ord, tot_sum = c.fetchone()
        tot_sum = tot_sum or 0
        c.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
        stat = c.fetchall()
        c.execute("SELECT COUNT(*) FROM channels")
        chan_cnt = c.fetchone()[0]
        c.execute("SELECT DATE(created_at), COUNT(*), SUM(total) FROM orders WHERE created_at >= DATE('now','-7 days') GROUP BY DATE(created_at) ORDER BY DATE(created_at) ASC")
        week = c.fetchall()
        conn.close()
        txt = f"📊 Статистика ESVIG Service\n\n📦 Всего заявок: {tot_ord}\n💰 Общая сумма: {tot_sum}$\n📋 Каналов: {chan_cnt}\n\n🔄 По статусам:\n"
        em = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}
        for st, cnt in stat:
            txt += f"{em.get(st,'⚪')} {st}: {cnt}\n"
        if week:
            txt += "\n📅 Последние 7 дней:\n"
            for d, cnt, s in week:
                txt += f"{d}: {cnt} заявок, {s or 0}$\n"
        else:
            txt += "\n📭 За последние 7 дней заявок нет."
        await m.answer(txt)

    @dp.message(F.text == "📋 Каталог каналов")
    async def cat(m: Message):
        await load_channels()
        if not channels:
            await m.answer("Каталог пуст")
            return
        kb, pg, total = get_catalog_keyboard(0)
        await m.answer(f"📢 Наши каналы (страница 1/{total})\nНажмите на канал для деталей:", reply_markup=kb)

    @dp.message(F.text == "🛒 Корзина")
    async def cart(m: Message):
        c = get_cart(m.from_user.id)
        if not c:
            await m.answer("Корзина пуста")
            return
        total = sum(i['price'] for i in c)
        txt = "🛒 Ваша корзина:\n\n" + "\n".join(f"{idx+1}. {i['name']} — {i['price']}$" for idx,i in enumerate(c)) + f"\n\nИтого: {total}$"
        await m.answer(txt, reply_markup=get_cart_keyboard(m.from_user.id))

    @dp.message(F.text == "👤 Мой профиль")
    async def profile(m: Message):
        orders = get_orders_by_user(m.from_user.id, 100)
        tot_ord = len(orders)
        tot_spent = sum(o['total'] for o in orders)
        txt = f"👤 Мой профиль\n\n🆔 ID: {m.from_user.id}\n📛 Username: @{m.from_user.username or 'не указан'}\n📦 Всего заказов: {tot_ord}\n💰 Общая сумма трат: {tot_spent}$\n💳 Баланс: 0$ (пополнение временно недоступно)"
        await m.answer(txt, reply_markup=get_profile_keyboard())

    @dp.message(F.text == "ℹ️ О сервисе")
    async def about(m: Message):
        txt = "ℹ️ О сервисе ESVIG Service\n\nМы помогаем рекламодателям размещать посты в проверенных Telegram-каналах крипто-тематики.\n\n✅ Наши преимущества:\n• Только каналы с высокой вовлечённостью (ER > 2%)\n• Полная предоплата от рекламодателя\n• Отчёт по каждому размещению\n• Быстрая связь с администраторами каналов\n\n📌 Работаем с 2026 года."
        await m.answer(txt)

    @dp.message(F.text == "❓ FAQ")
    async def faq(m: Message):
        txt = "❓ Часто задаваемые вопросы\n\n1️⃣ Как я могу оплатить рекламу?\n   Оплата принимается в USDT (TRC20 или BEP20). Вы переводите полную сумму нам, мы гарантируем размещение.\n\n2️⃣ Что если пост не выйдет?\n   Мы вернём 100% предоплаты. Случаев невыхода не было.\n\n3️⃣ Какой срок размещения?\n   Обычно пост выходит в течение 24 часов после оплаты.\n\n4️⃣ Могу ли я выбрать каналы сам?\n   Да, вы можете просмотреть каталог и добавить любые каналы в корзину.\n\n5️⃣ Как узнать статистику поста?\n   Через 24 часа после публикации мы пришлём вам отчёт: просмотры, реакции, ER.\n\nПо остальным вопросам пишите @esvig_support."
        await m.answer(txt)

    @dp.message(F.text == "📞 Контакты")
    async def contacts(m: Message):
        txt = "📞 Контакты\n\nПо всем вопросам обращайтесь:\n• Support: @esvig_support\n• Наш канал: https://t.me/esvig_service\n• По поводу сотрудничества/рекламы: @zoldya_vv"
        await m.answer(txt)

    # ---------- Инлайн - админка, каталог, корзина ----------
    @dp.callback_query(F.data == "admin_back")
    async def adm_back(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await cb.message.edit_text("👑 Админ-панель", reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_orders")
    async def adm_orders(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        ords = get_orders(20)
        if not ords: await cb.message.edit_text("Нет заявок", reply_markup=get_back_keyboard()); await cb.answer(); return
        await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_order_"))
    async def adm_view_order(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        oid = int(cb.data.split("_")[2])
        ordd = get_order_by_id(oid)
        if not ordd: await cb.answer("Заявка не найдена", True); return
        em = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}.get(ordd['status'],'⚪')
        txt = f"📄 Заявка #{ordd['id']}\n👤 @{ordd['username']}\n💰 Сумма: {ordd['total']}$\n📌 Статус: {em} {ordd['status']}\n\nВыберите новый статус:"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟡 В обработке", callback_data=f"set_status_{oid}_в обработке")],
            [InlineKeyboardButton(text="🟢 Оплачена", callback_data=f"set_status_{oid}_оплачена")],
            [InlineKeyboardButton(text="✅ Выполнена", callback_data=f"set_status_{oid}_выполнена")],
            [InlineKeyboardButton(text="❌ Отменена", callback_data=f"set_status_{oid}_отменена")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_orders")]
        ])
        await cb.message.edit_text(txt, reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("set_status_"))
    async def set_st(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        parts = cb.data.split("_")
        oid = int(parts[2])
        new_st = "_".join(parts[3:])
        update_order_status(oid, new_st)
        await cb.answer(f"✅ Статус заявки #{oid} изменён на {new_st}", False)
        ordd = get_order_by_id(oid)
        if ordd:
            try:
                await cb.bot.send_message(ordd['user_id'], f"📢 Статус вашей заявки #{oid} изменён на: {new_st}")
            except: pass
        ords = get_orders(20)
        await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))

    @dp.callback_query(F.data == "admin_list")
    async def adm_list(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await load_channels()
        if not channels: await cb.message.edit_text("Список каналов пуст", reply_markup=get_back_keyboard()); await cb.answer(); return
        await cb.message.edit_text("📋 Список каналов\nНажмите на канал для подробностей:", reply_markup=get_admin_list_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_view_"))
    async def adm_view_chan(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await load_channels()
        cid = cb.data.replace("admin_view_", "")
        ch = channels.get(cid)
        if not ch: await cb.answer("Канал не найден", True); return
        txt = f"📌 {ch['name']}\n🔗 {ch['url']}\n💰 {ch['price']}$\n👥 {ch['subscribers']} подп.\n📝 {ch.get('description','Нет описания')}\n🆔 {cid}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_channel_{cid}")],[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_list")]])
        await cb.message.edit_text(txt, reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("edit_channel_"))
    async def edit_chan_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        cid = cb.data.replace("edit_channel_", "")
        await load_channels()
        if cid not in channels: await cb.answer("Канал не найден", True); return
        await cb.message.edit_text(f"Редактирование канала {channels[cid]['name']}\nВыберите, что изменить:", reply_markup=get_edit_channel_keyboard(cid))
        await cb.answer()

    @dp.callback_query(F.data.startswith("edit_") & ~F.data.startswith("edit_channel_"))
    async def edit_field(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        parts = cb.data.split("_",2)
        if len(parts)<3: await cb.answer("Ошибка", True); return
        cid, field = parts[1], parts[2]
        await load_channels()
        if cid not in channels: await cb.answer("Канал не найден", True); return
        await state.update_data(ch_id=cid, field=field)
        prompt = {'name':'Введите новое название:','price':'Введите новую цену (число):','subscribers':'Введите новый охват (число):','url':'Введите новую ссылку (https://t.me/...):','description':'Введите новое описание:'}
        await cb.message.edit_text(prompt.get(field, "Введите значение:"))
        if field=='name': await state.set_state(EditChannelStates.waiting_for_name)
        elif field=='price': await state.set_state(EditChannelStates.waiting_for_price)
        elif field=='subscribers': await state.set_state(EditChannelStates.waiting_for_subscribers)
        elif field=='url': await state.set_state(EditChannelStates.waiting_for_url)
        elif field=='description': await state.set_state(EditChannelStates.waiting_for_description)
        await cb.answer()

    @dp.message(EditChannelStates.waiting_for_name)
    async def e_name(m: Message, state: FSMContext):
        d = await state.get_data()
        update_channel(d['ch_id'], name=m.text)
        await load_channels()
        await m.answer(f"✅ Название изменено на {m.text}")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_price)
    async def e_price(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        d = await state.get_data()
        update_channel(d['ch_id'], price=int(m.text))
        await load_channels()
        await m.answer(f"✅ Цена изменена на {m.text}$")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_subscribers)
    async def e_subs(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        d = await state.get_data()
        update_channel(d['ch_id'], subscribers=int(m.text))
        await load_channels()
        await m.answer(f"✅ Охват изменён на {m.text}")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_url)
    async def e_url(m: Message, state: FSMContext):
        url = m.text.strip()
        if not url.startswith("https://t.me/"):
            await m.answer("Ссылка должна начинаться с https://t.me/")
            return
        d = await state.get_data()
        update_channel(d['ch_id'], url=url)
        await load_channels()
        await m.answer(f"✅ Ссылка изменена на {url}")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_description)
    async def e_desc(m: Message, state: FSMContext):
        d = await state.get_data()
        update_channel(d['ch_id'], description=m.text)
        await load_channels()
        await m.answer("✅ Описание изменено")
        await state.clear()
        await admin_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.callback_query(F.data == "admin_remove")
    async def adm_rem_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await load_channels()
        if not channels: await cb.message.edit_text("Нет каналов для удаления", reply_markup=get_back_keyboard()); await cb.answer(); return
        await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_del_"))
    async def adm_del(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        cid = cb.data.replace("admin_del_", "")
        await load_channels()
        if cid in channels:
            name = channels[cid]['name']
            delete_channel(cid)
            await load_channels()
            await cb.answer(f"✅ Канал {name} удалён", False)
            if not channels:
                await cb.message.edit_text("Все каналы удалены", reply_markup=get_back_keyboard())
            else:
                await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard())
        else:
            await cb.answer("Канал не найден", True)

    @dp.callback_query(F.data == "admin_add")
    async def adm_add_start(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await cb.message.edit_text("➕ Добавление канала\n\nВведите название:")
        await state.set_state(AddChannelStates.waiting_for_name)
        await cb.answer()

    @dp.message(AddChannelStates.waiting_for_name)
    async def a_name(m: Message, state: FSMContext):
        await state.update_data(name=m.text)
        await m.answer("Введите цену (число):")
        await state.set_state(AddChannelStates.waiting_for_price)

    @dp.message(AddChannelStates.waiting_for_price)
    async def a_price(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        await state.update_data(price=int(m.text))
        await m.answer("Введите охват (число):")
        await state.set_state(AddChannelStates.waiting_for_subscribers)

    @dp.message(AddChannelStates.waiting_for_subscribers)
    async def a_subs(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        await state.update_data(subscribers=int(m.text))
        await m.answer("Введите ссылку (https://t.me/...):")
        await state.set_state(AddChannelStates.waiting_for_url)

    @dp.message(AddChannelStates.waiting_for_url)
    async def a_url(m: Message, state: FSMContext):
        url = m.text.strip()
        if not url.startswith("https://t.me/"): await m.answer("Ссылка должна начинаться с https://t.me/"); return
        await state.update_data(url=url)
        await m.answer("Введите описание канала:")
        await state.set_state(AddChannelStates.waiting_for_description)

    @dp.message(AddChannelStates.waiting_for_description)
    async def a_desc(m: Message, state: FSMContext):
        d = await state.get_data()
        await load_channels()
        new_id = f"channel_{len(channels)+1}"
        add_channel(new_id, d['name'], d['price'], d['subscribers'], d['url'], m.text)
        await load_channels()
        await m.answer(f"✅ Канал {d['name']} добавлен!")
        await state.clear()
        await m.answer("Вернуться в админ-панель:", reply_markup=get_admin_keyboard())

    @dp.callback_query(F.data == "back_to_main")
    async def back_main(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.message.edit_text("Главное меню:", reply_markup=get_main_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("view_catalog_page_"))
    async def view_catalog_page(cb: CallbackQuery):
        await load_channels()
        page = int(cb.data.split("_")[-1])
        kb, cur, tot = get_catalog_keyboard(page)
        await cb.message.edit_text(f"📢 Наши каналы (страница {cur+1}/{tot})\nНажмите на канал для деталей:", reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("view_"))
    async def view_channel(cb: CallbackQuery):
        cid = cb.data.replace("view_", "")
        info = get_all_channels().get(cid)
        if not info:
            await cb.answer("Канал не найден", True)
            return
        txt = f"📌 {info['name']}\n👥 Подписчиков: {info['subscribers']}\n💰 Цена: {info['price']}$\n🔗 Ссылка: {info['url']}\n📝 Описание:\n{info.get('description','Нет описания')}"
        await cb.message.edit_text(txt, reply_markup=get_channel_view_keyboard(cid))
        await cb.answer()

    @dp.callback_query(F.data.startswith("add_"))
    async def add_to_cart(cb: CallbackQuery):
        cid = cb.data.replace("add_", "")
        info = get_all_channels().get(cid)
        if not info:
            await cb.answer("Канал не найден", True)
            return
        cart = get_cart(cb.from_user.id)
        cart.append({"id": cid, "name": info['name'], "price": info['price']})
        save_cart(cb.from_user.id, cart)
        await cb.answer(f"✅ {info['name']} добавлен в корзину!", False)

    @dp.callback_query(F.data == "clear_cart")
    async def clear_cart(cb: CallbackQuery):
        user_carts[cb.from_user.id] = []
        await cb.answer("🗑 Корзина очищена", False)
        await cb.message.edit_text("Корзина пуста", reply_markup=get_back_keyboard())

    @dp.callback_query(F.data.startswith("remove_"))
    async def remove_from_cart(cb: CallbackQuery):
        idx = int(cb.data.split("_")[1])
        cart = get_cart(cb.from_user.id)
        if 0 <= idx < len(cart):
            removed = cart.pop(idx)
            save_cart(cb.from_user.id, cart)
            await cb.answer(f"❌ {removed['name']} удалён", False)
            if not cart:
                await cb.message.edit_text("Корзина пуста", reply_markup=get_back_keyboard())
            else:
                total = sum(i['price'] for i in cart)
                txt = "🛒 Ваша корзина:\n\n" + "\n".join(f"{i+1}. {item['name']} — {item['price']}$" for i,item in enumerate(cart)) + f"\n\nИтого: {total}$"
                await cb.message.edit_text(txt, reply_markup=get_cart_keyboard(cb.from_user.id))
        else:
            await cb.answer("Ошибка", True)

    @dp.callback_query(F.data == "checkout")
    async def checkout_cb(cb: CallbackQuery, state: FSMContext):
        cart = get_cart(cb.from_user.id)
        if not cart:
            await cb.message.edit_text("Корзина пуста", reply_markup=get_back_keyboard())
            await cb.answer()
            return
        total = sum(i['price'] for i in cart)
        await state.update_data(cart=cart, total=total)
        await cb.message.edit_text(f"💳 Оформление заказа\n\nСумма: {total}$\nВведите ваш бюджет (цифрами, ≥ суммы):")
        await state.set_state(OrderForm.waiting_for_budget)
        await cb.answer()

    @dp.message(OrderForm.waiting_for_budget)
    async def budg(m: Message, state: FSMContext):
        if not m.text.isdigit():
            await m.answer("Введите число")
            return
        budget = int(m.text)
        d = await state.get_data()
        total = d.get("total",0)
        if budget < total:
            await m.answer(f"Бюджет ({budget}$) меньше суммы ({total}$). Введите {total}$ или больше:")
            return
        await state.update_data(budget=budget)
        await m.answer("Напишите ваш Telegram username (например, @username) или другой контакт:")
        await state.set_state(OrderForm.waiting_for_contact)

    @dp.message(OrderForm.waiting_for_contact)
    async def cont(m: Message, state: FSMContext):
        d = await state.get_data()
        cart = d.get("cart",[])
        total = d.get("total",0)
        budget = d.get("budget",0)
        contact = m.text.strip()
        username = m.from_user.username or "не указан"
        save_order(m.from_user.id, username, cart, total, budget, contact)
        items = "\n".join(f"• {i['name']} — {i['price']}$" for i in cart)
        report = f"🟢 НОВАЯ ЗАЯВКА\n👤 @{username}\n📦 Состав:\n{items}\n💰 Сумма: {total}$\n💵 Бюджет: {budget}$\n📞 Контакт: {contact}"
        for aid in ADMIN_IDS:
            try:
                await m.bot.send_message(aid, report)
            except: pass
        user_carts[m.from_user.id] = []
        await m.answer("✅ Заявка отправлена! Менеджер свяжется с вами.", reply_markup=get_main_keyboard())
        await state.clear()

    @dp.callback_query(F.data == "my_orders")
    async def my_ords(cb: CallbackQuery):
        ords = get_orders_by_user(cb.from_user.id, 10)
        if not ords:
            await cb.message.edit_text("У вас пока нет заявок", reply_markup=get_back_keyboard())
            await cb.answer()
            return
        txt = "📊 Ваши заявки:\n\n"
        em = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}
        for o in ords:
            txt += f"🆔 №{o['id']}\n💰 Сумма: {o['total']}$\n📦 Товаров: {len(o['cart'])}\n📌 Статус: {em.get(o['status'],'⚪')} {o['status']}\n🕒 {o['created_at']}\n➖➖➖➖➖\n"
        await cb.message.edit_text(txt, reply_markup=get_back_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "deposit")
    async def dep(cb: CallbackQuery):
        await cb.message.edit_text("💰 Пополнение баланса временно недоступно.\n\nСкоро мы добавим эту возможность.", reply_markup=get_back_keyboard())
        await cb.answer()

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
