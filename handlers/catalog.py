from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import get_all_channels, get_all_categories, get_channel
from keyboards import (get_categories_keyboard, get_catalog_keyboard,
                       get_back_keyboard, get_channel_view_keyboard, get_main_keyboard)

router = Router()


@router.message(F.text == "📋 Каталог каналов")
async def catalog_start(m: Message):
    cats = await get_all_categories()
    if not cats:
        await m.answer("Категории не найдены")
        return

    await m.answer("Выберите категорию:", reply_markup=await get_categories_keyboard(cats))


@router.callback_query(F.data.startswith("category_select_"))
async def select_category(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[2])
    ch = await get_all_channels(cat_id)

    if not ch:
        await cb.message.edit_text(
            "В этой категории пока нет каналов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_categories")]]
            )
        )
        await cb.answer()
        return

    kb, page, total = get_catalog_keyboard(ch, cat_id, 0)
    await cb.message.edit_text(f"📢 Каналы (1/{total})", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("view_catalog_page_"))
async def view_catalog_page(cb: CallbackQuery):
    parts = cb.data.split("_")
    cat_id = int(parts[3])
    page = int(parts[4])

    ch = await get_all_channels(cat_id)

    if not ch:
        await cb.message.edit_text("Каталог пуст")
        await cb.answer()
        return

    kb, cur, total = get_catalog_keyboard(ch, cat_id, page)
    await cb.message.edit_text(f"📢 Каналы ({cur+1}/{total})", reply_markup=kb)
    await cb.answer()


# 🔥 ГЛАВНЫЙ ФИКС
@router.callback_query(F.data.startswith("channel_view_"))
async def view_channel(cb: CallbackQuery):
    cid = cb.data.replace("channel_view_", "")

    info = await get_channel(cid)

    if not info:
        await cb.answer("Канал не найден", True)
        return

    text = (
        f"📌 {info['name']}\n"
        f"👥 {info['subscribers']}\n"
        f"💰 {info['price']}$\n"
        f"🔗 {info['url']}\n\n"
        f"{info.get('description', '')}"
    )

    await cb.message.edit_text(text, reply_markup=get_channel_view_keyboard(cid))
    await cb.answer()


@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(cb: CallbackQuery):
    cats = await get_all_categories()
    await cb.message.edit_text("Выберите категорию:", reply_markup=await get_categories_keyboard(cats))
    await cb.answer()


@router.callback_query(F.data == "back_to_main_menu")
async def back_main_menu(cb: CallbackQuery):
    await cb.message.delete()
    await cb.message.answer("Главное меню:", reply_markup=get_main_keyboard(cb.from_user.id))
    await cb.answer()
