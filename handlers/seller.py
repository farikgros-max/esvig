from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import create_seller_application, get_seller_channels

router = Router()

class SellerStates(StatesGroup):
    waiting_for_channel_url = State()
    waiting_for_price = State()
    waiting_for_description = State()

async def submit_application(m: Message, state: FSMContext, description: str):
    """Общая логика создания заявки с обработкой ошибок."""
    try:
        data = await state.get_data()
        channel_url = data['channel_url']
        price = data['price']
        username = m.from_user.username or "нет username"

        # Пытаемся получить название канала
        channel_name = channel_url
        try:
            chat_id = "@" + channel_url.split('/')[-1]
            chat = await m.bot.get_chat(chat_id)
            channel_name = chat.title
        except Exception:
            await m.answer("⚠️ Не удалось получить название канала. Заявка будет сохранена с URL в качестве имени.")

        # Отправляем заявку
        await create_seller_application(m.from_user.id, username, channel_url, channel_name, price, description)
        await m.answer(
            f"✅ Заявка на канал «{channel_name}» отправлена.\nМы рассмотрим её в ближайшее время.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
            ])
        )
        await state.clear()
    except Exception as e:
        # Логируем ошибку и сообщаем пользователю
        import logging
        logging.error(f"Ошибка при создании заявки продавца: {e}", exc_info=True)
        await m.answer("❌ Не удалось отправить заявку. Попробуйте позже или обратитесь в поддержку.")
        await state.clear()

# ---------- Вход в раздел продавца ----------
@router.message(F.text == "📢 Стать продавцом")
@router.message(F.text == "🏪 Биржа каналов")
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
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_description")]
    ])
    await m.answer("📝 Введите описание вашего канала или нажмите кнопку ниже:", reply_markup=kb)
    await state.set_state(SellerStates.waiting_for_description)

@router.callback_query(F.data == "skip_description", SellerStates.waiting_for_description)
async def skip_description(cb: CallbackQuery, state: FSMContext):
    await submit_application(cb.message, state, "")
    await cb.answer()

@router.message(SellerStates.waiting_for_description)
async def seller_description(m: Message, state: FSMContext):
    await submit_application(m, state, m.text.strip())

@router.callback_query(F.data == "seller_channels")
async def seller_channels(cb: CallbackQuery):
    try:
        channels = await get_seller_channels(cb.from_user.id)
    except Exception:
        await cb.answer("Не удалось загрузить каналы.", show_alert=True)
        return
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
