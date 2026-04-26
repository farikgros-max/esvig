from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import get_channels, get_categories, get_channel

from keyboards import (
    get_categories_keyboard,
    get_catalog_keyboard,
    get_back_keyboard,
    get_channel_view_keyboard,
    get_main_keyboard
)

router = Router()


# ================= START =================
@router.message(F.text == "📋 Каталог каналов")
async def catalog_start(m: Message):
    cats = await get_categories()

    if not cats:
        await m.answer("Категории не найдены")
        return

    await m.answer(
        "Выберите категорию:",
        reply_markup=await get_categories_keyboard(cats)
    )


# ================= CATEGORY =================
@router.callback_query(F.data.startswith("category_select_"))
async def select_category(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[2])

    ch = await get_channels(cat_id)

    if not ch:
        await cb.message.edit_text(
            "В этой категории пока нет каналов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔙 Назад",
                        callback_data="back_to_categories"
                    )]
                ]
            )
        )
        await cb.answer()
        return

    kb, page, total = get_catalog_keyboard(ch, cat_id, 0)

    await cb.message.edit_text(
        f"📢 Каналы (страница 1/{total})",
        reply_markup=kb
    )

    await cb.answer()


# ================= VIEW CHANNEL =================
@router.callback_query(F.data.startswith("channel_view_"))
async def view_channel(cb: CallbackQuery):
    cid = cb.data.replace("channel_view_", "")

    ch = await get_channel(cid)

    if not ch:
        await cb.answer("Канал не найден", show_alert=True)
        return

    text = (
        f"📌 {ch['name']}\n"
        f"👥 {ch['subscribers']}\n"
        f"💰 {ch['price']}$\n"
        f"🔗 {ch['url']}\n\n"
        f"{ch['description']}"
    )

    await cb.message.edit_text(
        text,
        reply_markup=get_channel_view_keyboard(cid)
    )

    await cb.answer()


# ================= BACK =================
@router.callback_query(F.data == "back_to_categories")
async def back(cb: CallbackQuery):
    cats = await get_categories()

    await cb.message.edit_text(
        "Выберите категорию:",
        reply_markup=await get_categories_keyboard(cats)
    )

    await cb.answer()
