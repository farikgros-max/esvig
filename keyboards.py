from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import ADMIN_IDS


# Главное меню (обычные кнопки)
def get_main_keyboard(user_id: int = None):
    buttons = [
        [KeyboardButton(text="📢 Купить рекламу"), KeyboardButton(text="💰 Продать рекламу")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="🛒 Корзина")],
        [KeyboardButton(text="❓ FAQ"), KeyboardButton(text="📞 Контакты")]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([KeyboardButton(text="🔑 Админ‑панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# Админ‑панель
def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Каналы", callback_data="admin_channels_menu"),
         InlineKeyboardButton(text="📋 Заявки", callback_data="admin_orders_menu")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
         InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data="admin_balance")]
    ])

def get_admin_channels_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="admin_add")],
        [InlineKeyboardButton(text="⚡ Быстрое добавление", callback_data="quick_add")],
        [InlineKeyboardButton(text="📋 Список каналов", callback_data="admin_list")],
        [InlineKeyboardButton(text="🗑 Удалить канал", callback_data="admin_remove")],
        [InlineKeyboardButton(text="📥 Массовое добавление", callback_data="bulk_add")],
        [InlineKeyboardButton(text="🏷 Управление категориями", callback_data="admin_categories")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])

def get_admin_orders_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список заявок", callback_data="admin_orders")],
        [InlineKeyboardButton(text="📋 Заявки продавцов", callback_data="admin_seller_applications")],
        [InlineKeyboardButton(text="🧹 Очистить неуспешные", callback_data="confirm_clear_failed")],
        [InlineKeyboardButton(text="🧹 Полная очистка", callback_data="confirm_clear_all")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])

# Клавиатуры статистики
def get_stats_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Топ каналов", callback_data="top_channels"),
         InlineKeyboardButton(text="📥 Экспорт заказов", callback_data="export_orders")],
        [InlineKeyboardButton(text="👥 Топ покупателей", callback_data="top_buyers"),
         InlineKeyboardButton(text="📈 Доходы по дням", callback_data="daily_revenue")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])

# Каталог
def get_catalog_keyboard(channels_dict, category_id, page=0, sort_by="default"):
    items = list(channels_dict.items())
    if sort_by == "price_asc":
        items.sort(key=lambda x: x[1].get('price', 0))
    elif sort_by == "price_desc":
        items.sort(key=lambda x: x[1].get('price', 0), reverse=True)
    elif sort_by == "subs_asc":
        items.sort(key=lambda x: x[1].get('subscribers', 0))
    elif sort_by == "subs_desc":
        items.sort(key=lambda x: x[1].get('subscribers', 0), reverse=True)

    per_page = 5
    total = max(1, (len(items) + per_page - 1) // per_page)
    start = page * per_page
    end = start + per_page
    page_items = items[start:end]

    kb_rows = []
    for cid, info in page_items:
        name = info.get('name', 'Без названия')
        price = info.get('price', 0)
        kb_rows.append([InlineKeyboardButton(text=f"{name} ({price}$)", callback_data=f"channel_view_{cid}")])

    # Сортировка
    price_arrow = "↑" if sort_by == "price_asc" else "↓"
    subs_arrow = "↑" if sort_by == "subs_asc" else "↓"
    kb_rows.append([
        InlineKeyboardButton(text=f"По цене {price_arrow}", callback_data=f"sort_{category_id}_price_{'asc' if sort_by != 'price_asc' else 'desc'}_{page}"),
        InlineKeyboardButton(text=f"По подп. {subs_arrow}", callback_data=f"sort_{category_id}_subs_{'asc' if sort_by != 'subs_asc' else 'desc'}_{page}")
    ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"view_catalog_page_{category_id}_{page-1}_{sort_by}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="none"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"view_catalog_page_{category_id}_{page+1}_{sort_by}"))
    kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows), page, total

def get_channel_view_keyboard(cid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ В корзину", callback_data=f"cart_add_{cid}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_catalog")]
    ])

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")]
    ])

async def get_categories_keyboard(get_all_cats):
    cats = await get_all_cats()
    kb_rows = []
    for i in range(0, len(cats), 2):
        row = [InlineKeyboardButton(text=cats[i]['display_name'], callback_data=f"category_select_{cats[i]['id']}")]
        if i+1 < len(cats):
            row.append(InlineKeyboardButton(text=cats[i+1]['display_name'], callback_data=f"category_select_{cats[i+1]['id']}"))
        kb_rows.append(row)
    kb_rows.append([InlineKeyboardButton(text="↩️ Главное меню", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

def get_free_slots_keyboard(channel_id, free_slots, page=0):
    per_page = 5
    total = max(1, (len(free_slots) + per_page - 1) // per_page)
    start = page * per_page
    end = start + per_page
    page_slots = free_slots[start:end]
    kb_rows = []
    for date in page_slots:
        kb_rows.append([InlineKeyboardButton(text=f"📅 {date}", callback_data=f"choose_slot_{channel_id}_{date}")])
    # Навигация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"slots_page_{channel_id}_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="none"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️ Вперёд", callback_data=f"slots_page_{channel_id}_{page+1}"))
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="🔙 К каналу", callback_data=f"channel_view_{channel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

# Биржа (продавец)
def get_seller_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои каналы", callback_data="seller_my_channels")],
        [InlineKeyboardButton(text="➕ Подать заявку", callback_data="seller_apply")],
        [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
    ])

def get_seller_channel_keyboard(channel_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"seller_edit_{channel_id}")],
        [InlineKeyboardButton(text="📅 Календарь", callback_data=f"seller_calendar_{channel_id}")],
        [InlineKeyboardButton(text="📊 Аналитика", callback_data=f"seller_analytics_{channel_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="seller_my_channels")]
    ])


def get_seller_analytics_keyboard(channel_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Доходы за 7 дней", callback_data=f"seller_analytics_7_{channel_id}")],
        [InlineKeyboardButton(text="📅 Доходы за 30 дней", callback_data=f"seller_analytics_30_{channel_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"seller_channel_{channel_id}")]
    ])

async def get_seller_categories_keyboard(get_all_cats):
    return await get_category_selection_keyboard(get_all_cats, "seller_cat")

async def get_category_selection_keyboard(get_all_cats, callback_prefix):
    cats = await get_all_cats()
    kb_rows = []
    for cat in cats:
        kb_rows.append([InlineKeyboardButton(text=cat['display_name'], callback_data=f"{callback_prefix}_{cat['id']}")])
    kb_rows.append([InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"{callback_prefix}_skip")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

# Профиль
def get_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Пополнить баланс", callback_data="deposit"),
         InlineKeyboardButton(text="📊 Мои заявки", callback_data="my_orders")],
        [InlineKeyboardButton(text="📜 История транзакций", callback_data="transaction_history"),
         InlineKeyboardButton(text="👥 Реферальная программа", callback_data="referral_program")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main_menu")]
    ])

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_channel")]
    ])

# Дополнительные админские клавиатуры (заглушки, если потребуются)
def get_admin_list_keyboard(channels_dict, page=0, category_id=None):
    items = list(channels_dict.items())
    per_page = 5
    total = max(1, (len(items) + per_page - 1) // per_page)
    start = page * per_page
    end = start + per_page
    page_items = items[start:end]
    kb_rows = []
    for cid, info in page_items:
        name = info.get('name', 'Без названия')
        kb_rows.append([InlineKeyboardButton(text=name, callback_data=f"admin_view_{cid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_list_page_{page-1}_{category_id}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="none"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_list_page_{page+1}_{category_id}"))
    kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_list_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows), page, total

def get_admin_remove_keyboard(channels_dict):
    kb_rows = []
    for cid, info in channels_dict.items():
        name = info.get('name', 'Без названия')
        kb_rows.append([InlineKeyboardButton(text=name, callback_data=f"admin_del_{cid}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_channels_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

def get_admin_orders_keyboard(orders):
    kb_rows = []
    for o in orders:
        kb_rows.append([InlineKeyboardButton(text=f"#{o['id']} {o['username']} ({o['total']}$)", callback_data=f"admin_order_{o['id']}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_orders_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

def get_edit_channel_keyboard(cid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Название", callback_data=f"edit_{cid}_name")],
        [InlineKeyboardButton(text="Цена", callback_data=f"edit_{cid}_price")],
        [InlineKeyboardButton(text="Подписчики", callback_data=f"edit_{cid}_subscribers")],
        [InlineKeyboardButton(text="Ссылка", callback_data=f"edit_{cid}_url")],
        [InlineKeyboardButton(text="Описание", callback_data=f"edit_{cid}_description")],
        [InlineKeyboardButton(text="Категория", callback_data=f"edit_{cid}_category")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_view_{cid}")]
    ])

async def get_categories_admin_keyboard(get_all_cats):
    cats = await get_all_cats()
    kb_rows = []
    for cat in cats:
        kb_rows.append([InlineKeyboardButton(text=cat['display_name'], callback_data=f"admin_category_{cat['id']}")])
    kb_rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_category")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_channels_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

def get_category_actions_keyboard(cat_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить категорию", callback_data=f"confirm_delete_category_{cat_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_categories")]
    ])

def get_confirm_delete_category_keyboard(cat_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"exec_delete_category_{cat_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_categories")]
    ])

async def get_admin_categories_keyboard(get_all_cats):
    cats = await get_all_cats()
    kb_rows = [[InlineKeyboardButton(text="Все каналы", callback_data="admin_cat_all")],
               [InlineKeyboardButton(text="Без категории", callback_data="admin_cat_none")]]
    for cat in cats:
        kb_rows.append([InlineKeyboardButton(text=cat['display_name'], callback_data=f"admin_cat_{cat['id']}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_channels_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

# Корзина
def get_cart_keyboard(cart):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    # В оригинале клавиатура для корзины могла содержать кнопки удаления и т.д.
    # Добавим минимально необходимую кнопку "Оформить заказ" и "Очистить корзину"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")],
        [InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="clear_cart")],
        [InlineKeyboardButton(text="↩️ Главное меню", callback_data="main_menu")]
    ])

def back_to_menu_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main_menu")]
    ])

def main_menu_keyboard():
    return get_main_keyboard(None)


def get_seller_slots_list_keyboard(channel_id: int, slots: list, page: int = 0):
    """Список слотов с пагинацией."""
    per_page = 5
    total = max(1, (len(slots) + per_page - 1) // per_page)
    start = page * per_page
    end = start + per_page
    page_slots = slots[start:end]

    kb_rows = []
    for slot in page_slots:
        date = slot.get("date", "")
        status = slot.get("status", "")
        if status == "free":
            btn_text = f"📅 {date} — свободен"
        elif status == "booked":
            btn_text = f"🔴 {date} — занят"
        else:
            btn_text = f"⚪ {date} — {status}"
        # В callback добавляем page, чтобы при возврате знать, откуда пришли
        kb_rows.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"seller_slot_info_{channel_id}_{date}_{page}"
        )])

    # Навигация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"seller_my_slots_{channel_id}_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="none"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"seller_my_slots_{channel_id}_{page+1}"))
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"seller_calendar_{channel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)
