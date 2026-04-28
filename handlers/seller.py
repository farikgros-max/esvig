from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import date
import re

from database import (get_or_create_user, submit_seller_channel, get_seller_channels,
                      update_seller_channel_status, get_seller_channel_by_id,
                      set_calendar_dates, get_calendar_dates)
from states import SellerStates
from utils import is_admin, admin_only_message, admin_only_callback, log_admin_action

router = Router()

# ---------- Кнопка "Стать продавцом" в главном меню ----------
@router.message(F.text == "📢 Стать продавцом")
async def become_seller(m: Message, state: FSMContext):
    await m.answer("Отправьте ссылку на ваш канал (https://t.me/username):")
    await state.set_state(SellerStates.waiting_for_channel_url)

@router.message(SellerStates.waiting_for_channel_url)
async def seller_url(m: Message, state: FSMContext):
    url = m.text.strip()
    if not re.match(r'(?:https?://)?t(?:elegram)?\.me/(?:joinchat/)?([a-zA-Z0-9_]+)', url):
        await m.answer("Неверная ссылка. Попробуйте ещё раз.")
        return
    await state.update_data(channel_url=url)
    await m.answer("Введите название канала:")
    await state.set_state(SellerStates.waiting_for_channel_name)

@router.message(SellerStates.waiting_for_channel_name)
async def seller_name(m: Message, state: FSMContext):
    await state.update_data(channel_name=m.text)
    await m.answer("Опишите ваш канал (кратко):")
    await state.set_state(SellerStates.waiting_for_description)

@router.message(SellerStates.waiting_for_description)
async def seller_desc(m: Message, state: FSMContext):
    await state.update_data(description=m.text)
    await m.answer("Укажите цену за рекламный пост (целое число):")
    await state.set_state(SellerStates.waiting_for_price)

@router.message(SellerStates.waiting_for_price)
async def seller_price(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите целое число (например, 100).")
        return
    price = int(m.text)
    data = await state.get_data()
    seller_id = m.from_user.id
    username = m.from_user.username or "Без username"
    await get_or_create_user(seller_id, username)
    await submit_seller_channel(
        seller_id,
        data['channel_name'],
        data['channel_url'],
        data['description'],
        price
    )
    await m.answer(
        "✅ Заявка отправлена на модерацию. После одобрения администратором вы сможете управлять календарём.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Мой календарь", callback_data="seller_calendar_menu")]
        ])
    )
    await state.clear()

# ---------- Личный кабинет продавца (управление календарём) ----------
@router.callback_query(F.data == "seller_calendar_menu")
async def seller_calendar_menu(cb: CallbackQuery, state: FSMContext):
    # Проверяем, есть ли у пользователя одобренные каналы
    channels = await get_seller_channels('approved')
    my_channels = [ch for ch in channels if ch['seller_id'] == cb.from_user.id]
    if not my_channels:
        await cb.message.edit_text(
            "У вас нет одобренных каналов для управления календарём. Ожидайте модерацию.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
            ])
        )
        await cb.answer()
        return
    # Показываем список своих каналов
    text = "Ваши каналы:\n"
    for ch in my_channels:
        text += f"• {ch['channel_name']} (id={ch['id']})\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📅 Управление датами для {ch['channel_name']}", callback_data=f"seller_set_dates_{ch['id']}")] for ch in my_channels
    ] + [[InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("seller_set_dates_"))
async def seller_set_dates_start(cb: CallbackQuery, state: FSMContext):
    channel_id = int(cb.data.split("_")[-1])
    await state.update_data(seller_channel_id=channel_id)
    await cb.message.edit_text(
        "Введите свободные даты через запятую в формате ГГГГ-ММ-ДД (например: 2026-04-30, 2026-05-01):"
    )
    await state.set_state(SellerStates.waiting_for_calendar_dates)
    await cb.answer()

@router.message(SellerStates.waiting_for_calendar_dates)
async def seller_save_dates(m: Message, state: FSMContext):
    data = await state.get_data()
    channel_id = data['seller_channel_id']
    dates_str = m.text.strip()
    dates = []
    for part in dates_str.split(","):
        part = part.strip()
        try:
            d = date.fromisoformat(part)
            dates.append(d)
        except ValueError:
            await m.answer(f"Неверный формат даты: {part}. Используйте ГГГГ-ММ-ДД.")
            return
    await set_calendar_dates(channel_id, dates)
    await m.answer("✅ Даты сохранены!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Мой календарь", callback_data="seller_calendar_menu")]
    ]))
    await state.clear()

# ---------- АДМИНСКАЯ МОДЕРАЦИЯ ----------
@router.callback_query(F.data == "admin_seller_list")
async def admin_seller_list(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    pending = await get_seller_channels('pending')
    if not pending:
        await cb.message.edit_text("Нет заявок на модерацию.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
        ]))
        await cb.answer()
        return
    text = "📋 Заявки продавцов:\n\n"
    for ch in pending:
        text += f"#{ch['id']} | {ch['channel_name']} | {ch['price']}$ | От: {ch['seller_id']}\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📄 Заявка #{ch['id']}", callback_data=f"admin_review_seller_{ch['id']}")] for ch in pending
    ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("admin_review_seller_"))
async def admin_review_seller(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    channel_id = int(cb.data.split("_")[-1])
    ch = await get_seller_channel_by_id(channel_id)
    if not ch:
        await cb.answer("Заявка не найдена", True)
        return
    text = f"Заявка #{ch['id']}\nНазвание: {ch['channel_name']}\nСсылка: {ch['channel_url']}\nОписание: {ch['description']}\nЦена: {ch['price']}$\nПродавец: {ch['seller_id']}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"admin_approve_seller_{ch['id']}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_reject_seller_{ch['id']}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_seller_list")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("admin_approve_seller_"))
async def admin_approve_seller(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    channel_id = int(cb.data.split("_")[-1])
    ch = await get_seller_channel_by_id(channel_id)
    await update_seller_channel_status(channel_id, 'approved')
    log_admin_action(cb.from_user.id, f"approved seller channel {channel_id}")
    # Уведомим продавца
    try:
        await cb.bot.send_message(ch['seller_id'], f"✅ Ваша заявка на канал «{ch['channel_name']}» одобрена! Теперь вы можете управлять календарём: /seller")
    except: pass
    await cb.answer("Канал одобрен", False)
    await admin_seller_list(cb)

@router.callback_query(F.data.startswith("admin_reject_seller_"))
async def admin_reject_seller(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    channel_id = int(cb.data.split("_")[-1])
    ch = await get_seller_channel_by_id(channel_id)
    await update_seller_channel_status(channel_id, 'rejected')
    log_admin_action(cb.from_user.id, f"rejected seller channel {channel_id}")
    try:
        await cb.bot.send_message(ch['seller_id'], f"❌ Ваша заявка на канал «{ch['channel_name']}» отклонена.")
    except: pass
    await cb.answer("Канал отклонен", False)
    await admin_seller_list(cb)
