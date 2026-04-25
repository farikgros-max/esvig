from aiogram import Router, F
from aiogram.types import Message
from texts import ABOUT_MESSAGE, FAQ_MESSAGE, CONTACTS_MESSAGE
from keyboards import get_admin_keyboard
from config import ADMIN_IDS

router = Router()

@router.message(F.text == "🔑 Админ‑панель")
async def admin_panel_msg(m: Message):
    if m.from_user.id in ADMIN_IDS:
        await m.answer("👑 Админ‑панель", reply_markup=get_admin_keyboard())
    else:
        await m.answer("Нет прав")

@router.message(F.text == "ℹ️ О сервисе")
async def about(m: Message):
    await m.answer(ABOUT_MESSAGE)

@router.message(F.text == "❓ FAQ")
async def faq(m: Message):
    await m.answer(FAQ_MESSAGE)

@router.message(F.text == "📞 Контакты")
async def contacts(m: Message):
    await m.answer(CONTACTS_MESSAGE)
