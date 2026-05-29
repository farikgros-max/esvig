from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta

from database import get_active_channels, get_all_categories, get_free_slots
from keyboards import (get_categories_keyboard, get_catalog_keyboard,
                       get_back_keyboard, get_channel_view_keyboard, get_main_keyboard)

router = Router()

class SlotSelect(StatesGroup):
    choosing = State()

@router.message(F.text == "📢 Купить рекламу")
async def buy_ads_start(m: Message):
    await catalog_start(m)

@router.message(F.text == "📋 Каталог каналов")
async def catalog_start(m: Message):
    cats = await get_all_categories()
    if not cats:
        await m.answer("Категории не найдены")
        return
    await m.answer("Выберите категорию:", reply_markup=await get_categories_keyboard(get_all_categories))

@router.callback_query(F.data.startswith("category_select_"))
async def select_category(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[2])
    ch = await get_active_channels(cat_id)
    if not ch:
        await cb.message.edit_text("В этой категории пока нет каналов (или все скрыты).",
                                   reply_markup=InlineKeyboardMarkup(
                                       inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")]]))
        await cb.answer()
        return
    kb, page, total = get_catalog_keyboard(ch, cat_id, 0)
    await cb.message.edit_text(f"📢 Каналы в категории (страница 1/{total})", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("sort_"))
async def sort_catalog(cb: CallbackQuery):
    parts = cb.data.split("_")
    cat_id = int(parts[1])
    field = parts[2]
    order = parts[3]
    page = int(parts[4])
    sort_key = f"{field}_{order}"
    ch = await get_active_channels(cat_id)
    kb, cur, total = get_catalog_keyboard(ch, cat_id, page, sort_by=sort_key)
    await cb.message.edit_text(f"📢 Каналы в категории (страница {cur+1}/{total})", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("view_catalog_page_"))
async def view_catalog_page(cb: CallbackQuery):
    parts = cb.data.split("_")
    cat_id = int(parts[3])
    page = int(parts[4])
    sort_by = parts[5] if len(parts) > 5 else "default"
    ch = await get_active_channels(cat_id)
    kb, cur, total = get_catalog_keyboard(ch, cat_id, page, sort_by=sort_by)
    if kb:
        await cb.message.edit_text(f"📢 Каналы в категории (страница {cur+1}/{total})", reply_markup=kb)
    else:
        await cb.message.edit_text("Каталог пуст", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_categories")]]))
    await cb.answer()

@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(cb: CallbackQuery):
    cats = await get_all_categories()
    if not cats:
        await cb.message.edit_text("Категории не найдены", reply_markup=get_back_keyboard())
        await cb.answer()
        return
    await cb.message.edit_text("Выберите категорию:", reply_markup=await get_categories_keyboard(get_all_categories))
    await cb.answer()

@router.callback_query(F.data == "back_to_catalog")
async def back_to_catalog(cb: CallbackQuery):
    cats = await get_all_categories()
    if not cats:
        await cb.message.edit_text("Категории не найдены", reply_markup=get_back_keyboard())
        await cb.answer()
        return
    await cb.message.edit_text("Выберите категорию:", reply_markup=await get_categories_keyboard(get_all_categories))
    await cb.answer()

@router.callback_query(F.data == "back_to_main_menu")
async def back_main_menu(cb: CallbackQuery):
    from handlers.start import send_welcome
    await send_welcome(cb.bot, cb.from_user.id, cb.from_user.id, cb.from_user.first_name, cb.from_user.username)
    await cb.answer()

# Карточка канала
@router.callback_query(F.data.startswith("channel_view_"))
async def view_channel(cb: CallbackQuery, state: FSMContext):
    cid = cb.data.replace("channel_view_", "")
    ch = await get_active_channels()
    info = ch.get(cid)
    if not info:
        await cb.answer("Канал не найден или скрыт", True)
        return
    txt = f"📌 {info['name']}\n👥 Подписчиков: {info['subscribers']}\n💰 Цена: {info['price']}$\n🔗 Ссылка: {info['url']}\n📝 Описание:\n{info.get('description','Нет описания')}"

    free_slots = await get_free_slots(cid)
    kb_rows = []
    if free_slots:
        kb_rows.append([InlineKeyboardButton(text="📅 Даты", callback_data=f"show_slots_{cid}")])
    kb_rows.append([InlineKeyboardButton(text="➕ В корзину", callback_data=f"cart_add_{cid}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_catalog")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    await state.clear()
    await cb.message.edit_text(txt, reply_markup=kb)
    await cb.answer()

# Экран выбора дат с галочками
@router.callback_query(F.data.startswith("show_slots_"))
async def show_slots(cb: CallbackQuery, state: FSMContext):
    cid = cb.data.replace("show_slots_", "")
    free = [d for d in await get_free_slots(cid) if d >= (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')]
    if not free:
        await cb.answer("Нет свободных дат", show_alert=True)
        return

    from handlers.cart import get_cart
    cart = await get_cart(cb.from_user.id)
    already_added = [item['date'] for item in cart if item.get("id") == cid and 'date' in item]

    await state.set_state(SlotSelect.choosing)
    await state.update_data(channel_id=cid, selected_dates=already_added.copy())

    kb_rows = []
    for date in free:
        if date in already_added:
            btn_text = f"✅ {date}"
        else:
            btn_text = f"☑️ {date}"
        kb_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_slot_{cid}_{date}")])
    kb_rows.append([InlineKeyboardButton(text="✅ Добавить выбранное", callback_data=f"add_selected_{cid}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 К каналу", callback_data=f"channel_view_{cid}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    await cb.message.edit_text("📅 Доступные даты (отметьте нужные):", reply_markup=kb)
    await cb.answer()

# Переключение галочки (универсальный парсинг)
@router.callback_query(F.data.startswith("toggle_slot_"))
async def toggle_slot(cb: CallbackQuery, state: FSMContext):
    rest = cb.data[len("toggle_slot_"):]
    if len(rest) < 11:
        await cb.answer("Некорректные данные", show_alert=True)
        return
    date = rest[-10:]          # YYYY-MM-DD
    cid = rest[:-11]           # всё, что перед датой и подчёркиванием

    data = await state.get_data()
    selected = data.get("selected_dates", [])
    if date in selected:
        selected.remove(date)
    else:
        selected.append(date)
    await state.update_data(selected_dates=selected)

    free = [d for d in await get_free_slots(cid) if d >= (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')]
    kb_rows = []
    for d in free:
        if d in selected:
            btn_text = f"✅ {d}"
        else:
            btn_text = f"☑️ {d}"
        kb_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_slot_{cid}_{d}")])
    kb_rows.append([InlineKeyboardButton(text="✅ Добавить выбранное", callback_data=f"add_selected_{cid}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 К каналу", callback_data=f"channel_view_{cid}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer()

# Добавление выбранных дат
@router.callback_query(F.data.startswith("add_selected_"))
async def add_selected(cb: CallbackQuery, state: FSMContext):
    cid = cb.data[len("add_selected_"):]
    data = await state.get_data()
    selected_dates = data.get("selected_dates", [])
    if not selected_dates:
        await cb.answer("Вы не выбрали ни одной даты", show_alert=True)
        return

    ch = await get_active_channels()
    info = ch.get(cid)
    if not info:
        await cb.answer("Канал не найден", show_alert=True)
        return

    from handlers.cart import get_cart, save_cart
    cart = await get_cart(cb.from_user.id)

    # Удаляем старые позиции этого канала с датами
    cart = [item for item in cart if not (item.get("id") == cid and 'date' in item)]

    for date in selected_dates:
        cart.append({"id": cid, "name": info['name'], "price": info['price'], "url": info['url'], "date": date})

    await save_cart(cb.from_user.id, cart)
    await state.clear()
    await cb.message.edit_text(
        f"✅ Выбранные даты канала {info['name']} добавлены в корзину.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 К каталогу", callback_data="back_to_catalog")]]
        )
    )
    await cb.answer()

# Обычное добавление в корзину (без даты)
@router.callback_query(F.data.startswith("cart_add_"))
async def add_to_cart(cb: CallbackQuery, state: FSMContext):
    cid = cb.data.replace("cart_add_", "")
    ch = await get_active_channels()
    info = ch.get(cid)
    if not info:
        await cb.answer("Канал не найден или скрыт", True)
        return

    from handlers.cart import get_cart, save_cart
    cart = await get_cart(cb.from_user.id)

    for item in cart:
        if item.get("id") == cid and 'date' not in item:
            await cb.answer("Этот канал уже в корзине", show_alert=True)
            return

    cart.append({"id": cid, "name": info['name'], "price": info['price'], "url": info['url']})
    await save_cart(cb.from_user.id, cart)
    await cb.answer(f"✅ {info['name']} добавлен в корзину!", False)
