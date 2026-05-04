from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from datetime import datetime

from database import (create_seller_application, get_seller_channels,
                      get_approved_seller_channels, get_all_categories,
                      set_slot, get_channel_slots, get_free_slots,
                      get_seller_channel_stats, get_calendar_fill_rate)
from keyboards import (get_seller_categories_keyboard, get_seller_main_keyboard,
                       get_seller_channel_keyboard, get_seller_calendar_keyboard,
                       get_seller_analytics_keyboard, cancel_keyboard, get_main_keyboard)
from states import SellerStates, SellerCalendarStates

router = Router()

async def seller_start(m: Message):
    """Показывает меню биржи в зависимости от статуса продавца."""
    approved_channels = await get_approved_seller_channels(m.from_user.id)
    if not approved_channels:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Подать заявку", callback_data="seller_apply")],
            [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
        ])
        await m.answer("🏪 Биржа каналов\n\nУ вас ещё нет одобренных каналов. Подайте заявку, чтобы начать продавать рекламу.", reply_markup=kb)
    else:
        await m.answer("🏪 Биржа каналов\n\nВыберите действие:", reply_markup=get_seller_main_keyboard())

@router.message(F.text == "🏪 Биржа каналов")
async def exchange_menu(m: Message):
    await seller_start(m)

@router.callback_query(F.data == "seller_back")
async def seller_back(cb: CallbackQuery):
    from handlers.start import start
    await start(cb.message)
    await cb.answer()

# Отмена при заполнении заявки
@router.callback_query(F.data == "cancel_add_channel", SellerStates.waiting_for_channel_url)
@router.callback_query(F.data == "cancel_add_channel", SellerStates.waiting_for_price)
@router.callback_query(F.data == "cancel_add_channel", SellerStates.waiting_for_description)
async def cancel_seller_process(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await seller_start(cb.message)
    await cb.answer()

# ---------- Добавление канала продавцом ----------
@router.callback_query(F.data == "seller_apply")
async def seller_apply(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("🏷 Выберите категорию для вашего канала:", reply_markup=await get_seller_categories_keyboard(get_all_categories))
    await state.set_state(SellerStates.waiting_for_category)
    await cb.answer()

@router.callback_query(F.data.startswith("seller_cat_"), SellerStates.waiting_for_category)
async def seller_category_chosen(cb: CallbackQuery, state: FSMContext):
    cat_id = int(cb.data.split("_")[2])
    await state.update_data(category_id=cat_id)
    await cb.message.edit_text("🔗 Отправьте ссылку на ваш канал (например, https://t.me/username):", reply_markup=cancel_keyboard())
    await state.set_state(SellerStates.waiting_for_channel_url)
    await cb.answer()

@router.message(SellerStates.waiting_for_channel_url)
async def seller_channel_url(m: Message, state: FSMContext):
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Ссылка должна начинаться с https://t.me/")
        return
    await state.update_data(channel_url=url)
    await m.answer("💰 Введите цену размещения в $ (с учётом комиссии 15%):\n(Например, при вводе 100$ вы получите 85$)", reply_markup=cancel_keyboard())
    await state.set_state(SellerStates.waiting_for_price)

@router.message(SellerStates.waiting_for_price)
async def seller_price(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите цену целым числом.")
        return
    price = int(m.text)
    await state.update_data(price=price)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_description")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_channel")]
    ])
    await m.answer("📝 Введите описание вашего канала или нажмите кнопку ниже:", reply_markup=kb)
    await state.set_state(SellerStates.waiting_for_description)

@router.callback_query(F.data == "skip_description", SellerStates.waiting_for_description)
async def skip_description(cb: CallbackQuery, state: FSMContext):
    await submit_seller_application(cb.message, state, "")
    await cb.answer()

@router.message(SellerStates.waiting_for_description)
async def seller_description(m: Message, state: FSMContext):
    await submit_seller_application(m, state, m.text.strip())

async def submit_seller_application(m: Message, state: FSMContext, description: str):
    try:
        data = await state.get_data()
        channel_url = data['channel_url']
        price = data['price']
        category_id = data.get('category_id')
        username = m.from_user.username or "нет username"

        channel_name = channel_url
        try:
            chat_id = "@" + channel_url.split('/')[-1]
            chat = await m.bot.get_chat(chat_id)
            channel_name = chat.title
        except Exception:
            pass

        await create_seller_application(m.from_user.id, username, channel_url, channel_name, price, description, category_id)
        await m.answer(
            f"✅ Заявка на канал «{channel_name}» отправлена.\nЦена: {price}$ (вам: {int(price * 0.85)}$ после комиссии 15%)\nМы рассмотрим её в ближайшее время.",
            reply_markup=get_seller_main_keyboard()
        )
        await state.clear()
    except Exception as e:
        logging.error(f"Ошибка при создании заявки продавца: {e}")
        await m.answer("❌ Не удалось отправить заявку. Попробуйте позже.")
        await state.clear()

# ---------- Просмотр каналов продавца ----------
@router.callback_query(F.data == "seller_channels")
async def seller_channels(cb: CallbackQuery):
    channels = await get_seller_channels(cb.from_user.id)
    if not channels:
        await cb.message.edit_text("У вас нет зарегистрированных каналов.", reply_markup=get_seller_main_keyboard())
        await cb.answer()
        return
    text = "📋 Ваши каналы:\n\n"
    for ch in channels:
        status_emoji = {"pending": "🕒 На модерации", "approved": "🟢 Активен", "rejected": "🔴 Отклонён"}
        status = status_emoji.get(ch['status'], ch['status'])
        price = ch['price']
        text += f"• {ch['channel_name']} ({price}$ / вам {int(price * 0.85)}$)\n   Статус: {status}\n\n"
    await cb.message.edit_text(text, reply_markup=get_seller_main_keyboard())
    await cb.answer()

# ---------- Просмотр конкретного канала ----------
@router.callback_query(F.data.startswith("seller_channel_"))
async def seller_channel_view(cb: CallbackQuery):
    channel_id = int(cb.data.split("_")[-1])
    approved = await get_approved_seller_channels(cb.from_user.id)
    if not any(ch['id'] == channel_id for ch in approved):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await cb.message.edit_text("Управление каналом:", reply_markup=get_seller_channel_keyboard(channel_id))
    await cb.answer()

# ---------- КАЛЕНДАРЬ ----------
@router.callback_query(F.data.startswith("seller_calendar_"))
async def seller_calendar_menu(cb: CallbackQuery):
    _, _, channel_id = cb.data.split("_")
    approved = await get_approved_seller_channels(cb.from_user.id)
    if not any(ch['id'] == int(channel_id) for ch in approved):
        await cb.answer("Нет доступа", show_alert=True)
        return
    slots = await get_channel_slots(channel_id)
    text = "📅 Календарь канала\n\n"
    if slots:
        for s in slots[:10]:
            status = "🔴 Занято" if s['status'] == 'booked' else "🟢 Свободно"
            text += f"{s['date']} – {status}\n"
    else:
        text += "Нет отмеченных дат."
    await cb.message.edit_text(text, reply_markup=get_seller_calendar_keyboard(int(channel_id)))
    await cb.answer()

@router.callback_query(F.data.startswith("seller_calendar_add_"))
async def seller_calendar_add(cb: CallbackQuery, state: FSMContext):
    channel_id = int(cb.data.split("_")[-1])
    approved = await get_approved_seller_channels(cb.from_user.id)
    if not any(ch['id'] == channel_id for ch in approved):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.update_data(calendar_channel_id=channel_id)
    await cb.message.edit_text("Введите дату в формате ГГГГ-ММ-ДД (например, 2026-05-10):")
    await state.set_state(SellerCalendarStates.waiting_for_date)
    await cb.answer()

@router.message(SellerCalendarStates.waiting_for_date)
async def process_calendar_date(m: Message, state: FSMContext):
    date_str = m.text.strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await m.answer("Неверный формат. Введите дату как ГГГГ-ММ-ДД")
        return
    data = await state.get_data()
    channel_id = data['calendar_channel_id']
    await set_slot(str(channel_id), m.from_user.id, date_str, "free")
    await m.answer(f"✅ Дата {date_str} отмечена как свободная.")
    await state.clear()
    # Возвращаемся к карточке канала
    await m.answer("Управление каналом:", reply_markup=get_seller_channel_keyboard(channel_id))

# ---------- АНАЛИТИКА ----------
@router.callback_query(F.data.startswith("seller_analytics_"))
async def seller_analytics_handler(cb: CallbackQuery):
    parts = cb.data.split("_")
    channel_id = int(parts[-1])
    approved = await get_approved_seller_channels(cb.from_user.id)
    if not any(ch['id'] == channel_id for ch in approved):
        await cb.answer("Нет доступа", show_alert=True)
        return
    if len(parts) == 4 and parts[2] in ("7", "30"):
        days = int(parts[2])
        await show_analytics(cb, channel_id, days)
    else:
        await cb.message.edit_text("Выберите период:", reply_markup=get_seller_analytics_keyboard(channel_id))
        await cb.answer()

async def show_analytics(cb: CallbackQuery, channel_id: int, days: int):
    stats = await get_seller_channel_stats(str(channel_id), cb.from_user.id, days)
    fill_rate = await get_calendar_fill_rate(str(channel_id))
    text = f"📊 Аналитика канала за {days} дней\n\n"
    if stats:
        total_revenue = sum(d['revenue'] for d in stats)
        total_orders = sum(d['orders'] for d in stats)
        text += f"💰 Общий доход: {total_revenue}$\n📦 Заказов: {total_orders}\n🗓 Заполненность: {fill_rate}%\n\n"
        text += "Доход по дням:\n"
        for d in stats:
            text += f"{d['day']}: {d['revenue']}$ ({d['orders']} зак.)\n"
    else:
        text += "Нет данных за этот период."
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="🔙 Назад", callback_data=f"seller_analytics_{channel_id}")]]))
    await cb.answer()
