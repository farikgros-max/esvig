from aiogram import Router, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile

from database import add_user, get_or_create_user, get_user, get_user_by_referral_code
from keyboards import get_main_keyboard
from texts import start_text

router = Router()

async def send_welcome(bot, chat_id: int, user_id: int, first_name: str, username: str):
    user = await get_user(user_id)
    if not user:
        await add_user(user_id, username or "", first_name or "", "")
        balance = 0
    else:
        balance = user.get('balance', 0)
    name = first_name or username or "друг"
    caption = start_text.format(name=name, balance=balance)
    kb = get_main_keyboard(user_id)
    try:
        photo = FSInputFile("welcome.jpg")
        await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, reply_markup=kb)
    except FileNotFoundError:
        await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)

@router.message(CommandStart())
async def start_command(message: types.Message):
    inviter_id = None
    args = (message.text or "").split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("ref_"):
        inviter = await get_user_by_referral_code(args[1][4:])
        if inviter:
            inviter_id = inviter['user_id']
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        inviter_id=inviter_id if inviter_id != message.from_user.id else None,
    )
    await send_welcome(
        message.bot,
        message.chat.id,
        message.from_user.id,
        message.from_user.first_name,
        message.from_user.username,
    )
