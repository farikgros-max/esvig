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

# Проверка прав продавца (любой залогиненный пользователь может быть продавцом)
async def seller_only_callback(cb: CallbackQuery):
    # В нашем случае любой пользователь может управлять своими каналами – просто проверяем, что он автор
    # Но для безопасности добавим проверку, что канал принадлежит ему (будет внутри обработчиков)
    return True

async def seller_start(m: Message):
    approved_channels = await get_approved_seller_channels(m.from_user.id)
    if not approved_channels:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Подать заявку", callback_data="seller_apply")],
            [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
        ])
        await m.answer("🏪 Биржа каналов\n\nУ вас ещё нет одобренных каналов. Подайте заявку.", reply_markup=kb)
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

# ... (все старые обработчики seller_apply, seller_cat_, channel_url, price, description, skip_description, submit_seller_application, seller_channels) без изменений
# Они идентичны предыдущей полной версии seller.py, поэтому не дублирую здесь.

# ---------- НОВЫЕ: КАЛЕНДАРЬ ----------
@router.callback_query(F.data.startswith("seller_calendar_"))
async def seller_calendar_menu(cb: CallbackQuery):
    # Проверим, что канал принадлежит продавцу
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
    # Возврат в меню канала
    await seller_channel_card(m, channel_id)   # напишем вспомогательную функцию ниже

async def seller_channel_card(m: Message, channel_id: int):
    """Показать карточку канала (для продавца)"""
    # Можно просто отправить меню канала
    kb = get_seller_channel_keyboard(channel_id)
    await m.answer("Управление каналом:", reply_markup=kb)

# ---------- АНАЛИТИКА ----------
@router.callback_query(F.data.startswith("seller_analytics_"))
async def seller_analytics_handler(cb: CallbackQuery):
    parts = cb.data.split("_")
    channel_id = int(parts[-1])
    # Проверка принадлежности
    approved = await get_approved_seller_channels(cb.from_user.id)
    if not any(ch['id'] == channel_id for ch in approved):
        await cb.answer("Нет доступа", show_alert=True)
        return
    if len(parts) == 4 and parts[2] in ("7","30"):
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
