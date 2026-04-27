from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import requests

from database import (get_or_create_user, get_user_daily_info, get_orders_by_user,
                      get_user_balance, update_user_balance, debit_balance,
                      get_order_by_id, update_order_status, return_balance)
from states import OrderForm
from texts import (PROFILE_TEMPLATE, DEPOSIT_PROMPT, MIN_DEPOSIT_ERROR,
                   CHECK_PAYMENT_MESSAGE)
from keyboards import (get_profile_keyboard, get_main_keyboard, cancel_keyboard)
from config import MIN_DEPOSIT, PAID_BTN_URL, CRYPTO_BOT_TOKEN, XROCKET_API_KEY, ADMIN_IDS

router = Router()

@router.message(F.text == "👤 Мой профиль")
async def profile(m: Message):
    try:
        user = await get_or_create_user(m.from_user.id, m.from_user.username or "")
        daily_limit, daily_used = 0, 0
        try:
            daily_limit, daily_used = await get_user_daily_info(m.from_user.id)
        except Exception:
            pass
        left_orders = max(daily_limit - daily_used, 0) if daily_limit > 0 else "∞"

        total_spent = 0
        total_orders = 0
        try:
            completed_orders = await get_orders_by_user(m.from_user.id, limit=1000, only_completed=True)
            total_spent = sum(o['total'] for o in completed_orders)
            total_orders = len(completed_orders)
        except Exception:
            pass

        txt = PROFILE_TEMPLATE.format(
            user_id=m.from_user.id,
            username=m.from_user.username or 'не указан',
            total_orders=total_orders,
            total_spent=total_spent,
            balance=user.get('balance', 0),
            left_orders=left_orders,
            daily_limit=daily_limit if daily_limit > 0 else '∞'
        )
        # Вот эта строка вернёт кнопки
        await m.answer(txt, reply_markup=get_profile_keyboard())
    except Exception as e:
        await m.answer(f"❌ Ошибка загрузки профиля: {e}", reply_markup=get_main_keyboard(m.from_user.id))

# Остальные обработчики (пополнение, заявки) остаются без изменений
# ...
