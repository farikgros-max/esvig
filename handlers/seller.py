from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import create_seller_application, get_seller_channels, get_seller_applications

router = Router()

class SellerStates(StatesGroup):
    waiting_for_channel_url = State()
    waiting_for_price = State()
    waiting_for_description = State()

@router.message(F.text == "📢 Стать продавцом")
async def seller_start(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Подать заявку", callback_data="seller_apply")],
        [InlineKeyboardButton(text="📋 Мои каналы", callback_data="seller_channels")],
        [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
    ])
    await m.answer("📢 Биржа каналов\n\nЗдесь вы можете разместить свой канал для продажи рекламы.", reply_markup=kb)

@router.callback_query(F.data == "seller_apply")
async def seller_apply(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("🔗 Отправьте ссылку на ваш канал (например, https://t.me/username):")
    await state.set_state(SellerStates.waiting_for_channel_url)
    await cb.answer()

@router.message(SellerStates.waiting_for_channel_url)
async def seller_channel_url(m: Message, state: FSMContext):
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Ссылка должна начинаться с https://t.me/")
        return
    await state.update_data(channel_url=url)
    await m.answer("💰 Введите цену за размещение (в $):")
    await state.set_state(SellerStates.waiting_for_price)

@router.message(SellerStates.waiting_for_price)
async def seller_price(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите цену целым числом.")
        return
    price = int(m.text)
    await state.update_data(price=price)
    await m.answer("📝 Введите описание вашего канала (или нажмите 'Пропустить', отправив любое слово):")
    await state.set_state(SellerStates.waiting_for_description)

@router.message(SellerStates.waiting_for_description)
async def seller_description(m: Message, state: FSMContext):
    desc = m.text.strip()
    data = await state.get_data()
    channel_url = data['channel_url']
    price = data['price']
    # Получаем username из ссылки для уведомления
    username = m.from_user.username or "нет username"
    # Пытаемся получить название канала
    try:
        chat = await m.bot.get_chat(channel_url.split('/')[-1])
        channel_name = chat.title
    except:
        channel_name = channel_url
    await create_seller_application(m.from_user.id, username, channel_url, channel_name, price, desc)
    await m.answer(
        f"✅ Заявка на канал «{channel_name}» отправлена.\n"
        "Мы рассмотрим её в ближайшее время.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
        ])
    )
    await state.clear()

@router.callback_query(F.data == "seller_channels")
async def seller_channels(cb: CallbackQuery):
    channels = await get_seller_channels(cb.from_user.id)
    if not channels:
        await cb.message.edit_text("У вас нет зарегистрированных каналов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Подать заявку", callback_data="seller_apply")],
            [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
        ]))
        await cb.answer()
        return
    text = "📋 Ваши каналы:\n\n"
    for ch in channels:
        status = "🟢 Активен" if ch['status'] == 'approved' else "🕒 На модерации"
        text += f"• {ch['channel_name']} ({ch['price']}$)\n   Статус: {status}\n\n"
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
    ]))
    await cb.answer()
