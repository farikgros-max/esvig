from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from config import ADMIN_IDS, ITEMS_PER_PAGE

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_channel")]])

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
        [InlineKeyboardButton(text="⚡ Быстрое добавление", callback_data="quick_add"),
         InlineKeyboardButton(text="📥 Массовое добавление", callback_data="bulk_add")],
        [InlineKeyboardButton(text="🏷 Управление категориями", callback_data="admin_categories"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data="admin_balance")],
    ])

# Все остальные функции оставьте без изменений
async def get_categories_keyboard(cats):
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
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"view_catalog_page_{category_id}_{page-1}_{sort_by}"))
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

def get_cart_keyboard(cart):
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
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="🔍 Проверить платёж", callback_data="check_payment")]
    ])

def get_stats_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить неуспешные", callback_data="confirm_clear_failed")],
        [InlineKeyboardButton(text="🗑 Полная очистка", callback_data="confirm_clear_all")]
    ])

async def get_categories_admin_keyboard(get_all_categories):
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

async def get_category_selection_keyboard(get_all_categories, callback_prefix):
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
