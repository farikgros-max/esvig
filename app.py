import os
import asyncio
import json
import sqlite3
import hashlib
import re
import requests
import time
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask, request, jsonify
from database import init_db, get_all_channels, add_channel, delete_channel, update_channel, save_order, get_orders, get_orders_by_user, update_order_status, get_order_by_id, clear_non_successful_orders, clear_all_orders, get_all_categories, add_category, delete_category, get_category_by_id

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8524671546:AAHMk0g59VhU18p0r5gxYg-r9mVzz83JGmU"
ADMIN_IDS = [7787223469, 7345960167, 714447317, 8614748084, 8702300149, 8472548724]
ITEMS_PER_PAGE = 5
SECRET_TOKEN = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()
# ==================================

init_db()

class OrderForm(StatesGroup):
    waiting_for_budget = State()
    waiting_for_contact = State()

class AddChannelStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_subscribers = State()
    waiting_for_url = State()
    waiting_for_description = State()
    waiting_for_category = State()

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

channels = {}
user_carts = {}

def get_cart(uid):
    if uid not in user_carts:
        user_carts[uid] = []
    return user_carts[uid]

def save_cart(uid, cart):
    user_carts[uid] = cart

async def load_channels(category_id=None):
    global channels
    channels = get_all_channels(category_id)
    print(f"Загружено {len(channels)} каналов" + (f" для категории {category_id}" if category_id else ""))

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_channel")]])

# --- Клавиатуры ---
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
        [InlineKeyboardButton(text="🏷 Управление категориями", callback_data="admin_categories")]
    ])

def get_categories_keyboard():
    cats = get_all_categories()
    if not cats:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]])
    rows = []
    for i in range(0, len(cats), 2):
        row = []
        row.append(InlineKeyboardButton(text=cats[i]['display_name'], callback_data=f"select_category_{cats[i]['id']}"))
        if i+1 < len(cats):
            row.append(InlineKeyboardButton(text=cats[i+1]['display_name'], callback_data=f"select_category_{cats[i+1]['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_catalog_keyboard(category_id, page=0):
    if not channels:
        return None, 0, 0
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
    if page > 0: nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"view_catalog_page_{category_id}_{page-1}"))
    if page < tot - 1: nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"view_catalog_page_{category_id}_{page+1}"))
    if nav: btns.append(nav)
    btns.append([InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=btns), page, tot

def get_channel_view_keyboard(cid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в корзину", callback_data=f"add_{cid}")],
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

def get_categories_admin_keyboard():
    cats = get_all_categories()
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

def get_category_selection_keyboard(callback_prefix):
    cats = get_all_categories()
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

# --- Обработчики ---
async def register_handlers(dp: Dispatcher):
    @dp.message(Command("start"))
    async def start(m: Message):
        user_name = m.from_user.first_name or m.from_user.username or "Пользователь"
        text = f"Рад видеть тебя, {user_name}!\n\n💰 Твой баланс: 0$\n\n🚀 Приятных покупок! 🛍️"
        await m.answer(text, reply_markup=get_main_keyboard())

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
        await m.answer(txt, reply_markup=get_stats_keyboard())

    # ----- Очистка статистики -----
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
        clear_non_successful_orders()
        await cb.message.edit_text("✅ Неуспешные заявки удалены.")
        await cb.answer()

    @dp.callback_query(F.data == "clear_all_yes")
    async def clear_all(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        clear_all_orders()
        await cb.message.edit_text("✅ Все заявки удалены.")
        await cb.answer()

    @dp.callback_query(F.data == "clear_no")
    async def clear_no(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        await cb.message.delete()
        await cb.answer("Очистка отменена")

    # ----- Каталог -----
    @dp.message(F.text == "📋 Каталог каналов")
    async def catalog_start(m: Message):
        cats = get_all_categories()
        if not cats:
            await m.answer("Категории не найдены")
            return
        await m.answer("Выберите категорию:", reply_markup=get_categories_keyboard())

    @dp.callback_query(F.data.startswith("select_category_"))
    async def select_category(cb: CallbackQuery):
        cat_id = int(cb.data.split("_")[2])
        await load_channels(cat_id)
        if not channels:
            await cb.message.edit_text("В этой категории пока нет каналов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")]]))
            await cb.answer()
            return
        kb, page, total = get_catalog_keyboard(cat_id, 0)
        await cb.message.edit_text(f"📢 Каналы в категории (страница 1/{total})", reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data == "back_to_categories")
    async def back_to_categories(cb: CallbackQuery):
        cats = get_all_categories()
        if not cats:
            await cb.message.edit_text("Категории не найдены", reply_markup=get_back_keyboard())
            await cb.answer()
            return
        await cb.message.edit_text("Выберите категорию:", reply_markup=get_categories_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("view_catalog_page_"))
    async def view_catalog_page(cb: CallbackQuery):
        parts = cb.data.split("_")
        cat_id = int(parts[3])
        page = int(parts[4])
        await load_channels(cat_id)
        kb, cur, total = get_catalog_keyboard(cat_id, page)
        if kb:
            await cb.message.edit_text(f"📢 Каналы в категории (страница {cur+1}/{total})", reply_markup=kb)
        else:
            await cb.message.edit_text("Каталог пуст", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")]]))
        await cb.answer()

    @dp.callback_query(F.data == "back_to_catalog")
    async def back_to_catalog(cb: CallbackQuery):
        cats = get_all_categories()
        if not cats:
            await cb.message.edit_text("Категории не найдены", reply_markup=get_back_keyboard())
            await cb.answer()
            return
        await cb.message.edit_text("Выберите категорию:", reply_markup=get_categories_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "back_to_main_menu")
    async def back_main_menu(cb: CallbackQuery):
        await cb.message.delete()
        await cb.message.answer("Главное меню:", reply_markup=get_main_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("view_"))
    async def view_channel(cb: CallbackQuery):
        cid = cb.data.replace("view_", "")
        info = get_all_channels().get(cid)
        if not info:
            await cb.answer("Канал не найден", True)
            return
        cat_name = ""
        if info.get('category_id'):
            cat = get_category_by_id(info['category_id'])
            if cat:
                cat_name = cat['display_name']
        txt = f"📌 {info['name']}\n👥 Подписчиков: {info['subscribers']}\n💰 Цена: {info['price']}$\n🔗 Ссылка: {info['url']}\n📝 Описание:\n{info.get('description','Нет описания')}"
        if cat_name:
            txt += f"\n🏷 Категория: {cat_name}"
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

    # ----- Корзина, оформление, профиль -----
    @dp.message(F.text == "🛒 Корзина")
    async def cart(m: Message):
        c = get_cart(m.from_user.id)
        if not c:
            await m.answer("Корзина пуста")
            return
        total = sum(i['price'] for i in c)
        txt = "🛒 Ваша корзина:\n\n" + "\n".join(f"{idx+1}. {i['name']} — {i['price']}$" for idx,i in enumerate(c)) + f"\n\nИтого: {total}$"
        await m.answer(txt, reply_markup=get_cart_keyboard(m.from_user.id))

    @dp.callback_query(F.data == "clear_cart")
    async def clear_cart(cb: CallbackQuery):
        user_carts[cb.from_user.id] = []
        await cb.answer("🗑 Корзина очищена", False)
        await cb.message.delete()
        await cb.message.answer("Корзина пуста", reply_markup=get_main_keyboard())

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
                await cb.message.answer("Корзина пуста", reply_markup=get_main_keyboard())
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
            await cb.message.edit_text("Корзина пуста", reply_markup=get_main_keyboard())
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
        order_id = save_order(m.from_user.id, username, cart, total, budget, contact)
        items = "\n".join(f"• {i['name']} — {i['price']}$" for i in cart)
        report = f"🟢 НОВАЯ ЗАЯВКА\n👤 @{username}\n📦 Состав:\n{items}\n💰 Сумма: {total}$\n💵 Бюджет: {budget}$\n📞 Контакт: {contact}"
        for aid in ADMIN_IDS:
            try:
                await m.bot.send_message(aid, report)
            except: pass
        user_carts[m.from_user.id] = []
        await m.answer("✅ Заявка отправлена! Менеджер свяжется с вами.", reply_markup=get_main_keyboard())
        await state.clear()

    @dp.message(F.text == "👤 Мой профиль")
    async def profile(m: Message):
        completed_orders = get_orders_by_user(m.from_user.id, limit=1000, only_completed=True)
        total_spent = sum(o['total'] for o in completed_orders)
        total_orders = len(completed_orders)
        txt = f"👤 Мой профиль\n\n🆔 ID: {m.from_user.id}\n📛 Username: @{m.from_user.username or 'не указан'}\n📦 Успешных заказов: {total_orders}\n💰 Общая сумма трат: {total_spent}$\n💳 Баланс: 0$ (пополнение временно недоступно)"
        await m.answer(txt, reply_markup=get_profile_keyboard())

    @dp.callback_query(F.data == "my_orders")
    async def my_ords(cb: CallbackQuery):
        ords = get_orders_by_user(cb.from_user.id, 10, only_completed=False)
        if not ords:
            await cb.message.edit_text("📭 У вас пока нет заявок.", reply_markup=get_main_keyboard())
            await cb.answer()
            return
        txt = "📊 Ваши заявки:\n\n"
        em = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}
        for o in ords:
            txt += f"🆔 №{o['id']}\n💰 Сумма: {o['total']}$\n📦 Товаров: {len(o['cart'])}\n📌 Статус: {em.get(o['status'],'⚪')} {o['status']}\n🕒 {o['created_at']}\n➖➖➖➖➖\n"
        await cb.message.edit_text(txt, reply_markup=get_main_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "deposit")
    async def dep(cb: CallbackQuery):
        await cb.message.edit_text("💰 Пополнение баланса временно недоступно.\n\nСкоро мы добавим эту возможность.", reply_markup=get_main_keyboard())
        await cb.answer()

    @dp.message(F.text == "ℹ️ О сервисе")
    async def about(m: Message):
        txt = "ℹ️ О сервисе ESVIG Service\n\nМы помогаем размещать рекламу в проверенных Telegram-каналах крипто-тематики.\n\n✅ Наши преимущества:\n• Только каналы с высокой вовлечённостью (ER > 2%)\n• Полная предоплата от рекламодателя\n• Отчёт по каждому размещению\n• Быстрая связь с администраторами каналов"
        await m.answer(txt)

    @dp.message(F.text == "❓ FAQ")
    async def faq(m: Message):
        txt = "❓ Часто задаваемые вопросы\n\n1️⃣ Как я могу оплатить рекламу?\n   Оплата принимается в USDT (TRC20 или BEP20). Вы переводите полную сумму нам, мы гарантируем размещение.\n\n2️⃣ Что если пост не выйдет?\n   Мы вернём 100% предоплаты. Случаев невыхода не было.\n\n3️⃣ Какой срок размещения?\n   Обычно пост выходит в течение 24 часов после оплаты.\n\n4️⃣ Могу ли я выбрать каналы сам?\n   Да, вы можете просмотреть каталог и добавить любые каналы в корзину.\n\n5️⃣ Как узнать статистику поста?\n   Через 24 часа после публикации мы пришлём вам отчёт: просмотры, реакции, ER.\n\nПо остальным вопросам пишите @esvig_support."
        await m.answer(txt)

    @dp.message(F.text == "📞 Контакты")
    async def contacts(m: Message):
        txt = "📞 Контакты\n\n• Support: @esvig_support\n• Наш канал: https://t.me/esvig_service\n• По поводу сотрудничества/рекламы: @zoldya_vv"
        await m.answer(txt)

    # ---------- Админ-панель (каналы, заявки, категории) ----------
    @dp.callback_query(F.data == "cancel_add_channel")
    async def cancel_add_channel(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", show_alert=True)
            return
        await state.clear()
        await cb.message.edit_text("👑 Админ-панель", reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_back")
    async def adm_back(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await cb.message.edit_text("👑 Админ-панель", reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_categories")
    async def admin_categories_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await cb.message.edit_text("🏷 Управление категориями", reply_markup=get_categories_admin_keyboard())
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
        add_category(name, display)
        await m.answer(f"✅ Категория '{display}' добавлена", reply_markup=get_admin_keyboard())
        await state.clear()

    @dp.callback_query(F.data.startswith("admin_category_"))
    async def admin_category_detail(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        cat_id = int(cb.data.split("_")[2])
        cat = get_category_by_id(cat_id)
        if not cat:
            await cb.answer("Категория не найдена", True)
            return
        await cb.message.edit_text(f"Категория: {cat['display_name']} (id={cat_id}, имя={cat['name']})", reply_markup=get_category_actions_keyboard(cat_id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_del_category_"))
    async def admin_del_category(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        cat_id = int(cb.data.split("_")[3])
        delete_category(cat_id)
        await cb.answer("Категория удалена", False)
        await admin_categories_menu(cb)

    @dp.callback_query(F.data == "admin_list")
    async def adm_list(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await load_channels()
        if not channels: await cb.message.edit_text("Список каналов пуст", reply_markup=get_main_keyboard()); await cb.answer(); return
        await cb.message.edit_text("📋 Список каналов\nНажмите на канал для подробностей:", reply_markup=get_admin_list_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_view_"))
    async def adm_view_chan(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await load_channels()
        cid = cb.data.replace("admin_view_", "")
        ch = channels.get(cid)
        if not ch: await cb.answer("Канал не найден", True); return
        cat_name = ""
        if ch.get('category_id'):
            cat = get_category_by_id(ch['category_id'])
            if cat:
                cat_name = cat['display_name']
        txt = f"📌 {ch['name']}\n🔗 {ch['url']}\n💰 {ch['price']}$\n👥 {ch['subscribers']} подп.\n📝 {ch.get('description','Нет описания')}\n🆔 {cid}"
        if cat_name:
            txt += f"\n🏷 Категория: {cat_name}"
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
        if field == 'category':
            await cb.message.edit_text("Выберите новую категорию:", reply_markup=get_category_selection_keyboard(f"edit_chan_cat_{cid}"))
            await state.set_state(EditChannelStates.waiting_for_category)
        else:
            prompts = {'name':'Введите новое название:','price':'Введите новую цену (число):','subscribers':'Введите новый охват (число):','url':'Введите новую ссылку (https://t.me/...):','description':'Введите новое описание:'}
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
        update_channel(cid, category_id=cat_id)
        await load_channels()
        await cb.answer("Категория обновлена", False)
        await adm_view_chan(CallbackQuery(id=0, from_user=cb.from_user, message=cb.message, data=f"admin_view_{cid}"))
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_name)
    async def e_name(m: Message, state: FSMContext):
        d = await state.get_data()
        update_channel(d['ch_id'], name=m.text)
        await load_channels()
        await m.answer(f"✅ Название изменено на {m.text}")
        await state.clear()
        await adm_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_price)
    async def e_price(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        d = await state.get_data()
        update_channel(d['ch_id'], price=int(m.text))
        await load_channels()
        await m.answer(f"✅ Цена изменена на {m.text}$")
        await state.clear()
        await adm_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_subscribers)
    async def e_subs(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        d = await state.get_data()
        update_channel(d['ch_id'], subscribers=int(m.text))
        await load_channels()
        await m.answer(f"✅ Охват изменён на {m.text}")
        await state.clear()
        await adm_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

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
        await adm_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.message(EditChannelStates.waiting_for_description)
    async def e_desc(m: Message, state: FSMContext):
        d = await state.get_data()
        update_channel(d['ch_id'], description=m.text)
        await load_channels()
        await m.answer("✅ Описание изменено")
        await state.clear()
        await adm_list(CallbackQuery(id=0, from_user=m.from_user, message=m, data="admin_list"))

    @dp.callback_query(F.data == "admin_remove")
    async def adm_rem_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await load_channels()
        if not channels: await cb.message.edit_text("Нет каналов для удаления", reply_markup=get_main_keyboard()); await cb.answer(); return
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
                await cb.message.edit_text("Все каналы удалены", reply_markup=get_main_keyboard())
            else:
                await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard())
        else:
            await cb.answer("Канал не найден", True)

    @dp.callback_query(F.data == "admin_add")
    async def adm_add_start(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        await cb.message.edit_text("➕ Добавление канала\n\nВведите название:", reply_markup=cancel_keyboard())
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
        await m.answer("Введите охват (число):", reply_markup=cancel_keyboard())
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
        await m.answer("Выберите категорию канала:", reply_markup=get_category_selection_keyboard("add_chan_cat"))
        await state.set_state(AddChannelStates.waiting_for_category)

    @dp.callback_query(F.data.startswith("add_chan_cat_"))
    async def add_channel_category_selected(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("Нет прав", True)
            return
        # Извлекаем cat_id
        try:
            cat_id = int(cb.data.split("_")[3])
        except (IndexError, ValueError):
            await cb.answer("Ошибка: неверный формат категории", True)
            return
        data = await state.get_data()
        if not data:
            await cb.answer("Ошибка: данные канала не найдены", True)
            return
        new_id = f"channel_{int(time.time())}"
        add_channel(new_id, data['name'], data['price'], data['subscribers'], data['url'], data['description'], cat_id)
        await load_channels()
        cat = get_category_by_id(cat_id)
        cat_name = cat['display_name'] if cat else "неизвестная"
        await cb.message.edit_text(f"✅ Канал {data['name']} добавлен в категорию {cat_name}!")
        await state.clear()
        await cb.message.answer("Вернуться в админ-панель:", reply_markup=get_admin_keyboard())

    @dp.callback_query(F.data == "admin_orders")
    async def adm_orders(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
        ords = get_orders(20)
        if not ords: await cb.message.edit_text("Нет заявок", reply_markup=get_main_keyboard()); await cb.answer(); return
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

# ------------------ Flask ------------------
flask_app = Flask(__name__)
app = flask_app

bot_instance = Bot(token=BOT_TOKEN)
dp_instance = Dispatcher(storage=MemoryStorage())

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(register_handlers(dp_instance))
print("Бот готов")

def set_webhook_on_startup():
    webhook_url = "https://esvig-production.up.railway.app/webhook"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url, "secret_token": SECRET_TOKEN}
        )
        print(f"Webhook set result: {r.json()}")
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
