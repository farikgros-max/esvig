from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from database import (create_seller_application, get_seller_channels,
                      get_approved_seller_channels, get_all_categories)
from keyboards import get_seller_categories_keyboard, get_seller_main_keyboard, get_main_keyboard, cancel_keyboard

router = Router()

class SellerStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_channel_url = State()
    waiting_for_price = State()
    waiting_for_description = State()

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
    await seller_start(cb.message)
    await cb.answer()

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
    if m.text == "❌ Отмена":
        await state.clear()
        await seller_start(m)
        return
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Ссылка должна начинаться с https://t.me/")
        return
    await state.update_data(channel_url=url)
    await m.answer("💰 Введите цену размещения в $ (с учётом комиссии 15%):\n(Например, при вводе 100$ вы получите 85$)", reply_markup=cancel_keyboard())
    await state.set_state(SellerStates.waiting_for_price)

@router.message(SellerStates.waiting_for_price)
async def seller_price(m: Message, state: FSMContext):
    if m.text == "❌ Отмена":
        await state.clear()
        await seller_start(m)
        return
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
    if m.text == "❌ Отмена":
        await state.clear()
        await seller_start(m)
        return
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
