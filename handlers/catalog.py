from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext          # ← добавлен импорт

from database import get_active_channels, get_all_categories, get_channel, get_free_slots
from keyboards import (get_categories_keyboard, get_catalog_keyboard,
                       get_back_keyboard, get_channel_view_keyboard, get_main_keyboard,
                       get_free_slots_keyboard)
from config import ADMIN_IDS

router = Router()

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

@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(cb: CallbackQuery):
    cats = await get_all_categories()
    if not cats:
        await cb.message.edit_text("Категории не найдены", reply_markup=get_back_keyboard())
        await cb.answer()
        return
    await cb.message.edit_text("Выберите категорию:", reply_markup=await get_categories_keyboard(get_all_categories))
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
    await cb.message.delete()
    await cb.message.answer("Главное меню:", reply_markup=get_main_keyboard(cb.from_user.id))
    await cb.answer()

@router.callback_query(F.data.startswith("channel_view_"))
async def view_channel(cb: CallbackQuery):
    cid = cb.data.replace("channel_view_", "")
    ch = await get_active_channels()
    info = ch.get(cid)
    if not info:
        await cb.answer("Канал не найден или скрыт", True)
        return
    txt = f"📌 {info['name']}\n👥 Подписчиков: {info['subscribers']}\n💰 Цена: {info['price']}$\n🔗 Ссылка: {info['url']}\n📝 Описание:\n{info.get('description','Нет описания')}"

    # Проверим свободные слоты
    free_slots = await get_free_slots(cid)
    kb = get_channel_view_keyboard(cid)
    if free_slots:
        kb.inline_keyboard.insert(0, [InlineKeyboardButton(text="📅 Выбрать дату", callback_data=f"show_slots_{cid}")])
    await cb.message.edit_text(txt, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("show_slots_"))
async def show_free_slots(cb: CallbackQuery):
    cid = cb.data.replace("show_slots_", "")
    free = await get_free_slots(cid)
    if not free:
        await cb.answer("Нет свободных дат", show_alert=True)
        return
    await cb.message.edit_text("📅 Доступные даты для размещения:", reply_markup=get_free_slots_keyboard(cid, free))
    await cb.answer()

@router.callback_query(F.data.startswith("choose_slot_"))
async def choose_slot(cb: CallbackQuery, state: FSMContext):
    # ожидается формат choose_slot_{channel_id}_{date}
    parts = cb.data.split("_")
    channel_id = parts[2]
    date = parts[3]
    # Сохраняем выбранную дату в FSM, чтобы потом добавить в корзину с датой
    await state.update_data(selected_date=date)
    await cb.answer(f"Дата {date} выбрана. Теперь добавьте канал в корзину.", show_alert=False)
    # Возвращаемся к просмотру канала
    await view_channel(cb)

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

    # Проверяем, есть ли выбранная дата в FSM
    data = await state.get_data()
    selected_date = data.get("selected_date")
    if selected_date:
        # Добавляем элемент с датой
        cart.append({"id": cid, "name": info['name'], "price": info['price'], "date": selected_date})
        await state.update_data(selected_date=None)  # сброс
    else:
        cart.append({"id": cid, "name": info['name'], "price": info['price']})

    await save_cart(cb.from_user.id, cart)
    await cb.answer(f"✅ {info['name']} добавлен в корзину!", False)
