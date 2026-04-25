from aiogram import Router, F
from aiogram.types import Message
from texts import ABOUT_MESSAGE, FAQ_MESSAGE, CONTACTS_MESSAGE

router = Router()

@router.message(F.text == "ℹ️ О сервисе")
async def about(m: Message):
    await m.answer(ABOUT_MESSAGE)

@router.message(F.text == "❓ FAQ")
async def faq(m: Message):
    await m.answer(FAQ_MESSAGE)

@router.message(F.text == "📞 Контакты")
async def contacts(m: Message):
    await m.answer(CONTACTS_MESSAGE)
