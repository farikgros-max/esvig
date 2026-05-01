from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import os

from database import get_or_create_user, get_user_by_referral_code, get_user_balance
from texts import WELCOME_CAPTION
from keyboards import get_main_keyboard
from middlewares import is_subscribed
from config import CHANNEL_ID, ADMIN_IDS

router = Router()

@router.message(Command("start"))
async def start(m: Message):
    # --- обработка реферального кода ---
    args = m.text.split()
    inviter_id = None
    if len(args) > 1:
        ref_param = args[1]
        if ref_param.startswith("ref_"):
            ref_code = ref_param[4:]
            inviter = await get_user_by_referral_code(ref_code)
            if inviter:
                inviter_id = inviter['user_id']

    # создаём/обновляем пользователя
    user = await get_or_create_user(m.from_user.id, m.from_user.username, inviter_id)

    # --- проверка подписки ---
    if not await is_subscribed(m.bot, m.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
        ])
        await m.answer("⚠️ Чтобы пользоваться ботом, подпишитесь на наш канал.", reply_markup=kb)
        return

    # --- приветствие ---
    user_name = m.from_user.first_name or m.from_user.username or "Пользователь"
    caption = WELCOME_CAPTION.format(user_name=user_name, balance=user['balance'])
    try:
        if os.path.exists("welcome.jpg"):
            from aiogram.types import FSInputFile
            photo = FSInputFile("welcome.jpg")
            await m.answer_photo(photo, caption=caption, reply_markup=get_main_keyboard(m.from_user.id))
        else:
            raise FileNotFoundError
    except:
        await m.answer(caption, reply_markup=get_main_keyboard(m.from_user.id))

@router.callback_query(F.data == "check_sub")
async def check_sub(cb: CallbackQuery):
    if await is_subscribed(cb.bot, cb.from_user.id):
        await cb.answer("✅ Подписка подтверждена!")
        await start(cb.message)
    else:
        await cb.answer("❌ Вы ещё не подписались. Попробуйте снова.", show_alert=True)

# Команда /export
@router.message(Command("export"))
async def export_orders(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        await m.answer("⛔ Нет доступа")
        return
    await m.answer("⏳ Формирую отчёт...")
    try:
        from database import get_orders
        orders = await get_orders(limit=10000)
        if not orders:
            await m.answer("Заказов нет.")
            return
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Заказы ESVIG"
        headers = ["ID", "User ID", "Username", "Сумма", "Статус", "Дата", "Состав"]
        ws.append(headers)
        for o in orders:
            items = "; ".join([f"{it['name']}({it['price']}$)" for it in o['cart']])
            ws.append([o['id'], o['user_id'], o['username'], o['total'], o['status'], str(o['created_at']), items])
        filename = "orders_export.xlsx"
        wb.save(filename)
        from aiogram.types import FSInputFile
        file = FSInputFile(filename)
        await m.answer_document(file, caption="📋 Все заказы")
        os.remove(filename)
    except Exception as e:
        await m.answer(f"❌ Ошибка экспорта: {e}")
