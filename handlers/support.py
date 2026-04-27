from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import create_ticket, get_tickets, get_ticket_messages, add_ticket_message, close_ticket

class SupportStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_message = State()

router = Router()

# ---------- Пользователь: создание тикета ----------
@router.message(F.text == "📝 Поддержка")
async def support_start(m: Message, state: FSMContext):
    await m.answer("Введите тему обращения:")
    await state.set_state(SupportStates.waiting_for_subject)

@router.message(SupportStates.waiting_for_subject)
async def support_subject(m: Message, state: FSMContext):
    await state.update_data(subject=m.text)
    await m.answer("Опишите вашу проблему:")
    await state.set_state(SupportStates.waiting_for_message)

@router.message(SupportStates.waiting_for_message)
async def support_message(m: Message, state: FSMContext):
    data = await state.get_data()
    subject = data['subject']
    message = m.text
    username = m.from_user.username or "Без username"
    ticket_id = await create_ticket(m.from_user.id, username, subject, message)
    await m.answer(
        f"✅ Обращение #{ticket_id} создано. Мы ответим вам в ближайшее время.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Мои тикеты", callback_data="my_tickets")]
        ])
    )
    await state.clear()

@router.callback_query(F.data == "my_tickets")
async def my_tickets(cb: CallbackQuery):
    # Показываем последние тикеты пользователя
    tickets = [t for t in await get_tickets('open') if t['user_id'] == cb.from_user.id]
    if not tickets:
        await cb.message.edit_text("У вас нет открытых обращений.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
        ]))
        await cb.answer()
        return
    text = "📋 Ваши обращения:\n\n"
    for t in tickets[:5]:
        text += f"#{t['id']} {t['subject']} ({t['status']})\n"
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
    ]))
    await cb.answer()
