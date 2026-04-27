from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
import re

from database import get_or_create_user, get_user_by_referral_code, get_referral_stats

router = Router()

@router.message(Command("start"))
async def referral_start(m: Message):
    # Извлекаем реферальный код из deep-link, если есть
    args = m.text.split()
    inviter_id = None
    if len(args) > 1:
        ref_param = args[1]
        # ref может быть в формате ref_123456789
        if ref_param.startswith("ref_"):
            ref_code = ref_param[4:]
            inviter = await get_user_by_referral_code(ref_code)
            if inviter:
                inviter_id = inviter['user_id']
    # Создаём пользователя с учётом пригласившего
    await get_or_create_user(m.from_user.id, m.from_user.username, inviter_id)
    # Вызываем стандартное приветствие из start.py
    from handlers.start import start
    await start(m)

@router.message(Command("referral"))
async def referral_info(m: Message):
    user = await get_or_create_user(m.from_user.id)
    code = user.get('referral_code', '')
    stats = await get_referral_stats(m.from_user.id)
    bot = await m.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{code}"
    text = (
        f"👥 Реферальная программа\n\n"
        f"Ваш код: `{code}`\n"
        f"Ссылка: {link}\n\n"
        f"Приглашено друзей: {stats['invited']}\n"
        f"Заработано бонусов: {stats['bonuses']}$\n\n"
        "Приглашайте друзей и получайте 5% от их заказов!"
    )
    await m.answer(text, parse_mode="Markdown")
