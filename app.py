import os
import asyncio
import json
import hashlib
import hmac
import time
import asyncpg
import requests
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
                           ReplyKeyboardMarkup, KeyboardButton, FSInputFile, Update)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask, request, jsonify
from database import (init_db, get_all_channels, add_channel, delete_channel, update_channel,
                      save_order, get_orders, get_orders_by_user, update_order_status,
                      get_order_by_id, clear_non_successful_orders, clear_all_orders,
                      get_all_categories, add_category, delete_category, get_category_by_id,
                      close_db, get_or_create_user, update_user_balance, get_user_balance,
                      debit_balance, return_balance, get_user_transactions,
                      check_daily_order_limit, get_user_daily_info)

# ---------- Конфигурация (все секреты через переменные окружения) ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8524671546:AAHMk0g59VhU18p0r5gxYg-r9mVzz83JGmU")
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "7787223469,7345960167,714447317,8614748084,8702300149,8472548724").split(",")))
ITEMS_PER_PAGE = 5
SECRET_TOKEN = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://esvig-production-4961.up.railway.app/webhook")
MIN_DEPOSIT = 0.1
PAID_BTN_URL = "https://t.me/esvig_bot"
CRYPTO_BOT_TOKEN = os.environ.get("CRYPTO_BOT_TOKEN", "")
XROCKET_API_KEY = os.environ.get("XROCKET_API_KEY", "56ddd1419e9215489721f9a8")
DAILY_ORDER_LIMIT = 3
# -------------------------------------------------------------------------

class OrderForm(StatesGroup):
    waiting_for_budget = State()
    waiting_for_contact = State()
    waiting_for_deposit_amount = State()

class AddChannelStates(StatesGroup):
    waiting_for_category = State()
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
    waiting_for_category = State()

class AddCategoryStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_display_name = State()

class AdminBalanceStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

user_carts = {}

def get_cart(uid):
    if uid not in user_carts:
        user_carts[uid] = []
    return user_carts[uid]

def save_cart(uid, cart):
    user_carts[uid] = cart

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_channel")]])

# --- Клавиатуры (все функции без изменений, кроме исправления сортировки) ---
def get_main_keyboard(user_id: int = None):
    buttons = [
        [KeyboardButton(text="📋 Каталог каналов"), KeyboardButton(text="🛒 Корзина")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="ℹ️ О сервисе")],
        [KeyboardButton(text="❓ FAQ"), KeyboardButton(text="📞 Контакты")]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([KeyboardButton(text="🔑 Админ‑панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список каналов", callback_data="admin_list"),
         InlineKeyboardButton(text="📋 Заявки", callback_data="admin_orders")],
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="admin_add"),
         InlineKeyboardButton(text="❌ Удалить канал", callback_data="admin_remove")],
        [InlineKeyboardButton(text="🏷 Управление категориями", callback_data="admin_categories"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data="admin_balance")],
    ])

async def get_categories_keyboard():
    cats = await get_all_categories()
    if not cats:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]])
    rows = []
    for i in range(0, len(cats), 2):
        row = []
        row.append(InlineKeyboardButton(
            text=cats[i]['display_name'],
            callback_data=f"category_select_{cats[i]['id']}"
        ))
        if i+1 < len(cats):
            row.append(InlineKeyboardButton(
                text=cats[i+1]['display_name'],
                callback_data=f"category_select_{cats[i+1]['id']}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_catalog_keyboard(channels_dict, category_id, page=0, sort_by="default"):
    if not channels_dict:
        return None, 0, 0
    items = list(channels_dict.items())
    # Используем sorted() для избежания мутации
    if sort_by == "price_asc":
        items = sorted(items, key=lambda x: x[1]['price'])
    elif sort_by == "price_desc":
        items = sorted(items, key=lambda x: x[1]['price'], reverse=True)
    elif sort_by == "subs_asc":
        items = sorted(items, key=lambda x: x[1]['subscribers'])
    elif sort_by == "subs_desc":
        items = sorted(items, key=lambda x: x[1]['subscribers'], reverse=True)

    tot = (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    if page < 0: page = 0
    if page >= tot: page = tot - 1
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    btns = []
    if len(items) > 1:
        sort_row = [
            InlineKeyboardButton(text="🔽 Цена", callback_data=f"sort_{category_id}_price_asc_{page}"),
            InlineKeyboardButton(text="🔼 Цена", callback_data=f"sort_{category_id}_price_desc_{page}"),
            InlineKeyboardButton(text="🔽 Подп.", callback_data=f"sort_{category_id}_subs_asc_{page}"),
            InlineKeyboardButton(text="🔼 Подп.", callback_data=f"sort_{category_id}_subs_desc_{page}")
        ]
        btns.append(sort_row)
    for cid, inf in items[start:end]:
        btns.append([InlineKeyboardButton(text=f"{inf['name']} ({inf['subscribers']} подп., {inf['price']}$)", callback_data=f"channel_view_{cid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"view_catalog_page_{category_id}_{page}_{sort_by}"))
    if page < tot - 1:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"view_catalog_page_{category_id}_{page+1}_{sort_by}"))
    if nav: btns.append(nav)
    btns.append([InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=btns), page, tot

def get_channel_view_keyboard(cid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в корзину", callback_data=f"cart_add_{cid}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_catalog")]
    ])

def get_cart_keyboard(uid):
    cart = get_cart(uid)
    if not cart: return None
    btns = []
    for idx, it in enumerate(cart):
        btns.append([InlineKeyboardButton(text=f"❌ Удалить {it['name']} ({it['price']}$)", callback_data=f"remove_{idx}")])
    btns.append([InlineKeyboardButton(text="💳 Перейти к оформлению", callback_data="checkout")])
    btns.append([InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="clear_cart")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]])

def get_admin_list_keyboard(channels_dict):
    if not channels_dict: return None
    btns = []
    for cid, inf in channels_dict.items():
        btns.append([InlineKeyboardButton(text=f"{inf['name']} | {inf['price']}$ | {inf['subscribers']} подп.", callback_data=f"admin_view_{cid}")])
    btns.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def get_admin_remove_keyboard(channels_dict):
    if not channels_dict: return None
    btns = []
    for cid, inf in channels_dict.items():
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
        [InlineKeyboardButton(text="✏️ Подписчики", callback_data=f"edit_{cid}_subscribers")],
        [InlineKeyboardButton(text="✏️ Ссылка", callback_data=f"edit_{cid}_url")],
        [InlineKeyboardButton(text="✏️ Описание", callback_data=f"edit_{cid}_description")],
        [InlineKeyboardButton(text="✏️ Категория", callback_data=f"edit_{cid}_category")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_view_{cid}")]
    ])

def get_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мои заявки", callback_data="my_orders")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")]
    ])

def get_stats_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить неуспешные", callback_data="confirm_clear_failed")],
        [InlineKeyboardButton(text="🗑 Полная очистка", callback_data="confirm_clear_all")]
    ])

async def get_categories_admin_keyboard():
    cats = await get_all_categories()
    if not cats:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить категорию", callback_data="admin_add_category")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
        ])
    rows = []
    for i in range(0, len(cats), 2):
        row = []
        row.append(InlineKeyboardButton(text=f"{cats[i]['display_name']} ({cats[i]['name']})", callback_data=f"admin_category_{cats[i]['id']}"))
        if i+1 < len(cats):
            row.append(InlineKeyboardButton(text=f"{cats[i+1]['display_name']} ({cats[i+1]['name']})", callback_data=f"admin_category_{cats[i+1]['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="➕ Добавить категорию", callback_data="admin_add_category")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_category_actions_keyboard(cat_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Удалить категорию", callback_data=f"admin_del_category_{cat_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_categories")]
    ])

async def get_category_selection_keyboard(callback_prefix):
    cats = await get_all_categories()
    if not cats:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]])
    rows = []
    for i in range(0, len(cats), 2):
        row = []
        row.append(InlineKeyboardButton(text=cats[i]['display_name'], callback_data=f"{callback_prefix}_{cats[i]['id']}"))
        if i+1 < len(cats):
            row.append(InlineKeyboardButton(text=cats[i+1]['display_name'], callback_data=f"{callback_prefix}_{cats[i+1]['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# --- Обработчики (без изменений, кроме обработки welcome.jpg) ---
async def register_handlers(dp: Dispatcher):
    @dp.message(Command("start"))
    async def start(m: Message):
        user = await get_or_create_user(m.from_user.id, m.from_user.username or "Пользователь")
        user_name = m.from_user.first_name or m.from_user.username or "Пользователь"
        caption = f"Рад видеть тебя, {user_name}!\n\n💰 Твой баланс: {user['balance']}$\n\n🚀 Приятных покупок! 🛍️"
        try:
            # Проверяем существование файла, чтобы избежать лишней ошибки в логах
            if os.path.exists("welcome.jpg"):
                photo = FSInputFile("welcome.jpg")
                await m.answer_photo(photo, caption=caption, reply_markup=get_main_keyboard(m.from_user.id))
            else:
                raise FileNotFoundError
        except:
            await m.answer(caption, reply_markup=get_main_keyboard(m.from_user.id))

    @dp.message(F.text == "🔑 Админ‑панель")
    async def admin_panel_msg(m: Message):
        if m.from_user.id in ADMIN_IDS:
            await m.answer("👑 Админ‑панель", reply_markup=get_admin_keyboard())
        else:
            await m.answer("Нет прав")

    # ========== Каталог ==========
    @dp.message(F.text == "📋 Каталог каналов")
    async def catalog_start(m: Message):
        cats = await get_all_categories()
        if not cats:
            await m.answer("Категории не найдены")
            return
        await m.answer("Выберите категорию:", reply_markup=await get_categories_keyboard())

    @dp.callback_query(F.data.startswith("category_select_"))
    async def select_category(cb: CallbackQuery):
        cat_id = int(cb.data.split("_")[2])
        ch = await get_all_channels(cat_id)
        if not ch:
            await cb.message.edit_text("В этой категории пока нет каналов.",
                                       reply_markup=InlineKeyboardMarkup(
                                           inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")]]))
            await cb.answer()
            return
        kb, page, total = get_catalog_keyboard(ch, cat_id, 0)
        await cb.message.edit_text(f"📢 Каналы в категории (страница 1/{total})", reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("sort_"))
    async def sort_catalog(cb: CallbackQuery):
        parts = cb.data.split("_")
        cat_id = int(parts[1])
        field = parts[2]
        order = parts[3]
        page = int(parts[4])
        sort_key = f"{field}_{order}"
        ch = await get_all_channels(cat_id)
        kb, cur, total = get_catalog_keyboard(ch, cat_id, page, sort_by=sort_key)
        await cb.message.edit_text(f"📢 Каналы в категории (страница {cur+1}/{total})", reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data == "back_to_categories")
    async def back_to_categories(cb: CallbackQuery):
        cats = await get_all_categories()
        if not cats:
            await cb.message.edit_text("Категории не найдены", reply_markup=get_back_keyboard())
            await cb.answer()
            return
        await cb.message.edit_text("Выберите категорию:", reply_markup=await get_categories_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("view_catalog_page_"))
    async def view_catalog_page(cb: CallbackQuery):
        parts = cb.data.split("_")
        cat_id = int(parts[3])
        page = int(parts[4])
        sort_by = parts[5] if len(parts) > 5 else "default"
        ch = await get_all_channels(cat_id)
        kb, cur, total = get_catalog_keyboard(ch, cat_id, page, sort_by=sort_by)
        if kb:
            await cb.message.edit_text(f"📢 Каналы в категории (страница {cur+1}/{total})", reply_markup=kb)
        else:
            await cb.message.edit_text("Каталог пуст", reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")]]))
        await cb.answer()

    @dp.callback_query(F.data == "back_to_catalog")
    async def back_to_catalog(cb: CallbackQuery):
        cats = await get_all_categories()
        if not cats:
            await cb.message.edit_text("Категории не найдены", reply_markup=get_back_keyboard())
            await cb.answer()
            return
        await cb.message.edit_text("Выберите категорию:", reply_markup=await get_categories_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "back_to_main_menu")
    async def back_main_menu(cb: CallbackQuery):
        await cb.message.delete()
        await cb.message.answer("Главное меню:", reply_markup=get_main_keyboard(cb.from_user.id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("channel_view_"))
    async def view_channel(cb: CallbackQuery):
        cid = cb.data.replace("channel_view_", "")
        ch = await get_all_channels()
        info = ch.get(cid)
        if not info:
            await cb.answer("Канал не найден", True)
            return
        txt = f"📌 {info['name']}\n👥 Подписчиков: {info['subscribers']}\n💰 Цена: {info['price']}$\n🔗 Ссылка: {info['url']}\n📝 Описание:\n{info.get('description','Нет описания')}"
        await cb.message.edit_text(txt, reply_markup=get_channel_view_keyboard(cid))
        await cb.answer()

    @dp.callback_query(F.data.startswith("cart_add_"))
    async def add_to_cart(cb: CallbackQuery):
        cid = cb.data.replace("cart_add_", "")
        ch = await get_all_channels()
        info = ch.get(cid)
        if not info:
            await cb.answer("Канал не найден", True)
            return
        cart = get_cart(cb.from_user.id)
        cart.append({"id": cid, "name": info['name'], "price": info['price']})
        save_cart(cb.from_user.id, cart)
        await cb.answer(f"✅ {info['name']} добавлен в корзину!", False)

    # ========== Корзина, оформление, профиль ==========
    @dp.message(F.text == "🛒 Корзина")
    async def cart(m: Message):
        c = get_cart(m.from_user.id)
        if not c:
            await m.answer("Корзина пуста")
            return
        total = sum(i['price'] for i in c)
        items_str = "\n".join(f"{idx+1}. {i['name']} — {i['price']}$" for idx,i in enumerate(c))
        await m.answer(f"🛒 Ваша корзина:\n\n{items_str}\n\nИтого: {total}$", reply_markup=get_cart_keyboard(m.from_user.id))

    @dp.callback_query(F.data == "clear_cart")
    async def clear_cart(cb: CallbackQuery):
        user_carts[cb.from_user.id] = []
        await cb.answer("🗑 Корзина очищена", False)
        await cb.message.delete()
        await cb.message.answer("Корзина пуста", reply_markup=get_main_keyboard(cb.from_user.id))

    @dp.callback_query(F.data.startswith("remove_"))
    async def remove_from_cart(cb: CallbackQuery):
        idx = int(cb.data.split("_")[1])
        cart = get_cart(cb.from_user.id)
        if 0 <= idx < len(cart):
            removed = cart.pop(idx)
            save_cart(cb.from_user.id, cart)
            await cb.answer(f"❌ {removed['name']} удалён", False)
            if not cart:
                await cb.message.delete()
                await cb.message.answer("Корзина пуста", reply_markup=get_main_keyboard(cb.from_user.id))
            else:
                total = sum(i['price'] for i in cart)
                items_str = "\n".join(f"{i+1}. {item['name']} — {item['price']}$" for i,item in enumerate(cart))
                await cb.message.edit_text(f"🛒 Ваша корзина:\n\n{items_str}\n\nИтого: {total}$", reply_markup=get_cart_keyboard(cb.from_user.id))
        else:
            await cb.answer("Ошибка", True)

    @dp.callback_query(F.data == "checkout")
    async def checkout_cb(cb: CallbackQuery, state: FSMContext):
        cart = get_cart(cb.from_user.id)
        if not cart:
            await cb.message.edit_text("Корзина пуста", reply_markup=get_main_keyboard(cb.from_user.id))
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

        can_order = await check_daily_order_limit(m.from_user.id)
        if not can_order:
            user_info = await get_or_create_user(m.from_user.id)
            await m.answer(f"❌ Вы исчерпали дневной лимит заявок ({user_info['daily_limit']}). Попробуйте завтра.")
            await state.clear()
            return

        balance = await get_user_balance(m.from_user.id)
        if balance < total:
            await m.answer(f"❌ Недостаточно средств. Ваш баланс: {balance}$, сумма заказа: {total}$.\nПополните баланс в разделе «👤 Мой профиль» → «💰 Пополнить баланс».")
            await state.clear()
            return

        order_id = await save_order(m.from_user.id, username, cart, total, budget, contact, status='оплачена')
        success = await debit_balance(m.from_user.id, total, order_id, description=f"Оплата заказа #{order_id}")
        if not success:
            await update_order_status(order_id, 'отменена')
            await m.answer("Не удалось списать средства. Заказ отменён. Обратитесь в поддержку.")
            await state.clear()
            return

        items = "\n".join(f"• {i['name']} — {i['price']}$" for i in cart)
        report = f"🟢 НОВАЯ ОПЛАЧЕННАЯ ЗАЯВКА #{order_id}\n👤 @{username}\n📦 Состав:\n{items}\n💰 Сумма: {total}$\n💵 Бюджет: {budget}$\n📞 Контакт: {contact}"
        for aid in ADMIN_IDS:
            try:
                await m.bot.send_message(aid, report)
            except: pass
        user_carts[m.from_user.id] = []
        await m.answer(f"✅ Заказ #{order_id} оформлен и оплачен! Сумма {total}$ списана с баланса.\nМенеджер скоро свяжется с вами.",
                       reply_markup=get_main_keyboard(m.from_user.id))
        await state.clear()

    @dp.message(F.text == "👤 Мой профиль")
    async def profile(m: Message):
        user = await get_or_create_user(m.from_user.id, m.from_user.username or "")
        daily_limit, daily_used = await get_user_daily_info(m.from_user.id)
        left_orders = max(daily_limit - daily_used, 0)

        completed_orders = await get_orders_by_user(m.from_user.id, limit=1000, only_completed=True)
        total_spent = sum(o['total'] for o in completed_orders)
        total_orders = len(completed_orders)
        txt = f"👤 Мой профиль\n\n🆔 ID: {m.from_user.id}\n📛 Username: @{m.from_user.username or 'не указан'}\n📦 Успешных заказов: {total_orders}\n💰 Общая сумма трат: {total_spent}$\n💳 Баланс: {user['balance']}$\n📅 Осталось заявок сегодня: {left_orders}/{daily_limit}"
        await m.answer(txt, reply_markup=get_profile_keyboard())

    # ========== ПОПОЛНЕНИЕ БАЛАНСА ==========
    @dp.callback_query(F.data == "deposit")
    async def deposit_menu(cb: CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💵 CryptoBot", callback_data="deposit_crypto")],
            [InlineKeyboardButton(text="💎 XRocket", callback_data="deposit_xrocket")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")]
        ])
        await cb.message.edit_text("Выберите способ пополнения:", reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data == "deposit_crypto")
    async def deposit_crypto_start(cb: CallbackQuery, state: FSMContext):
        await cb.message.edit_text(
            f"💰 Введите сумму пополнения в USDT (минимум {MIN_DEPOSIT}$):",
            reply_markup=cancel_keyboard()
        )
        await state.set_state(OrderForm.waiting_for_deposit_amount)
        await state.update_data(payment_method='crypto')
        await cb.answer()

    @dp.callback_query(F.data == "deposit_xrocket")
    async def deposit_xrocket_start(cb: CallbackQuery, state: FSMContext):
        await cb.message.edit_text(
            f"💰 Введите сумму пополнения в USDT (минимум {MIN_DEPOSIT}$):",
            reply_markup=cancel_keyboard()
        )
        await state.set_state(OrderForm.waiting_for_deposit_amount)
        await state.update_data(payment_method='xrocket')
        await cb.answer()

    @dp.callback_query(F.data == "cancel_add_channel", OrderForm.waiting_for_deposit_amount)
    async def cancel_deposit(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.message.edit_text("👤 Мой профиль", reply_markup=get_profile_keyboard())
        await cb.answer()

    @dp.message(OrderForm.waiting_for_deposit_amount)
    async def process_deposit_amount(m: Message, state: FSMContext):
        text = m.text.strip()
        try:
            amount = float(text)
        except ValueError:
            await m.answer("Пожалуйста, введите число (например, 0.5 или 10).")
            return

        if amount < MIN_DEPOSIT:
            await m.answer(f"Минимальная сумма пополнения — {MIN_DEPOSIT} USDT. Попробуйте ещё раз.")
            return

        data = await state.get_data()
        method = data.get('payment_method', 'crypto')

        if method == 'crypto':
            if not CRYPTO_BOT_TOKEN:
                await m.answer("Платёжная система временно недоступна.")
                await state.clear()
                return
            url = "https://pay.crypt.bot/api/createInvoice"
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            payload = {
                "asset": "USDT",
                "amount": str(amount),
                "description": f"Пополнение баланса user_id:{m.from_user.id}",
                "paid_btn_name": "callback",
                "paid_btn_url": PAID_BTN_URL,
                "hidden_message": f"Спасибо за пополнение, {m.from_user.first_name}!"
            }
       else:  # xrocket
    if not XROCKET_API_KEY:
        await m.answer("Платёжная система временно недоступна.")
        await state.clear()
        return
    # ↓↓↓ НОВЫЙ ДОМЕН И ПУТЬ ↓↓↓
    url = "https://pay.xrocket.tg/api/v1/createInvoice"
    headers = {"X-API-Key": XROCKET_API_KEY}
    payload = {
        "asset": "USDT",
        "amount": str(amount),
        "description": f"Пополнение баланса user_id:{m.from_user.id}",
        "paid_btn_name": "callback",
        "paid_btn_url": PAID_BTN_URL,
    }

        try:
            r = requests.post(url, json=payload, headers=headers)
            data_resp = r.json()
            if data_resp.get("ok"):
                invoice_url = data_resp["result"]["pay_url"]
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Перейти к оплате", url=invoice_url)],
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
                ])
                await m.answer(f"Счёт на {amount}$ создан. Нажмите кнопку для оплаты:", reply_markup=kb)
            else:
                await m.answer("Ошибка при создании счёта. Попробуйте позже.", reply_markup=get_profile_keyboard())
        except Exception as e:
            await m.answer(f"❌ Ошибка XRocket: {str(e)[:300]}", reply_markup=get_profile_keyboard())
        finally:
            await state.clear()

    # ========== Заявки пользователя ==========
    @dp.callback_query(F.data == "my_orders")
    async def my_ords(cb: CallbackQuery):
        ords = await get_orders_by_user(cb.from_user.id, 10, only_completed=False)
        if not ords:
            await cb.message.delete()
            await cb.message.answer("📭 У вас пока нет заявок.", reply_markup=get_main_keyboard(cb.from_user.id))
            await cb.answer()
            return
        txt = "📊 Ваши заявки:\n\n"
        btns = []
        em = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}
        for o in ords:
            txt += f"🆔 №{o['id']}\n💰 Сумма: {o['total']}$\n📦 Товаров: {len(o['cart'])}\n📌 Статус: {em.get(o['status'],'⚪')} {o['status']}\n🕒 {o['created_at']}\n➖➖➖➖➖\n"
            row = [InlineKeyboardButton(text="📄 Подробнее", callback_data=f"order_details_{o['id']}")]
            if o['status'] in ('в обработке', 'оплачена'):
                row.append(InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_order_{o['id']}"))
            btns.append(row)
        btns.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")])
        await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
        await cb.answer()

    @dp.callback_query(F.data.startswith("order_details_"))
    async def order_details(cb: CallbackQuery):
        oid = int(cb.data.split("_")[2])
        ordd = await get_order_by_id(oid)
        if not ordd or ordd['user_id'] != cb.from_user.id:
            await cb.answer("Заявка не найдена", True)
            return
        items = "\n".join(f"• {it['name']} — {it['price']}$" for it in ordd['cart'])
        await cb.message.edit_text(f"📄 Заявка #{oid}\n📌 Статус: {ordd['status']}\n💰 Сумма: {ordd['total']}$\n\n📦 Состав:\n{items}",
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="my_orders")]]))
        await cb.answer()

    @dp.callback_query(F.data.startswith("cancel_order_"))
    async def cancel_order(cb: CallbackQuery):
        order_id = int(cb.data.split("_")[2])
        ordd = await get_order_by_id(order_id)
        if not ordd or ordd['user_id'] != cb.from_user.id:
            await cb.answer("Заявка не найдена или недоступна", True)
            return
        if ordd['status'] not in ('в обработке', 'оплачена'):
            await cb.answer("Эту заявку уже нельзя отменить", True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"confirm_cancel_{order_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="my_orders")]
        ])
        await cb.message.edit_text(f"⚠️ Вы уверены, что хотите отменить заявку #{order_id} на сумму {ordd['total']}$?\nДеньги будут возвращены на баланс.", reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("confirm_cancel_"))
    async def confirm_cancel(cb: CallbackQuery):
        order_id = int(cb.data.split("_")[2])
        ordd = await get_order_by_id(order_id)
        if not ordd or ordd['user_id'] != cb.from_user.id:
            await cb.answer("Заявка не найдена", True)
            return
        if ordd['status'] not in ('в обработке', 'оплачена'):
            await cb.answer("Статус изменился, отмена невозможна", True)
            return
        await update_order_status(order_id, 'отменена')
        await return_balance(ordd['user_id'], ordd['total'], order_id, f"Возврат за отмену заказа #{order_id}")
        await cb.answer("Заявка отменена, деньги возвращены на баланс", False)
        for aid in ADMIN_IDS:
            try:
                await cb.bot.send_message(aid, f"❌ Заявка #{order_id} отменена пользователем @{ordd['username']} (сумма {ordd['total']}$). Деньги возвращены.")
            except: pass
        await my_ords(cb)

    # ========== Админ‑панель (полная) ==========
    @dp.callback_query(F.data == "cancel_add_channel")
    async def cancel_add_channel(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
        await state.clear()
        await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_back")
    async def adm_back(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_categories")
    async def admin_categories_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await cb.message.edit_text("🏷 Управление категориями", reply_markup=await get_categories_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_add_category")
    async def admin_add_category_start(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await cb.message.edit_text("Введите **короткое имя** категории (на английском, например 'mining'):", parse_mode="Markdown")
        await state.set_state(AddCategoryStates.waiting_for_name)
        await cb.answer()

    @dp.message(AddCategoryStates.waiting_for_name)
    async def add_cat_name(m: Message, state: FSMContext):
        name = m.text.strip()
        if not name:
            await m.answer("Имя не может быть пустым")
            return
        await state.update_data(name=name)
        await m.answer("Введите отображаемое название категории (например 'Майнинг'):")
        await state.set_state(AddCategoryStates.waiting_for_display_name)

    @dp.message(AddCategoryStates.waiting_for_display_name)
    async def add_cat_display(m: Message, state: FSMContext):
        data = await state.get_data()
        name = data['name']
        display = m.text.strip()
        if not display:
            await m.answer("Название не может быть пустым")
            return
        await add_category(name, display)
        await m.answer(f"✅ Категория '{display}' добавлена", reply_markup=get_admin_keyboard())
        await state.clear()

    @dp.callback_query(F.data.startswith("admin_category_"))
    async def admin_category_detail(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        cat_id = int(cb.data.split("_")[2])
        cat = await get_category_by_id(cat_id)
        if not cat:
            await cb.answer("Категория не найдена", True)
            return
        await cb.message.edit_text(f"Категория: {cat['display_name']} (id={cat_id}, имя={cat['name']})", reply_markup=get_category_actions_keyboard(cat_id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_del_category_"))
    async def admin_del_category(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        cat_id = int(cb.data.split("_")[3])
        await delete_category(cat_id)
        await cb.answer("Категория удалена", False)
        await admin_categories_menu(cb)

    @dp.callback_query(F.data == "admin_list")
    async def adm_list(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        ch = await get_all_channels()
        if not ch:
            await cb.message.delete()
            await cb.message.answer("Список каналов пуст", reply_markup=get_main_keyboard(cb.from_user.id))
            await cb.answer()
            return
        await cb.message.edit_text("📋 Список каналов\nНажмите на канал для подробностей:", reply_markup=get_admin_list_keyboard(ch))
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_view_"))
    async def adm_view_chan(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        ch = await get_all_channels()
        cid = cb.data.replace("admin_view_", "")
        info = ch.get(cid)
        if not info: await cb.answer("Канал не найден", True); return
        cat_name = ""
        if info.get('category_id'):
            cat = await get_category_by_id(info['category_id'])
            if cat:
                cat_name = cat['display_name']
        txt = f"📌 {info['name']}\n🔗 {info['url']}\n💰 {info['price']}$\n👥 {info['subscribers']} подп.\n📝 {info.get('description','Нет описания')}"
        if cat_name:
            txt += f"\n🏷 {cat_name}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_channel_{cid}")],[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_list")]])
        await cb.message.edit_text(txt, reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("edit_channel_"))
    async def edit_chan_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        cid = cb.data.replace("edit_channel_", "")
        ch = await get_all_channels()
        if cid not in ch: await cb.answer("Канал не найден", True); return
        await cb.message.edit_text(f"Редактирование канала {ch[cid]['name']}\nВыберите, что изменить:", reply_markup=get_edit_channel_keyboard(cid))
        await cb.answer()

    @dp.callback_query(F.data.startswith("edit_") & ~F.data.startswith("edit_channel_"))
    async def edit_field(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        parts = cb.data.split("_",2)
        if len(parts)<3: await cb.answer("Ошибка", True); return
        cid, field = parts[1], parts[2]
        ch = await get_all_channels()
        if cid not in ch: await cb.answer("Канал не найден", True); return
        await state.update_data(ch_id=cid, field=field)
        if field == 'category':
            await cb.message.edit_text("Выберите новую категорию:", reply_markup=await get_category_selection_keyboard(f"edit_chan_cat_{cid}"))
            await state.set_state(EditChannelStates.waiting_for_category)
        else:
            prompts = {'name':'Введите новое название:','price':'Введите новую цену (число):','subscribers':'Введите новое количество подписчиков (число):','url':'Введите новую ссылку (https://t.me/...):','description':'Введите новое описание:'}
            await cb.message.edit_text(prompts.get(field, "Введите значение:"))
            if field=='name': await state.set_state(EditChannelStates.waiting_for_name)
            elif field=='price': await state.set_state(EditChannelStates.waiting_for_price)
            elif field=='subscribers': await state.set_state(EditChannelStates.waiting_for_subscribers)
            elif field=='url': await state.set_state(EditChannelStates.waiting_for_url)
            elif field=='description': await state.set_state(EditChannelStates.waiting_for_description)
        await cb.answer()

    @dp.callback_query(F.data.startswith("edit_chan_cat_"))
    async def edit_channel_category_selected(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        parts = cb.data.split("_")
        cid = parts[3]
        cat_id = int(parts[4])
        await update_channel(cid, category_id=cat_id)
        await cb.answer("Категория обновлена", False)
        await adm_view_chan(cb)
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_name)
    async def e_name(m: Message, state: FSMContext):
        d = await state.get_data()
        await update_channel(d['ch_id'], name=m.text)
        await m.answer(f"✅ Название изменено на {m.text}")
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_price)
    async def e_price(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        d = await state.get_data()
        await update_channel(d['ch_id'], price=int(m.text))
        await m.answer(f"✅ Цена изменена на {m.text}$")
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_subscribers)
    async def e_subs(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        d = await state.get_data()
        await update_channel(d['ch_id'], subs=int(m.text))
        await m.answer(f"✅ Количество подписчиков изменено на {m.text}")
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_url)
    async def e_url(m: Message, state: FSMContext):
        url = m.text.strip()
        if not url.startswith("https://t.me/"):
            await m.answer("Ссылка должна начинаться с https://t.me/")
            return
        d = await state.get_data()
        await update_channel(d['ch_id'], url=url)
        await m.answer(f"✅ Ссылка изменена на {url}")
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_description)
    async def e_desc(m: Message, state: FSMContext):
        d = await state.get_data()
        await update_channel(d['ch_id'], desc=m.text)
        await m.answer("✅ Описание изменено")
        await state.clear()

    @dp.callback_query(F.data == "admin_remove")
    async def adm_rem_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        ch = await get_all_channels()
        if not ch:
            await cb.message.delete()
            await cb.message.answer("Нет каналов для удаления", reply_markup=get_main_keyboard(cb.from_user.id))
            await cb.answer()
            return
        await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard(ch))
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_del_"))
    async def adm_del(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        cid = cb.data.replace("admin_del_", "")
        ch = await get_all_channels()
        if cid in ch:
            name = ch[cid]['name']
            await delete_channel(cid)
            await cb.answer(f"✅ Канал {name} удалён", False)
            new_ch = await get_all_channels()
            if not new_ch:
                await cb.message.delete()
                await cb.message.answer("Все каналы удалены", reply_markup=get_main_keyboard(cb.from_user.id))
            else:
                await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard(new_ch))
        else:
            await cb.answer("Канал не найден", True)

    # ========== ДОБАВЛЕНИЕ КАНАЛА ==========
    @dp.callback_query(F.data == "admin_add")
    async def adm_add_start(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        await cb.message.edit_text("➕ Выберите категорию для нового канала:", reply_markup=await get_category_selection_keyboard("add_chan_cat"))
        await state.set_state(AddChannelStates.waiting_for_category)
        await cb.answer()

    @dp.callback_query(F.data.startswith("add_chan_cat_"), AddChannelStates.waiting_for_category)
    async def add_channel_category_chosen(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        cat_id = int(cb.data.split("_")[3])
        await state.update_data(category_id=cat_id)
        await cb.message.edit_text("Введите название канала:", reply_markup=cancel_keyboard())
        await state.set_state(AddChannelStates.waiting_for_name)
        await cb.answer()

    @dp.message(AddChannelStates.waiting_for_name)
    async def a_name(m: Message, state: FSMContext):
        await state.update_data(name=m.text)
        await m.answer("Введите цену (число):", reply_markup=cancel_keyboard())
        await state.set_state(AddChannelStates.waiting_for_price)

    @dp.message(AddChannelStates.waiting_for_price)
    async def a_price(m: Message, state: FSMContext):
        if not m.text.isdigit():
            await m.answer("Введите число")
            return
        await state.update_data(price=int(m.text))
        await m.answer("Введите количество подписчиков (число):", reply_markup=cancel_keyboard())
        await state.set_state(AddChannelStates.waiting_for_subscribers)

    @dp.message(AddChannelStates.waiting_for_subscribers)
    async def a_subs(m: Message, state: FSMContext):
        if not m.text.isdigit():
            await m.answer("Введите число")
            return
        await state.update_data(subscribers=int(m.text))
        await m.answer("Введите ссылку (https://t.me/...):", reply_markup=cancel_keyboard())
        await state.set_state(AddChannelStates.waiting_for_url)

    @dp.message(AddChannelStates.waiting_for_url)
    async def a_url(m: Message, state: FSMContext):
        url = m.text.strip()
        if not url.startswith("https://t.me/"):
            await m.answer("Ссылка должна начинаться с https://t.me/")
            return
        await state.update_data(url=url)
        await m.answer("Введите описание канала:", reply_markup=cancel_keyboard())
        await state.set_state(AddChannelStates.waiting_for_description)

    @dp.message(AddChannelStates.waiting_for_description)
    async def a_desc(m: Message, state: FSMContext):
        await state.update_data(description=m.text)
        data = await state.get_data()
        new_id = f"channel_{int(time.time())}"
        cat_id = data['category_id']
        await add_channel(new_id, data['name'], data['price'], data['subscribers'], data['url'], data['description'], cat_id)
        cat = await get_category_by_id(cat_id)
        cat_name = cat['display_name'] if cat else ""
        await m.answer(f"✅ Канал {data['name']} добавлен в категорию {cat_name}!", reply_markup=get_admin_keyboard())
        await state.clear()

    # ========== ЗАЯВКИ (админ) ==========
    @dp.callback_query(F.data == "admin_orders")
    async def adm_orders(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        ords = await get_orders(20)
        if not ords: await cb.message.edit_text("Нет заявок", reply_markup=get_main_keyboard(cb.from_user.id)); await cb.answer(); return
        await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_order_"))
    async def adm_view_order(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        oid = int(cb.data.split("_")[2])
        ordd = await get_order_by_id(oid)
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
        order = await get_order_by_id(oid)
        if not order: await cb.answer("Заявка не найдена", True); return

        old_status = order['status']
        if new_st == 'отменена' and old_status == 'оплачена':
            await return_balance(order['user_id'], order['total'], oid, f"Возврат за отмену заказа #{oid} админом")
            try:
                await cb.bot.send_message(order['user_id'], f"📢 Ваша заявка #{oid} была отменена администратором. Средства возвращены на баланс.")
            except: pass
            for aid in ADMIN_IDS:
                if aid != cb.from_user.id:
                    try:
                        await cb.bot.send_message(aid, f"❌ Админ отменил заявку #{oid} (возврат {order['total']}$)")
                    except: pass

        await update_order_status(oid, new_st)
        await cb.answer(f"✅ Статус заявки #{oid} изменён на {new_st}", False)
        try:
            await cb.bot.send_message(order['user_id'], f"📢 Статус вашей заявки #{oid} изменён на: {new_st}")
        except: pass
        ords = await get_orders(20)
        await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))

    # ========== Админ‑статистика ==========
    @dp.callback_query(F.data == "admin_stats")
    async def admin_stats_cb(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        tot_ord, tot_sum = await conn.fetchrow("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders")
        stat = await conn.fetch("SELECT status, COUNT(*) FROM orders GROUP BY status")
        chan_cnt = await conn.fetchval("SELECT COUNT(*) FROM channels")
        week = await conn.fetch("SELECT DATE(created_at), COUNT(*), SUM(total) FROM orders WHERE created_at >= CURRENT_DATE - INTERVAL '7 days' GROUP BY DATE(created_at) ORDER BY DATE(created_at) ASC")
        await conn.close()
        status_lines = "\n".join(f"{'🟡' if s=='в обработке' else '🟢' if s=='оплачена' else '✅' if s=='выполнена' else '❌'} {s}: {c}" for s, c in stat)
        week_lines = "\n".join(f"{d}: {cnt} заявок, {s or 0}$" for d, cnt, s in week) if week else ""
        txt = f"📊 Статистика ESVIG Service\n\n📦 Всего заявок: {tot_ord}\n💰 Общая сумма: {tot_sum or 0}$\n📋 Каналов: {chan_cnt}\n\n🔄 По статусам:\n{status_lines}\n"
        if week_lines:
            txt += f"\n📅 Последние 7 дней:\n{week_lines}"
        await cb.message.edit_text(txt, reply_markup=get_stats_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_balance")
    async def admin_balance_start(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        await cb.message.edit_text("Введите Telegram ID пользователя:", reply_markup=cancel_keyboard())
        await state.set_state(AdminBalanceStates.waiting_for_user_id)
        await cb.answer()

    @dp.callback_query(F.data == "cancel_add_channel", AdminBalanceStates.waiting_for_user_id)
    async def cancel_balance_user(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.message(AdminBalanceStates.waiting_for_user_id)
    async def process_balance_user_id(m: Message, state: FSMContext):
        if not m.text.isdigit():
            await m.answer("Введите числовой ID")
            return
        target_id = int(m.text)
        await state.update_data(target_id=target_id)
        await m.answer("Введите сумму (положительное – пополнение, отрицательное – списание):", reply_markup=cancel_keyboard())
        await state.set_state(AdminBalanceStates.waiting_for_amount)

    @dp.message(AdminBalanceStates.waiting_for_amount)
    async def process_balance_amount(m: Message, state: FSMContext):
        try:
            amount = int(m.text.strip())
        except ValueError:
            await m.answer("Введите целое число")
            return
        data = await state.get_data()
        target_id = data['target_id']
        await get_or_create_user(target_id)
        if amount >= 0:
            await update_user_balance(target_id, amount, f"Ручное пополнение админом {m.from_user.id}")
            await m.answer(f"✅ Баланс пользователя {target_id} пополнен на {amount}$", reply_markup=get_admin_keyboard())
        else:
            success = await debit_balance(target_id, -amount, None, f"Ручное списание админом {m.from_user.id}")
            if success:
                await m.answer(f"✅ С баланса пользователя {target_id} списано {-amount}$", reply_markup=get_admin_keyboard())
            else:
                bal = await get_user_balance(target_id)
                await m.answer(f"❌ Недостаточно средств. Текущий баланс: {bal}$", reply_markup=get_admin_keyboard())
        await state.clear()

    # Очистка статистики
    @dp.callback_query(F.data == "confirm_clear_failed")
    async def ask_clear_failed(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, очистить неуспешные", callback_data="clear_failed_yes")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="clear_no")]
        ])
        await cb.message.edit_text("⚠️ Будут удалены все заявки со статусами «в обработке» и «отменена». Оплаченные и выполненные останутся.", reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data == "confirm_clear_all")
    async def ask_clear_all(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, полная очистка", callback_data="clear_all_yes")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="clear_no")]
        ])
        await cb.message.edit_text("⚠️ **Полная очистка**: будут удалены **все** заявки (и у вас, и у покупателей). Это действие необратимо.", reply_markup=kb, parse_mode="Markdown")
        await cb.answer()

    @dp.callback_query(F.data == "clear_failed_yes")
    async def clear_failed(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        try:
            await clear_non_successful_orders()
            await cb.message.edit_text("✅ Неуспешные заявки удалены.")
        except Exception as e:
            print(f"Ошибка очистки: {e}")
            await cb.message.edit_text("❌ Ошибка при очистке. Попробуйте позже.")
        await cb.answer()

    @dp.callback_query(F.data == "clear_all_yes")
    async def clear_all(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        try:
            await clear_all_orders()
            await cb.message.edit_text("✅ Все заявки удалены.")
        except Exception as e:
            print(f"Ошибка очистки: {e}")
            await cb.message.edit_text("❌ Ошибка при очистке. Попробуйте позже.")
        await cb.answer()

    @dp.callback_query(F.data == "clear_no")
    async def clear_no(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        await cb.message.delete()
        await cb.answer("Очистка отменена")

    # Текстовые сообщения
    @dp.message(F.text == "ℹ️ О сервисе")
    async def about(m: Message):
        await m.answer("ℹ️ О сервисе ESVIG Service\n\nМы помогаем размещать рекламу в проверенных Telegram-каналах крипто-тематики.\n\n✅ Наши преимущества:\n• Только каналы с высокой вовлечённостью (ER > 2%)\n• Полная предоплата от рекламодателя\n• Отчёт по каждому размещению\n• Быстрая связь с администраторами каналов")

    @dp.message(F.text == "❓ FAQ")
    async def faq(m: Message):
        await m.answer("❓ Часто задаваемые вопросы\n\n1️⃣ Как я могу оплатить рекламу?\n   Оплата принимается в USDT (TRC20 или BEP20). Вы переводите полную сумму нам, мы гарантируем размещение.\n\n2️⃣ Что если пост не выйдет?\n   Мы вернём 100% предоплаты. Случаев невыхода не было.\n\n3️⃣ Какой срок размещения?\n   Обычно пост выходит в течение 24 часов после оплаты.\n\n4️⃣ Могу ли я выбрать каналы сам?\n   Да, вы можете просмотреть каталог и добавить любые каналы в корзину.\n\n5️⃣ Как узнать статистику поста?\n   Через 24 часа после публикации мы пришлём вам отчёт: просмотры, реакции, ER.\n\nПо остальным вопросам пишите @esvig_support.")

    @dp.message(F.text == "📞 Контакты")
    async def contacts(m: Message):
        await m.answer("📞 Контакты\n\n• Support: @esvig_support\n• Наш канал: https://t.me/esvig_service\n• По поводу сотрудничества/рекламы: @zoldya_vv")

# ------------------ Flask и Webhooks ------------------
from aiohttp import web

bot_instance = Bot(token=BOT_TOKEN)
dp_instance = Dispatcher(storage=MemoryStorage())

# Инициализация БД и хендлеров
async def startup():
    await init_db()
    await register_handlers(dp_instance)
    # Удаляем вебхук Telegram, т.к. будем использовать Long Polling
    await bot_instance.delete_webhook(drop_pending_updates=True)
    print("Бот готов (Long Polling)")

# Асинхронная обработка платёжных вебхуков
async def cryptobot_handler(request):
    if not CRYPTO_BOT_TOKEN:
        return web.json_response({'status': 'error'}, status=403)
    body = await request.read()
    secret = hashlib.sha256(CRYPTO_BOT_TOKEN.encode()).digest()
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if request.headers.get('Crypto-Pay-Api-Signature') != signature:
        return web.json_response({'status': 'error'}, status=403)
    try:
        data = await request.json()
        if data.get('update_type') == 'invoice_paid':
            payload = data['payload']
            invoice = payload['invoice']
            desc = invoice.get('description', '')
            user_id = int(desc.split("user_id:")[1]) if "user_id:" in desc else None
            if user_id:
                amount = int(float(invoice['amount']))
                await update_user_balance(user_id, amount, f"Пополнение USDT {amount}$")
                try:
                    await bot_instance.send_message(user_id, f"✅ Ваш баланс пополнен на {amount}$. Спасибо!")
                except: pass
                for aid in ADMIN_IDS:
                    try:
                        await bot_instance.send_message(aid, f"💰 Пользователь {user_id} пополнил баланс на {amount}$")
                    except: pass
    except Exception as e:
        print(f"CryptoBot webhook error: {e}")
    return web.json_response({'status': 'ok'})

async def xrocket_handler(request):
    if not XROCKET_API_KEY:
        return web.json_response({'status': 'error'}, status=403)
    body = await request.read()
    secret = hashlib.sha256(XROCKET_API_KEY.encode()).digest()
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if request.headers.get('X-Signature') != signature:
        return web.json_response({'status': 'error'}, status=403)
    try:
        data = await request.json()
        if data.get('status') == 'paid':
            invoice = data.get('invoice', {})
            desc = invoice.get('description', '')
            user_id = int(desc.split("user_id:")[1]) if "user_id:" in desc else None
            if user_id:
                amount = int(float(invoice.get('amount', 0)))
                await update_user_balance(user_id, amount, f"Пополнение USDT {amount}$")
                try:
                    await bot_instance.send_message(user_id, f"✅ Ваш баланс пополнен на {amount}$. Спасибо!")
                except: pass
                for aid in ADMIN_IDS:
                    try:
                        await bot_instance.send_message(aid, f"💰 Пользователь {user_id} пополнил баланс на {amount}$")
                    except: pass
    except Exception as e:
        print(f"XRocket webhook error: {e}")
    return web.json_response({'status': 'ok'})

async def main():
    await startup()
    # Создаём aiohttp-приложение с платёжными эндпоинтами
    aio_app = web.Application()
    aio_app.router.add_post('/cryptobot', cryptobot_handler)
    aio_app.router.add_post('/xrocket', xrocket_handler)
    # Запускаем HTTP-сервер на порту из переменной окружения
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await site.start()
    print(f"Платёжный HTTP-сервер запущен на порту {os.environ.get('PORT', 8080)}")
    # Запускаем поллинг Telegram
    await dp_instance.start_polling(bot_instance, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
