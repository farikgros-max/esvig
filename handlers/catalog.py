from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import get_channels, get_all_categories, get_channel
from keyboards import (
    get_categories_keyboard,
    get_catalog_keyboard,
    get_back_keyboard,
    get_channel_view_keyboard,
    get_main_keyboard
)

router = Router()


# ---------------- CATALOG START ----------------

@router.message(F.text == "📋 Каталог каналов")
async def catalog_start(m: Message):
    cats = await get_all_categories()

    if not cats:
        await m.answer("Категории не найдены")
        return

    await m.answer(
        "Выберите категорию:",
        reply_markup=await get_categories_keyboard(cats)
    )


# ---------------- CATEGORY SELECT ----------------

@router.callback_query(F.data.startswith("category_select_"))
async def select_category(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[2])

    ch = await get_channels(cat_id)

    if not ch:
        await cb.message.edit_text(
            "В этой категории пока нет каналов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🔙 Назад к категориям",
                        callback_data="back_to_categories"
                    )
                ]]
            )
        )
        await cb.answer()
        return

    kb, page, total = get_catalog_keyboard(ch, cat_id, 0)

    await cb.message.edit_text(
        f"📢 Каналы в категории (страница 1/{total})",
        reply_markup=kb
    )
    await cb.answer()


# ---------------- SORT ----------------

@router.callback_query(F.data.startswith("sort_"))
async def sort_catalog(cb: CallbackQuery):
    parts = cb.data.split("_")

    cat_id = int(parts[1])
    field = parts[2]
    order = parts[3]
    page = int(parts[4])

    sort_key = f"{field}_{order}"

    ch = await get_channels(cat_id)

    kb, cur, total = get_catalog_keyboard(
        ch,
        cat_id,
        page,
        sort_by=sort_key
    )

    await cb.message.edit_text(
        f"📢 Каналы в категории (страница {cur+1}/{total})",
        reply_markup=kb
    )
    await cb.answer()


# ---------------- BACK TO CATEGORIES ----------------

@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(cb: CallbackQuery):
    cats = await get_all_categories()

    if not cats:
        await cb.message.edit_text(
            "Категории не найдены",
            reply_markup=get_back_keyboard()
        )
        await cb.answer()
        return

    await cb.message.edit_text(
        "Выберите категорию:",
        reply_markup=await get_categories_keyboard(cats)
    )
    await cb.answer()


# ---------------- PAGINATION ----------------

@router.callback_query(F.data.startswith("view_catalog_page_"))
async def view_catalog_page(cb: CallbackQuery):
    parts = cb.data.split("_")

    cat_id = int(parts[3])
    page = int(parts[4])
    sort_by = parts[5] if len(parts) > 5 else "default"

    ch = await get_channels(cat_id)

    kb, cur, total = get_catalog_keyboard(
        ch,
        cat_id,
        page,
        sort_by=sort_by
    )

    if kb:
        await cb.message.edit_text(
            f"📢 Каналы в категории (страница {cur+1}/{total})",
            reply_markup=kb
        )
    else:
        await cb.message.edit_text(
            "Каталог пуст",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🔙 Назад к категориям",
                        callback_data="back_to_categories"
                    )
                ]]
            )
        )

    await cb.answer()


# ---------------- BACK TO CATALOG ----------------

@router.callback_query(F.data == "back_to_catalog")
async def back_to_catalog(cb: CallbackQuery):
    cats = await get_all_categories()

    if not cats:
        await cb.message.edit_text(
            "Категории не найдены",
            reply_markup=get_back_keyboard()
        )
        await cb.answer()
        return

    await cb.message.edit_text(
        "Выберите категорию:",
        reply_markup=await get_categories_keyboard(cats)
    )
    await cb.answer()


# ---------------- MAIN MENU ----------------

@router.callback_query(F.data == "back_to_main_menu")
async def back_main_menu(cb: CallbackQuery):
    await cb.message.delete()
    await cb.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(cb.from_user.id)
    )
    await cb.answer()


# ---------------- CHANNEL VIEW ----------------

@router.callback_query(F.data.startswith("channel_view_"))
async def view_channel(cb: CallbackQuery):
    cid = cb.data.replace("channel_view_", "")

    ch = await get_channels()
    info = ch.get(cid)

    if not info:
        await cb.answer("Канал не найден", show_alert=True)
        return

    txt = (
        f"📌 {info['name']}\n"
        f"👥 Подписчиков: {info['subscribers']}\n"
        f"💰 Цена: {info['price']}$\n"
        f"🔗 Ссылка: {info['url']}\n"
        f"📝 Описание:\n{info.get('description','Нет описания')}"
    )

    await cb.message.edit_text(
        txt,
        reply_markup=get_channel_view_keyboard(cid)
    )
    await cb.answer()


# ---------------- ADD TO CART ----------------

@router.callback_query(F.data.startswith("cart_add_"))
async def add_to_cart(cb: CallbackQuery):
    cid = cb.data.replace("cart_add_", "")

    ch = await get_channels()
    info = ch.get(cid)

    if not info:
        await cb.answer("Канал не найден", show_alert=True)
        return

    from handlers.cart import get_cart, save_cart

    cart = get_cart(cb.from_user.id)

    cart.append({
        "id": cid,
        "name": info["name"],
        "price": info["price"]
    })

    save_cart(cb.from_user.id, cart)

    await cb.answer(f"✅ {info['name']} добавлен в корзину!", show_alert=False)
