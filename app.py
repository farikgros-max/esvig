import os
import asyncio
import json
import hashlib
import hmac
import asyncpg
import requests
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
                           Update, ReplyKeyboardMarkup, KeyboardButton, FSInputFile)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask, request, jsonify
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import (init_db, get_all_channels, add_channel, delete_channel, update_channel,
                      save_order, get_orders, get_orders_by_user, update_order_status,
                      get_order_by_id, clear_non_successful_orders, clear_all_orders,
                      get_all_categories, add_category, delete_category, get_category_by_id,
                      close_db, get_or_create_user, update_user_balance, get_user_balance,
                      debit_balance, return_balance, get_user_transactions,
                      update_channel_metrics_db, check_daily_order_limit, get_user_daily_info,
                      get_user_language, set_user_language)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8524671546:AAHMk0g59VhU18p0r5gxYg-r9mVzz83JGmU"
ADMIN_IDS = [7787223469, 7345960167, 714447317, 8614748084, 8702300149, 8472548724]
ITEMS_PER_PAGE = 5
SECRET_TOKEN = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()
WEBHOOK_URL = "https://esvig-production-4961.up.railway.app/webhook"
CRYPTO_BOT_TOKEN = os.environ.get("CRYPTO_BOT_TOKEN", "")
MIN_DEPOSIT = 0.1
PAID_BTN_URL = "https://t.me/esvig_bot"
DAILY_ORDER_LIMIT = 3
# ==================================

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
    channels = await get_all_channels(category_id)
    print(f"Загружено {len(channels)} каналов" + (f" для категории {category_id}" if category_id else ""))

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_channel")]])

# --- Клавиатуры ---
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
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data="admin_balance"),
         InlineKeyboardButton(text="🔄 Обновить метрики", callback_data="admin_refresh_metrics")],
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

def get_catalog_keyboard(category_id, page=0, sort_by="default"):
    if not channels:
        return None, 0, 0
    items = list(channels.items())
    if sort_by == "price_asc":
        items.sort(key=lambda x: x[1]['price'])
    elif sort_by == "price_desc":
        items.sort(key=lambda x: x[1]['price'], reverse=True)
    elif sort_by == "subs_asc":
        items.sort(key=lambda x: x[1]['subscribers'])
    elif sort_by == "subs_desc":
        items.sort(key=lambda x: x[1]['subscribers'], reverse=True)

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
        [InlineKeyboardButton(text="✏️ Подписчики", callback_data=f"edit_{cid}_subscribers")],
        [InlineKeyboardButton(text="✏️ Ссылка", callback_data=f"edit_{cid}_url")],
        [InlineKeyboardButton(text="✏️ Описание", callback_data=f"edit_{cid}_description")],
        [InlineKeyboardButton(text="✏️ Категория", callback_data=f"edit_{cid}_category")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_view_{cid}")]
    ])

def get_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мои заявки", callback_data="my_orders")],
        [InlineKeyboardButton(text="📊 История", callback_data="transaction_history")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="🌐 Switch Language", callback_data="switch_language")],
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

# ========================= ОБНОВЛЕНИЕ МЕТРИК =========================
async def update_channel_metrics(bot: Bot, ch_id, ch_url):
    try:
        if "t.me/" in ch_url:
            username = ch_url.split("t.me/")[1].strip("/")
        else:
            return f"skipped: некорректная ссылка {ch_url}"
        if username.startswith("+"):
            return f"skipped: приватная ссылка (не поддерживается) {username}"
        chat = await bot.get_chat(f"@{username}")
        subs = await bot.get_chat_member_count(chat.id)
    except Exception as e:
        err = str(e)
        if "chat not found" in err.lower():
            return f"error: канал @{username} не найден (бот не добавлен?)"
        elif "forbidden" in err.lower():
            return f"error: бот заблокирован или не состоит в @{username}"
        elif "too many requests" in err.lower():
            return f"error: превышен лимит запросов, попробуйте позже ({username})"
        else:
            return f"error: {err[:100]}"
    views_list = []
    try:
        async for msg in bot.get_chat_history(chat.id, limit=5):
            if msg.views:
                views_list.append(msg.views)
    except:
        pass
    views_avg = sum(views_list) // len(views_list) if views_list else 0
    er = (views_avg / subs * 100) if subs > 0 else 0.0
    await update_channel_metrics_db(ch_id, subs, round(er, 2), views_avg)
    return "ok"

async def refresh_all_channels_metrics(bot: Bot):
    all_ch = await get_all_channels()
    if not all_ch:
        return "❌ В базе нет каналов.", []
    total = len(all_ch)
    ok_list = []
    error_list = []
    for ch_id, info in all_ch.items():
        res = await update_channel_metrics(bot, ch_id, info['url'])
        if res == "ok":
            ok_list.append(info['name'])
        else:
            error_list.append(f"{info.get('name', ch_id)}: {res}")
    report = f"✅ Обновлено: {len(ok_list)} из {total}"
    if error_list:
        report += "\n❌ Ошибки:\n" + "\n".join(f"• {e}" for e in error_list)
    return report, error_list

# ========================= МУЛЬТИЯЗЫЧНОСТЬ =========================
LANGUAGES = {
    'ru': {
        'start': "Рад видеть тебя, {name}!\n\n💰 Твой баланс: {balance}$\n\n🚀 Приятных покупок! 🛍️",
        'admin': "👑 Админ-панель",
        'no_rights': "Нет прав",
        'catalog': "📋 Каталог каналов",
        'cart': "🛒 Корзина",
        'profile': "👤 Мой профиль",
        'about': "ℹ️ О сервисе",
        'faq': "❓ FAQ",
        'contacts': "📞 Контакты",
        'admin_panel_btn': "🔑 Админ-панель",
        'cart_empty': "Корзина пуста",
        'cart_total': "🛒 Ваша корзина:\n\n{items}\n\nИтого: {total}$",
        'cart_clear': "🗑 Корзина очищена",
        'cart_cleared': "Корзина пуста",
        'remove_item': "❌ {name} удалён",
        'checkout': "💳 Оформление заказа",
        'enter_budget': "💳 Оформление заказа\n\nСумма: {total}$\nВведите ваш бюджет (цифрами, ≥ суммы):",
        'budget_low': "Бюджет ({budget}$) меньше суммы ({total}$). Введите {total}$ или больше:",
        'enter_contact': "Напишите ваш Telegram username (например, @username) или другой контакт:",
        'daily_limit_reached': "❌ Вы исчерпали дневной лимит заявок ({limit}). Попробуйте завтра.",
        'insufficient_funds': "❌ Недостаточно средств. Ваш баланс: {balance}$, сумма заказа: {total}$.\nПополните баланс в разделе «👤 Мой профиль» → «💰 Пополнить баланс».",
        'order_success': "✅ Заказ #{order_id} оформлен и оплачен! Сумма {total}$ списана с баланса.\nМенеджер скоро свяжется с вами.",
        'profile_text': "👤 Мой профиль\n\n🆔 ID: {user_id}\n📛 Username: @{username}\n📦 Успешных заказов: {total_orders}\n💰 Общая сумма трат: {total_spent}$\n💳 Баланс: {balance}$\n📅 Осталось заявок сегодня: {left_orders}/{daily_limit}",
        'transaction_history': "📊 Последние транзакции:\n\n",
        'tx_empty': "История пуста",
        'deposit_prompt': "💰 Введите сумму пополнения в USDT (минимум {min_deposit}$):",
        'my_orders': "📊 Ваши заявки:\n\n",
        'no_orders': "📭 У вас пока нет заявок.",
        'order_status': "🆔 №{id}\n💰 Сумма: {total}$\n📦 Товаров: {count}\n📌 Статус: {status_text}\n🕒 {created}\n➖➖➖➖➖\n",
        'switch_lang': "🌐 Switch Language",
        'lang_switched': "✅ Язык изменён на {language}",
        'main_menu': "Главное меню:",
        'back_to_main': "🔙 На главную",
        'cancel': "❌ Отмена",
        'add_to_cart': "✅ {name} добавлен в корзину!",
        'channel_not_found': "Канал не найден",
        'category_empty': "В этой категории пока нет каналов.",
        'back_to_categories': "🔙 Назад к категориям",
        'catalog_page': "📢 Каналы в категории (страница {page}/{total})",
        'sort_price_asc': "🔽 Цена",
        'sort_price_desc': "🔼 Цена",
        'sort_subs_asc': "🔽 Подп.",
        'sort_subs_desc': "🔼 Подп.",
        'prev_page': "◀️ Назад",
        'next_page': "Вперёд ▶️",
        'channel_info': "📌 {name}\n👥 Подписчиков: {subscribers}\n💰 Цена: {price}$\n🔗 Ссылка: {url}\n📝 Описание:\n{description}",
        'channel_er': "\n📊 ER: {er}%",
        'channel_views_avg': "\n📈 Средний охват: {views_avg}",
        'edit_channel': "Редактирование канала {name}\nВыберите, что изменить:",
        'admin_list': "📋 Список каналов\nНажмите на канал для подробностей:",
        'admin_orders': "📋 Список заявок:",
        'admin_no_channels': "Список каналов пуст",
        'admin_no_orders': "Нет заявок",
        'admin_remove': "❌ Выберите канал для удаления:",
        'channel_added': "✅ Канал {name} добавлен в категорию {category}!",
        'channel_deleted': "✅ Канал {name} удалён",
        'all_channels_deleted': "Все каналы удалены",
        'order_report': "🟢 НОВАЯ ОПЛАЧЕННАЯ ЗАЯВКА #{order_id}\n👤 @{username}\n📦 Состав:\n{items}\n💰 Сумма: {total}$\n💵 Бюджет: {budget}$\n📞 Контакт: {contact}",
        'order_cancelled_user': "❌ Заявка #{order_id} отменена пользователем @{username} (сумма {total}$). Деньги возвращены.",
        'order_cancelled_admin': "❌ Админ отменил заявку #{order_id} (возврат {total}$)",
        'status_changed': "📢 Статус вашей заявки #{order_id} изменён на: {new_status}",
        'balance_changed': "✅ Баланс пользователя {target_id} пополнен на {amount}$",
        'balance_debited': "✅ С баланса пользователя {target_id} списано {amount}$",
        'balance_not_enough': "❌ Недостаточно средств для списания. Текущий баланс: {balance}$",
        'tx_population': "🔵",
        'tx_writeoff': "🔴",
        'tx_refund': "🟢",
        'enter_number': "Пожалуйста, введите число",
        'min_deposit_error': "Минимальная сумма пополнения — {min_deposit} USDT. Попробуйте ещё раз.",
        'payment_unavailable': "Платёжная система временно недоступна.",
        'invoice_error': "Ошибка при создании счёта. Попробуйте позже.",
        'connection_error': "Ошибка связи с платёжной системой.",
        'debit_error': "Не удалось списать средства. Заказ отменён. Обратитесь в поддержку.",
        'cannot_cancel': "Эту заявку уже нельзя отменить",
        'confirm_cancel': "⚠️ Вы уверены, что хотите отменить заявку #{order_id} на сумму {total}$?\nДеньги будут возвращены на баланс.",
        'order_cancelled': "Заявка отменена, деньги возвращены на баланс",
        'admin_stats_text': "📊 Статистика ESVIG Service\n\n📦 Всего заявок: {total_orders}\n💰 Общая сумма: {total_sum}$\n📋 Каналов: {channel_count}\n\n🔄 По статусам:\n{statuses}\n{week_info}",
        'admin_week_info': "📅 Последние 7 дней:\n{week_rows}",
        'admin_no_week_info': "📭 За последние 7 дней заявок нет.",
        'admin_balance_start': "Введите Telegram ID пользователя, которому нужно изменить баланс:",
        'admin_balance_amount': "Введите сумму для изменения баланса (положительное – пополнение, отрицательное – списание):",
        'admin_balance_success': "✅ Баланс пользователя {target_id} пополнен на {amount}$",
        'admin_balance_debit': "✅ С баланса пользователя {target_id} списано {amount}$",
        'admin_balance_fail': "❌ Недостаточно средств для списания. Текущий баланс: {balance}$",
        'admin_invalid_id': "Пожалуйста, введите числовой ID.",
        'admin_invalid_amount': "Введите целое число (например, 100 или -50).",
    },
    'en': {
        'start': "Welcome, {name}!\n\n💰 Your balance: {balance}$\n\n🚀 Happy shopping! 🛍️",
        'admin': "👑 Admin Panel",
        'no_rights': "No rights",
        'catalog': "📋 Channel Catalog",
        'cart': "🛒 Cart",
        'profile': "👤 My Profile",
        'about': "ℹ️ About",
        'faq': "❓ FAQ",
        'contacts': "📞 Contacts",
        'admin_panel_btn': "🔑 Admin Panel",
        'cart_empty': "Cart is empty",
        'cart_total': "🛒 Your cart:\n\n{items}\n\nTotal: {total}$",
        'cart_clear': "🗑 Cart cleared",
        'cart_cleared': "Cart is empty",
        'remove_item': "❌ {name} removed",
        'checkout': "💳 Checkout",
        'enter_budget': "💳 Checkout\n\nAmount: {total}$\nEnter your budget (digits, ≥ total):",
        'budget_low': "Budget ({budget}$) is less than amount ({total}$). Enter {total}$ or more:",
        'enter_contact': "Enter your Telegram username (e.g., @username) or contact:",
        'daily_limit_reached': "❌ You have reached your daily order limit ({limit}). Try again tomorrow.",
        'insufficient_funds': "❌ Insufficient funds. Your balance: {balance}$, order amount: {total}$.\nTop up your balance in «👤 My Profile» → «💰 Top Up».",
        'order_success': "✅ Order #{order_id} placed and paid! Amount {total}$ deducted from your balance.\nA manager will contact you soon.",
        'profile_text': "👤 My Profile\n\n🆔 ID: {user_id}\n📛 Username: @{username}\n📦 Successful orders: {total_orders}\n💰 Total spent: {total_spent}$\n💳 Balance: {balance}$\n📅 Orders left today: {left_orders}/{daily_limit}",
        'transaction_history': "📊 Recent transactions:\n\n",
        'tx_empty': "History is empty",
        'deposit_prompt': "💰 Enter top-up amount in USDT (min {min_deposit}$):",
        'my_orders': "📊 Your orders:\n\n",
        'no_orders': "📭 You have no orders yet.",
        'order_status': "🆔 #{id}\n💰 Amount: {total}$\n📦 Items: {count}\n📌 Status: {status_text}\n🕒 {created}\n➖➖➖➖➖\n",
        'switch_lang': "🌐 Switch Language",
        'lang_switched': "✅ Language changed to {language}",
        'main_menu': "Main menu:",
        'back_to_main': "🔙 Main Menu",
        'cancel': "❌ Cancel",
        'add_to_cart': "✅ {name} added to cart!",
        'channel_not_found': "Channel not found",
        'category_empty': "No channels in this category yet.",
        'back_to_categories': "🔙 Back to categories",
        'catalog_page': "📢 Channels in category (page {page}/{total})",
        'sort_price_asc': "🔽 Price",
        'sort_price_desc': "🔼 Price",
        'sort_subs_asc': "🔽 Subs",
        'sort_subs_desc': "🔼 Subs",
        'prev_page': "◀️ Prev",
        'next_page': "Next ▶️",
        'channel_info': "📌 {name}\n👥 Subscribers: {subscribers}\n💰 Price: {price}$\n🔗 Link: {url}\n📝 Description:\n{description}",
        'channel_er': "\n📊 ER: {er}%",
        'channel_views_avg': "\n📈 Avg views: {views_avg}",
        'edit_channel': "Edit channel {name}\nChoose what to change:",
        'admin_list': "📋 Channel list\nClick on a channel for details:",
        'admin_orders': "📋 Orders:",
        'admin_no_channels': "Channel list is empty",
        'admin_no_orders': "No orders",
        'admin_remove': "❌ Select a channel to delete:",
        'channel_added': "✅ Channel {name} added to category {category}!",
        'channel_deleted': "✅ Channel {name} deleted",
        'all_channels_deleted': "All channels deleted",
        'order_report': "🟢 NEW PAID ORDER #{order_id}\n👤 @{username}\n📦 Items:\n{items}\n💰 Total: {total}$\n💵 Budget: {budget}$\n📞 Contact: {contact}",
        'order_cancelled_user': "❌ Order #{order_id} cancelled by @{username} (amount {total}$). Refunded.",
        'order_cancelled_admin': "❌ Admin cancelled order #{order_id} (refund {total}$)",
        'status_changed': "📢 Your order #{order_id} status changed to: {new_status}",
        'balance_changed': "✅ User {target_id} balance increased by {amount}$",
        'balance_debited': "✅ User {target_id} balance decreased by {amount}$",
        'balance_not_enough': "❌ Insufficient funds for debit. Current balance: {balance}$",
        'tx_population': "🔵",
        'tx_writeoff': "🔴",
        'tx_refund': "🟢",
        'enter_number': "Please enter a number",
        'min_deposit_error': "Minimum top-up amount is {min_deposit} USDT. Try again.",
        'payment_unavailable': "Payment system is temporarily unavailable.",
        'invoice_error': "Error creating invoice. Try again later.",
        'connection_error': "Communication error with payment system.",
        'debit_error': "Could not debit funds. Order cancelled. Contact support.",
        'cannot_cancel': "This order can no longer be cancelled",
        'confirm_cancel': "⚠️ Are you sure you want to cancel order #{order_id} for {total}$?\nThe funds will be refunded to your balance.",
        'order_cancelled': "Order cancelled, funds returned to your balance",
        'admin_stats_text': "📊 ESVIG Service Statistics\n\n📦 Total orders: {total_orders}\n💰 Total amount: {total_sum}$\n📋 Channels: {channel_count}\n\n🔄 By status:\n{statuses}\n{week_info}",
        'admin_week_info': "📅 Last 7 days:\n{week_rows}",
        'admin_no_week_info': "📭 No orders in the last 7 days.",
        'admin_balance_start': "Enter Telegram ID of the user to change balance:",
        'admin_balance_amount': "Enter the amount to change balance (positive – top up, negative – debit):",
        'admin_balance_success': "✅ User {target_id} balance increased by {amount}$",
        'admin_balance_debit': "✅ User {target_id} balance decreased by {amount}$",
        'admin_balance_fail': "❌ Insufficient funds for debit. Current balance: {balance}$",
        'admin_invalid_id': "Please enter a numeric ID.",
        'admin_invalid_amount': "Enter an integer (e.g., 100 or -50).",
    }
}

async def _(user_id, key, **kwargs):
    lang = await get_user_language(user_id)
    texts = LANGUAGES.get(lang, LANGUAGES['ru'])
    template = texts.get(key, key)
    try:
        return template.format(**kwargs)
    except KeyError:
        return template

# --- Обработчики ---
async def register_handlers(dp: Dispatcher):
    @dp.message(Command("start"))
    async def start(m: Message):
        user = await get_or_create_user(m.from_user.id, m.from_user.username or "Пользователь")
        user_name = m.from_user.first_name or m.from_user.username or "Пользователь"
        caption = await _(m.from_user.id, 'start', name=user_name, balance=user['balance'])
        try:
            photo = FSInputFile("welcome.jpg")
            await m.answer_photo(photo, caption=caption, reply_markup=get_main_keyboard(m.from_user.id))
        except Exception:
            await m.answer(caption, reply_markup=get_main_keyboard(m.from_user.id))

    @dp.message(F.text == "🔑 Админ‑панель")
    async def admin_panel_msg(m: Message):
        if m.from_user.id in ADMIN_IDS:
            await m.answer(await _(m.from_user.id, 'admin'), reply_markup=get_admin_keyboard())
        else:
            await m.answer(await _(m.from_user.id, 'no_rights'))

    @dp.callback_query(F.data == "switch_language")
    async def switch_language(cb: CallbackQuery):
        lang = await get_user_language(cb.from_user.id)
        new_lang = 'en' if lang == 'ru' else 'ru'
        await set_user_language(cb.from_user.id, new_lang)
        await cb.answer(await _(cb.from_user.id, 'lang_switched', language=new_lang.upper()), False)
        user = await get_or_create_user(cb.from_user.id)
        daily_limit, daily_used = await get_user_daily_info(cb.from_user.id)
        left = max(daily_limit - daily_used, 0)
        completed = await get_orders_by_user(cb.from_user.id, limit=1000, only_completed=True)
        total_spent = sum(o['total'] for o in completed)
        txt = await _(cb.from_user.id, 'profile_text',
                      user_id=user['user_id'],
                      username=user.get('username', 'не указан'),
                      total_orders=len(completed),
                      total_spent=total_spent,
                      balance=user['balance'],
                      left_orders=left,
                      daily_limit=daily_limit)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 " + (await _(cb.from_user.id, 'my_orders')).split("\n")[0], callback_data="my_orders")],
            [InlineKeyboardButton(text=(await _(cb.from_user.id, 'transaction_history')).split("\n")[0], callback_data="transaction_history")],
            [InlineKeyboardButton(text="💰 " + (await _(cb.from_user.id, 'deposit_prompt', min_deposit=MIN_DEPOSIT)).split("\n")[0], callback_data="deposit")],
            [InlineKeyboardButton(text=await _(cb.from_user.id, 'switch_lang'), callback_data="switch_language")],
            [InlineKeyboardButton(text=await _(cb.from_user.id, 'back_to_main'), callback_data="back_to_main_menu")],
        ])
        await cb.message.edit_text(txt, reply_markup=kb)

    # ========= Очистка статистики =========
    @dp.callback_query(F.data == "confirm_clear_failed")
    async def ask_clear_failed(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer(await _(cb.from_user.id, 'no_rights'), show_alert=True)
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
            await cb.answer(await _(cb.from_user.id, 'no_rights'), show_alert=True)
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
            await cb.answer(await _(cb.from_user.id, 'no_rights'), show_alert=True)
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
            await cb.answer(await _(cb.from_user.id, 'no_rights'), show_alert=True)
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
            await cb.answer(await _(cb.from_user.id, 'no_rights'), show_alert=True)
            return
        await cb.message.delete()
        await cb.answer("Очистка отменена")

    # ========= Каталог =========
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
        await load_channels(cat_id)
        if not channels:
            await cb.message.edit_text(
                await _(cb.from_user.id, 'category_empty'),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text=await _(cb.from_user.id, 'back_to_categories'), callback_data="back_to_categories")]]
                )
            )
            await cb.answer()
            return
        kb, page, total = get_catalog_keyboard(cat_id, 0)
        await cb.message.edit_text(await _(cb.from_user.id, 'catalog_page', page=1, total=total), reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("sort_"))
    async def sort_catalog(cb: CallbackQuery):
        parts = cb.data.split("_")
        cat_id = int(parts[1])
        field = parts[2]
        order = parts[3]
        page = int(parts[4])
        sort_key = f"{field}_{order}"
        await load_channels(cat_id)
        kb, cur, total = get_catalog_keyboard(cat_id, page, sort_by=sort_key)
        await cb.message.edit_text(await _(cb.from_user.id, 'catalog_page', page=cur+1, total=total), reply_markup=kb)
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
        await load_channels(cat_id)
        kb, cur, total = get_catalog_keyboard(cat_id, page, sort_by=sort_by)
        if kb:
            await cb.message.edit_text(await _(cb.from_user.id, 'catalog_page', page=cur+1, total=total), reply_markup=kb)
        else:
            await cb.message.edit_text(await _(cb.from_user.id, 'category_empty'), reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=await _(cb.from_user.id, 'back_to_categories'), callback_data="back_to_categories")]]))
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
        await cb.message.answer(await _(cb.from_user.id, 'main_menu'), reply_markup=get_main_keyboard(cb.from_user.id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("channel_view_"))
    async def view_channel(cb: CallbackQuery):
        cid = cb.data.replace("channel_view_", "")
        info = channels.get(cid)
        if not info:
            await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True)
            return
        cat_name = ""
        if info.get('category_id'):
            cat = await get_category_by_id(info['category_id'])
            if cat:
                cat_name = cat['display_name']
        txt = await _(cb.from_user.id, 'channel_info',
                      name=info['name'],
                      subscribers=info['subscribers'],
                      price=info['price'],
                      url=info['url'],
                      description=info.get('description', 'Нет описания'))
        if cat_name:
            txt += f"\n🏷 {cat_name}"
        if info.get('views_avg'):
            txt += await _(cb.from_user.id, 'channel_views_avg', views_avg=info['views_avg'])
        if info.get('er'):
            txt += await _(cb.from_user.id, 'channel_er', er=info['er'])
        await cb.message.edit_text(txt, reply_markup=get_channel_view_keyboard(cid))
        await cb.answer()

    @dp.callback_query(F.data.startswith("cart_add_"))
    async def add_to_cart(cb: CallbackQuery):
        cid = cb.data.replace("cart_add_", "")
        info = channels.get(cid)
        if not info:
            await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True)
            return
        cart = get_cart(cb.from_user.id)
        cart.append({"id": cid, "name": info['name'], "price": info['price']})
        save_cart(cb.from_user.id, cart)
        await cb.answer(await _(cb.from_user.id, 'add_to_cart', name=info['name']), False)

    # ========= Корзина, оформление, профиль =========
    @dp.message(F.text == "🛒 Корзина")
    async def cart(m: Message):
        c = get_cart(m.from_user.id)
        if not c:
            await m.answer(await _(m.from_user.id, 'cart_empty'))
            return
        total = sum(i['price'] for i in c)
        items_str = "\n".join(f"{idx+1}. {i['name']} — {i['price']}$" for idx,i in enumerate(c))
        txt = await _(m.from_user.id, 'cart_total', items=items_str, total=total)
        await m.answer(txt, reply_markup=get_cart_keyboard(m.from_user.id))

    @dp.callback_query(F.data == "clear_cart")
    async def clear_cart(cb: CallbackQuery):
        user_carts[cb.from_user.id] = []
        await cb.answer(await _(cb.from_user.id, 'cart_clear'), False)
        await cb.message.delete()
        await cb.message.answer(await _(cb.from_user.id, 'cart_cleared'), reply_markup=get_main_keyboard(cb.from_user.id))

    @dp.callback_query(F.data.startswith("remove_"))
    async def remove_from_cart(cb: CallbackQuery):
        idx = int(cb.data.split("_")[1])
        cart = get_cart(cb.from_user.id)
        if 0 <= idx < len(cart):
            removed = cart.pop(idx)
            save_cart(cb.from_user.id, cart)
            await cb.answer(await _(cb.from_user.id, 'remove_item', name=removed['name']), False)
            if not cart:
                await cb.message.delete()
                await cb.message.answer(await _(cb.from_user.id, 'cart_cleared'), reply_markup=get_main_keyboard(cb.from_user.id))
            else:
                total = sum(i['price'] for i in cart)
                items_str = "\n".join(f"{i+1}. {item['name']} — {item['price']}$" for i,item in enumerate(cart))
                txt = await _(cb.from_user.id, 'cart_total', items=items_str, total=total)
                await cb.message.edit_text(txt, reply_markup=get_cart_keyboard(cb.from_user.id))
        else:
            await cb.answer("Ошибка", True)

    @dp.callback_query(F.data == "checkout")
    async def checkout_cb(cb: CallbackQuery, state: FSMContext):
        cart = get_cart(cb.from_user.id)
        if not cart:
            await cb.message.edit_text(await _(cb.from_user.id, 'cart_empty'), reply_markup=get_main_keyboard(cb.from_user.id))
            await cb.answer()
            return
        total = sum(i['price'] for i in cart)
        await state.update_data(cart=cart, total=total)
        await cb.message.edit_text(await _(cb.from_user.id, 'enter_budget', total=total))
        await state.set_state(OrderForm.waiting_for_budget)
        await cb.answer()

    @dp.message(OrderForm.waiting_for_budget)
    async def budg(m: Message, state: FSMContext):
        if not m.text.isdigit():
            await m.answer(await _(m.from_user.id, 'enter_number'))
            return
        budget = int(m.text)
        d = await state.get_data()
        total = d.get("total",0)
        if budget < total:
            await m.answer(await _(m.from_user.id, 'budget_low', budget=budget, total=total))
            return
        await state.update_data(budget=budget)
        await m.answer(await _(m.from_user.id, 'enter_contact'))
        await state.set_state(OrderForm.waiting_for_contact)

    @dp.message(OrderForm.waiting_for_contact)
    async def cont(m: Message, state: FSMContext):
        d = await state.get_data()
        cart = d.get("cart",[])
        total = d.get("total",0)
        budget = d.get("budget",0)
        contact = m.text.strip()
        username = m.from_user.username or "не указан"

        # Проверка дневного лимита
        can_order = await check_daily_order_limit(m.from_user.id)
        if not can_order:
            user_info = await get_or_create_user(m.from_user.id)
            await m.answer(await _(m.from_user.id, 'daily_limit_reached', limit=user_info.get('daily_limit', DAILY_ORDER_LIMIT)))
            await state.clear()
            return

        # Проверка баланса
        balance = await get_user_balance(m.from_user.id)
        if balance < total:
            await m.answer(await _(m.from_user.id, 'insufficient_funds', balance=balance, total=total))
            await state.clear()
            return

        order_id = await save_order(m.from_user.id, username, cart, total, budget, contact, status='оплачена')
        success = await debit_balance(m.from_user.id, total, order_id, description=f"Оплата заказа #{order_id}")
        if not success:
            await update_order_status(order_id, 'отменена')
            await m.answer(await _(m.from_user.id, 'debit_error'))
            await state.clear()
            return

        items = "\n".join(f"• {i['name']} — {i['price']}$" for i in cart)
        report = await _(m.from_user.id, 'order_report',
                         order_id=order_id,
                         username=username,
                         items=items,
                         total=total,
                         budget=budget,
                         contact=contact)
        for aid in ADMIN_IDS:
            try:
                await m.bot.send_message(aid, report)
            except: pass
        user_carts[m.from_user.id] = []
        await m.answer(await _(m.from_user.id, 'order_success', order_id=order_id, total=total),
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
        txt = await _(m.from_user.id, 'profile_text',
                      user_id=m.from_user.id,
                      username=m.from_user.username or 'не указан',
                      total_orders=total_orders,
                      total_spent=total_spent,
                      balance=user['balance'],
                      left_orders=left_orders,
                      daily_limit=daily_limit)
        await m.answer(txt, reply_markup=get_profile_keyboard())

    @dp.callback_query(F.data == "transaction_history")
    async def transaction_history(cb: CallbackQuery):
        txs = await get_user_transactions(cb.from_user.id, limit=10)
        if not txs:
            await cb.answer(await _(cb.from_user.id, 'tx_empty'), True)
            return
        txt = await _(cb.from_user.id, 'transaction_history')
        type_emoji = {
            "пополнение": await _(cb.from_user.id, 'tx_population'),
            "списание": await _(cb.from_user.id, 'tx_writeoff'),
            "возврат": await _(cb.from_user.id, 'tx_refund')
        }
        for tx in txs:
            emoji = type_emoji.get(tx['type'], '⚪')
            txt += f"{emoji} {tx['description']}\n   {tx['amount']}$\n   {tx['created_at'].split('.')[0]}\n\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=await _(cb.from_user.id, 'back_to_main'), callback_data="back_to_main_menu")]])
        await cb.message.edit_text(txt, reply_markup=kb)
        await cb.answer()

    # ========= ПОПОЛНЕНИЕ БАЛАНСА =========
    @dp.callback_query(F.data == "deposit")
    async def deposit_start(cb: CallbackQuery, state: FSMContext):
        await cb.message.edit_text(
            await _(cb.from_user.id, 'deposit_prompt', min_deposit=MIN_DEPOSIT),
            reply_markup=cancel_keyboard()
        )
        await state.set_state(OrderForm.waiting_for_deposit_amount)
        await cb.answer()

    @dp.callback_query(F.data == "cancel_add_channel", OrderForm.waiting_for_deposit_amount)
    async def cancel_deposit(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.message.edit_text(await _(cb.from_user.id, 'profile'), reply_markup=get_profile_keyboard())
        await cb.answer()

    @dp.message(OrderForm.waiting_for_deposit_amount)
    async def process_deposit_amount(m: Message, state: FSMContext):
        text = m.text.strip()
        try:
            amount = float(text)
        except ValueError:
            await m.answer(await _(m.from_user.id, 'enter_number'))
            return

        if amount < MIN_DEPOSIT:
            await m.answer(await _(m.from_user.id, 'min_deposit_error', min_deposit=MIN_DEPOSIT))
            return

        if not CRYPTO_BOT_TOKEN:
            await m.answer(await _(m.from_user.id, 'payment_unavailable'))
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
        try:
            r = requests.post(url, json=payload, headers=headers)
            data = r.json()
            if data.get("ok"):
                invoice_url = data["result"]["pay_url"]
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Перейти к оплате", url=invoice_url)],
                    [InlineKeyboardButton(text=await _(m.from_user.id, 'back_to_main'), callback_data="deposit")]
                ])
                await m.answer(f"Счёт на {amount}$ создан. Нажмите кнопку для оплаты:", reply_markup=kb)
            else:
                await m.answer(await _(m.from_user.id, 'invoice_error'), reply_markup=get_profile_keyboard())
        except Exception as e:
            print(e)
            await m.answer(await _(m.from_user.id, 'connection_error'), reply_markup=get_profile_keyboard())
        finally:
            await state.clear()

    # ========= Мои заказы =========
    @dp.callback_query(F.data == "my_orders")
    async def my_ords(cb: CallbackQuery):
        ords = await get_orders_by_user(cb.from_user.id, 10, only_completed=False)
        if not ords:
            await cb.message.delete()
            await cb.message.answer(await _(cb.from_user.id, 'no_orders'), reply_markup=get_main_keyboard(cb.from_user.id))
            await cb.answer()
            return
        txt = await _(cb.from_user.id, 'my_orders')
        btns = []
        for o in ords:
            txt += await _(cb.from_user.id, 'order_status',
                           id=o['id'],
                           total=o['total'],
                           count=len(o['cart']),
                           status_text=o['status'],
                           created=o['created_at'].split('.')[0])
            row = []
            row.append(InlineKeyboardButton(text="📄 Подробнее", callback_data=f"order_details_{o['id']}"))
            if o['status'] in ('в обработке', 'оплачена'):
                row.append(InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_order_{o['id']}"))
            btns.append(row)
        btns.append([InlineKeyboardButton(text=await _(cb.from_user.id, 'back_to_main'), callback_data="back_to_main_menu")])
        await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
        await cb.answer()

    @dp.callback_query(F.data.startswith("order_details_"))
    async def order_details(cb: CallbackQuery):
        oid = int(cb.data.split("_")[2])
        ordd = await get_order_by_id(oid)
        if not ordd or ordd['user_id'] != cb.from_user.id:
            await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True)
            return
        items = "\n".join(f"• {it['name']} — {it['price']}$" for it in ordd['cart'])
        txt = f"📄 Заявка #{oid}\n📌 Статус: {ordd['status']}\n💰 Сумма: {ordd['total']}$\n\n📦 Состав:\n{items}"
        await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=await _(cb.from_user.id, 'back_to_main'), callback_data="my_orders")]]
        ))
        await cb.answer()

    @dp.callback_query(F.data.startswith("cancel_order_"))
    async def cancel_order(cb: CallbackQuery):
        order_id = int(cb.data.split("_")[2])
        ordd = await get_order_by_id(order_id)
        if not ordd or ordd['user_id'] != cb.from_user.id:
            await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True)
            return
        if ordd['status'] not in ('в обработке', 'оплачена'):
            await cb.answer(await _(cb.from_user.id, 'cannot_cancel'), True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"confirm_cancel_{order_id}")],
            [InlineKeyboardButton(text=await _(cb.from_user.id, 'back_to_main'), callback_data="my_orders")]
        ])
        await cb.message.edit_text(
            await _(cb.from_user.id, 'confirm_cancel', order_id=order_id, total=ordd['total']),
            reply_markup=kb
        )
        await cb.answer()

    @dp.callback_query(F.data.startswith("confirm_cancel_"))
    async def confirm_cancel(cb: CallbackQuery):
        order_id = int(cb.data.split("_")[2])
        ordd = await get_order_by_id(order_id)
        if not ordd or ordd['user_id'] != cb.from_user.id:
            await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True)
            return
        if ordd['status'] not in ('в обработке', 'оплачена'):
            await cb.answer(await _(cb.from_user.id, 'cannot_cancel'), True)
            return

        await update_order_status(order_id, 'отменена')
        await return_balance(ordd['user_id'], ordd['total'], order_id, f"Возврат за отмену заказа #{order_id}")

        await cb.answer(await _(cb.from_user.id, 'order_cancelled'), False)
        for aid in ADMIN_IDS:
            try:
                await cb.bot.send_message(aid, f"❌ Заявка #{order_id} отменена пользователем @{ordd['username']} (сумма {ordd['total']}$). Деньги возвращены.")
            except: pass
        await my_ords(cb)

    # ========= Админ-панель (каналы, заявки) =========
    @dp.callback_query(F.data == "cancel_add_channel")
    async def cancel_add_channel(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), show_alert=True); return
        await state.clear()
        await cb.message.edit_text(await _(cb.from_user.id, 'admin'), reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_back")
    async def adm_back(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        await cb.message.edit_text(await _(cb.from_user.id, 'admin'), reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_stats")
    async def admin_stats_cb(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer(await _(cb.from_user.id, 'no_rights'), show_alert=True)
            return
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        tot_ord, tot_sum = await conn.fetchrow("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders")
        stat = await conn.fetch("SELECT status, COUNT(*) FROM orders GROUP BY status")
        chan_cnt = await conn.fetchval("SELECT COUNT(*) FROM channels")
        week = await conn.fetch("SELECT DATE(created_at), COUNT(*), SUM(total) FROM orders WHERE created_at >= CURRENT_DATE - INTERVAL '7 days' GROUP BY DATE(created_at) ORDER BY DATE(created_at) ASC")
        await conn.close()
        status_lines = "\n".join(f"{'🟡' if s=='в обработке' else '🟢' if s=='оплачена' else '✅' if s=='выполнена' else '❌'} {s}: {c}" for s, c in stat)
        week_lines = "\n".join(f"{d}: {cnt} заявок, {s or 0}$" for d, cnt, s in week)
        week_info = await _(cb.from_user.id, 'admin_week_info', week_rows=week_lines) if week else await _(cb.from_user.id, 'admin_no_week_info')
        txt = await _(cb.from_user.id, 'admin_stats_text',
                      total_orders=tot_ord,
                      total_sum=tot_sum or 0,
                      channel_count=chan_cnt,
                      statuses=status_lines,
                      week_info=week_info)
        await cb.message.edit_text(txt, reply_markup=get_stats_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_balance")
    async def admin_balance_start(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer(await _(cb.from_user.id, 'no_rights'), show_alert=True)
            return
        await cb.message.edit_text(await _(cb.from_user.id, 'admin_balance_start'), reply_markup=cancel_keyboard())
        await state.set_state(AdminBalanceStates.waiting_for_user_id)
        await cb.answer()

    @dp.callback_query(F.data == "cancel_add_channel", AdminBalanceStates.waiting_for_user_id)
    async def cancel_balance_user(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.message.edit_text(await _(cb.from_user.id, 'admin'), reply_markup=get_admin_keyboard())
        await cb.answer()

    @dp.message(AdminBalanceStates.waiting_for_user_id)
    async def process_balance_user_id(m: Message, state: FSMContext):
        if not m.text.isdigit():
            await m.answer(await _(m.from_user.id, 'admin_invalid_id'))
            return
        target_id = int(m.text)
        await state.update_data(target_id=target_id)
        await m.answer(await _(m.from_user.id, 'admin_balance_amount'), reply_markup=cancel_keyboard())
        await state.set_state(AdminBalanceStates.waiting_for_amount)

    @dp.message(AdminBalanceStates.waiting_for_amount)
    async def process_balance_amount(m: Message, state: FSMContext):
        text = m.text.strip()
        try:
            amount = int(text)
        except ValueError:
            await m.answer(await _(m.from_user.id, 'admin_invalid_amount'))
            return
        data = await state.get_data()
        target_id = data['target_id']
        await get_or_create_user(target_id)
        if amount >= 0:
            await update_user_balance(target_id, amount, f"Ручное пополнение админом {m.from_user.id}")
            msg = await _(m.from_user.id, 'admin_balance_success', target_id=target_id, amount=amount)
        else:
            success = await debit_balance(target_id, -amount, None, f"Ручное списание админом {m.from_user.id}")
            if success:
                msg = await _(m.from_user.id, 'admin_balance_debit', target_id=target_id, amount=-amount)
            else:
                bal = await get_user_balance(target_id)
                msg = await _(m.from_user.id, 'admin_balance_fail', balance=bal)
        await m.answer(msg, reply_markup=get_admin_keyboard())
        await state.clear()

    @dp.callback_query(F.data == "admin_refresh_metrics")
    async def admin_refresh_metrics(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer(await _(cb.from_user.id, 'no_rights'), show_alert=True)
            return
        await cb.answer("🔄 Обновление метрик...", False)
        report, _ = await refresh_all_channels_metrics(cb.bot)
        await cb.message.answer(report, reply_markup=get_admin_keyboard())

    @dp.callback_query(F.data == "admin_categories")
    async def admin_categories_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        await cb.message.edit_text("🏷 Управление категориями", reply_markup=await get_categories_admin_keyboard())
        await cb.answer()

    @dp.callback_query(F.data == "admin_add_category")
    async def admin_add_category_start(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        await cb.message.edit_text("Введите **короткое имя** категории (на английском, например 'mining'):", parse_mode="Markdown")
        await state.set_state(AddCategoryStates.waiting_for_name)
        await cb.answer()

    @dp.message(AddCategoryStates.waiting_for_name)
    async def add_cat_name(m: Message, state: FSMContext):
        name = m.text.strip()
        if not name:
            await m.answer(await _(m.from_user.id, 'enter_number'))
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
            await m.answer(await _(m.from_user.id, 'enter_number'))
            return
        await add_category(name, display)
        await m.answer(f"✅ Категория '{display}' добавлена", reply_markup=get_admin_keyboard())
        await state.clear()

    @dp.callback_query(F.data.startswith("admin_category_"))
    async def admin_category_detail(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        cat_id = int(cb.data.split("_")[2])
        cat = await get_category_by_id(cat_id)
        if not cat:
            await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True)
            return
        await cb.message.edit_text(f"Категория: {cat['display_name']} (id={cat_id}, имя={cat['name']})", reply_markup=get_category_actions_keyboard(cat_id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_del_category_"))
    async def admin_del_category(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        cat_id = int(cb.data.split("_")[3])
        await delete_category(cat_id)
        await cb.answer("Категория удалена", False)
        await admin_categories_menu(cb)

    @dp.callback_query(F.data == "admin_list")
    async def adm_list(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        await load_channels()
        if not channels:
            await cb.message.delete()
            await cb.message.answer(await _(cb.from_user.id, 'admin_no_channels'), reply_markup=get_main_keyboard(cb.from_user.id))
            await cb.answer()
            return
        await cb.message.edit_text(await _(cb.from_user.id, 'admin_list'), reply_markup=get_admin_list_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_view_"))
    async def adm_view_chan(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        await load_channels()
        cid = cb.data.replace("admin_view_", "")
        ch = channels.get(cid)
        if not ch: await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True); return
        cat_name = ""
        if ch.get('category_id'):
            cat = await get_category_by_id(ch['category_id'])
            if cat:
                cat_name = cat['display_name']
        txt = f"📌 {ch['name']}\n🔗 {ch['url']}\n💰 {ch['price']}$\n👥 {ch['subscribers']} подп.\n📝 {ch.get('description','Нет описания')}"
        if cat_name:
            txt += f"\n🏷 {cat_name}"
        if ch.get('er'):
            txt += f"\n📊 ER: {ch['er']}%"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_channel_{cid}")],[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_list")]])
        await cb.message.edit_text(txt, reply_markup=kb)
        await cb.answer()

    @dp.callback_query(F.data.startswith("edit_channel_"))
    async def edit_chan_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        cid = cb.data.replace("edit_channel_", "")
        await load_channels()
        if cid not in channels: await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True); return
        await cb.message.edit_text(await _(cb.from_user.id, 'edit_channel', name=channels[cid]['name']), reply_markup=get_edit_channel_keyboard(cid))
        await cb.answer()

    @dp.callback_query(F.data.startswith("edit_") & ~F.data.startswith("edit_channel_"))
    async def edit_field(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        parts = cb.data.split("_",2)
        if len(parts)<3: await cb.answer("Ошибка", True); return
        cid, field = parts[1], parts[2]
        await load_channels()
        if cid not in channels: await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True); return
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
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        parts = cb.data.split("_")
        cid = parts[3]
        cat_id = int(parts[4])
        await update_channel(cid, category_id=cat_id)
        await load_channels()
        await cb.answer("Категория обновлена", False)
        await adm_view_chan(cb)
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_name)
    async def e_name(m: Message, state: FSMContext):
        d = await state.get_data()
        await update_channel(d['ch_id'], name=m.text)
        await load_channels()
        await m.answer(f"✅ Название изменено на {m.text}")
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_price)
    async def e_price(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        d = await state.get_data()
        await update_channel(d['ch_id'], price=int(m.text))
        await load_channels()
        await m.answer(f"✅ Цена изменена на {m.text}$")
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_subscribers)
    async def e_subs(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        d = await state.get_data()
        await update_channel(d['ch_id'], subs=int(m.text))
        await load_channels()
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
        await load_channels()
        await m.answer(f"✅ Ссылка изменена на {url}")
        await state.clear()

    @dp.message(EditChannelStates.waiting_for_description)
    async def e_desc(m: Message, state: FSMContext):
        d = await state.get_data()
        await update_channel(d['ch_id'], desc=m.text)
        await load_channels()
        await m.answer("✅ Описание изменено")
        await state.clear()

    @dp.callback_query(F.data == "admin_remove")
    async def adm_rem_menu(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        await load_channels()
        if not channels:
            await cb.message.delete()
            await cb.message.answer(await _(cb.from_user.id, 'admin_no_channels'), reply_markup=get_main_keyboard(cb.from_user.id))
            await cb.answer()
            return
        await cb.message.edit_text(await _(cb.from_user.id, 'admin_remove'), reply_markup=get_admin_remove_keyboard())
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_del_"))
    async def adm_del(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        cid = cb.data.replace("admin_del_", "")
        await load_channels()
        if cid in channels:
            name = channels[cid]['name']
            await delete_channel(cid)
            await load_channels()
            await cb.answer(await _(cb.from_user.id, 'channel_deleted', name=name), False)
            if not channels:
                await cb.message.delete()
                await cb.message.answer(await _(cb.from_user.id, 'all_channels_deleted'), reply_markup=get_main_keyboard(cb.from_user.id))
            else:
                await cb.message.edit_text(await _(cb.from_user.id, 'admin_remove'), reply_markup=get_admin_remove_keyboard())
        else:
            await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True)

    # ========= ДОБАВЛЕНИЕ КАНАЛА =========
    @dp.callback_query(F.data == "admin_add")
    async def adm_add_start(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        await cb.message.edit_text("➕ Выберите категорию для нового канала:", reply_markup=await get_category_selection_keyboard("add_chan_cat"))
        await state.set_state(AddChannelStates.waiting_for_category)
        await cb.answer()

    @dp.callback_query(F.data.startswith("add_chan_cat_"), AddChannelStates.waiting_for_category)
    async def add_channel_category_chosen(cb: CallbackQuery, state: FSMContext):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
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
        if not m.text.isdigit(): await m.answer("Введите число"); return
        await state.update_data(price=int(m.text))
        await m.answer("Введите количество подписчиков (число):", reply_markup=cancel_keyboard())
        await state.set_state(AddChannelStates.waiting_for_subscribers)

    @dp.message(AddChannelStates.waiting_for_subscribers)
    async def a_subs(m: Message, state: FSMContext):
        if not m.text.isdigit(): await m.answer("Введите число"); return
        await state.update_data(subscribers=int(m.text))
        await m.answer("Введите ссылку (https://t.me/...):", reply_markup=cancel_keyboard())
        await state.set_state(AddChannelStates.waiting_for_url)

    @dp.message(AddChannelStates.waiting_for_url)
    async def a_url(m: Message, state: FSMContext):
        url = m.text.strip()
        if not url.startswith("https://t.me/"): await m.answer("Ссылка должна начинаться с https://t.me/"); return
        await state.update_data(url=url)
        await m.answer("Введите описание канала:", reply_markup=cancel_keyboard())
        await state.set_state(AddChannelStates.waiting_for_description)

    @dp.message(AddChannelStates.waiting_for_description)
    async def a_desc(m: Message, state: FSMContext):
        await state.update_data(description=m.text)
        data = await state.get_data()
        new_id = f"channel_{int(round(time.time()*1000))}"
        cat_id = data['category_id']
        await add_channel(new_id, data['name'], data['price'], data['subscribers'], data['url'], data['description'], cat_id)
        await load_channels()
        cat = await get_category_by_id(cat_id)
        cat_name = cat['display_name'] if cat else ""
        await m.answer(await _(m.from_user.id, 'channel_added', name=data['name'], category=cat_name), reply_markup=get_admin_keyboard())
        await state.clear()

    # ========= ЗАЯВКИ (админ) =========
    @dp.callback_query(F.data == "admin_orders")
    async def adm_orders(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        ords = await get_orders(20)
        if not ords: await cb.message.edit_text(await _(cb.from_user.id, 'admin_no_orders'), reply_markup=get_main_keyboard(cb.from_user.id)); await cb.answer(); return
        await cb.message.edit_text(await _(cb.from_user.id, 'admin_orders'), reply_markup=get_admin_orders_keyboard(ords))
        await cb.answer()

    @dp.callback_query(F.data.startswith("admin_order_"))
    async def adm_view_order(cb: CallbackQuery):
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        oid = int(cb.data.split("_")[2])
        ordd = await get_order_by_id(oid)
        if not ordd: await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True); return
        em = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}
        txt = f"📄 Заявка #{ordd['id']}\n👤 @{ordd['username']}\n💰 Сумма: {ordd['total']}$\n📌 Статус: {em.get(ordd['status'], '⚪')} {ordd['status']}\n\nВыберите новый статус:"
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
        if cb.from_user.id not in ADMIN_IDS: await cb.answer(await _(cb.from_user.id, 'no_rights'), True); return
        parts = cb.data.split("_")
        oid = int(parts[2])
        new_st = "_".join(parts[3:])
        order = await get_order_by_id(oid)
        if not order: await cb.answer(await _(cb.from_user.id, 'channel_not_found'), True); return

        old_status = order['status']
        if new_st == 'отменена' and old_status == 'оплачена':
            await return_balance(order['user_id'], order['total'], oid, f"Возврат за отмену заказа #{oid} админом")
            try:
                await cb.bot.send_message(order['user_id'], await _(cb.from_user.id, 'status_changed', order_id=oid, new_status='отменена'))
            except: pass
            for aid in ADMIN_IDS:
                if aid != cb.from_user.id:
                    try:
                        await cb.bot.send_message(aid, f"❌ Админ отменил заявку #{oid} (возврат {order['total']}$)")
                    except: pass

        await update_order_status(oid, new_st)
        await cb.answer(f"✅ Статус заявки #{oid} изменён на {new_st}", False)
        try:
            await cb.bot.send_message(order['user_id'], await _(cb.from_user.id, 'status_changed', order_id=oid, new_status=new_st))
        except: pass
        ords = await get_orders(20)
        await cb.message.edit_text(await _(cb.from_user.id, 'admin_orders'), reply_markup=get_admin_orders_keyboard(ords))

    # ========= Текстовые сообщения =========
    @dp.message(F.text == "ℹ️ О сервисе")
    async def about(m: Message):
        await m.answer(await _(m.from_user.id, 'about'))

    @dp.message(F.text == "❓ FAQ")
    async def faq(m: Message):
        await m.answer(await _(m.from_user.id, 'faq'))

    @dp.message(F.text == "📞 Контакты")
    async def contacts(m: Message):
        await m.answer(await _(m.from_user.id, 'contacts'))

# ------------------ Flask и CryptoBot Webhooks ------------------
flask_app = Flask(__name__)
app = flask_app

bot_instance = Bot(token=BOT_TOKEN)
dp_instance = Dispatcher(storage=MemoryStorage())

scheduler = AsyncIOScheduler()

async def startup():
    await init_db()
    await register_handlers(dp_instance)
    print("Бот готов")
    # Вместо вебхука запускаем polling
    await dp_instance.start_polling(bot_instance)

@app.route('/cryptobot', methods=['POST'])
def cryptobot_webhook():
    if not CRYPTO_BOT_TOKEN:
        return jsonify({'status': 'error'}), 403
    body = request.get_data()
    secret = hashlib.sha256(CRYPTO_BOT_TOKEN.encode()).digest()
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if request.headers.get('Crypto-Pay-Api-Signature') != signature:
        return jsonify({'status': 'error'}), 403
    data = request.json
    if data.get('update_type') == 'invoice_paid':
        payload = data['payload']
        invoice = payload['invoice']
        desc = invoice.get('description', '')
        try:
            user_id = int(desc.split("user_id:")[1]) if "user_id:" in desc else None
        except:
            user_id = None
        if user_id:
            amount = int(float(invoice['amount']))
            loop.run_until_complete(update_user_balance(user_id, amount, f"Пополнение USDT {amount}$"))
            try:
                loop.run_until_complete(bot_instance.send_message(user_id, f"✅ Ваш баланс пополнен на {amount}$. Спасибо!"))
            except: pass
            for aid in ADMIN_IDS:
                try:
                    loop.run_until_complete(bot_instance.send_message(aid, f"💰 Пользователь {user_id} пополнил баланс на {amount}$"))
                except: pass
    return jsonify({'status': 'ok'})

# --- Старт ---
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(startup())

application = app
