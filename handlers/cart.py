from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime

from database import (
    load_cart_db, save_cart_db, clear_cart_db, release_slot,
    get_user_balance, check_daily_order_limit, save_order, get_user, debit_balance,
    increment_daily_orders, book_slot, get_free_slots
)
from keyboards import back_to_menu_keyboard, main_menu_keyboard
from config import ADMIN_IDS
from states import OrderForm

router = Router()

async def get_cart(user_id: int) -> list:
    return await load_cart_db(user_id)

async def save_cart(user_id: int, items: list):
    await save_cart_db(user_id, items)

class OrderStates(StatesGroup):
    waiting_for_confirmation = State()

# Просмотр корзины
@router.message(Command("cart"))
@router.message(F.text == "🛒 Корзина")
@router.callback_query(F.data == "cart")
async def show_cart(event):
    if isinstance(event, types.Message):
        msg = event
    else:
        msg = event.message

    user_id = event.from_user.id
    cart_items = await get_cart(user_id)
    if not cart_items:
        await msg.answer("Ваша корзина пуста.", reply_markup=back_to_menu_keyboard())
        return

    # Группируем по id канала
    grouped = {}
    for item in cart_items:
        cid = item.get("id")
        if cid not in grouped:
            grouped[cid] = {
                "name": item.get("name", "Неизвестный"),
                "price": item.get("price", 0),
                "url": item.get("url", ""),
                "dates": []
            }
        if 'date' in item and item['date']:
            grouped[cid]["dates"].append(item['date'])
        else:
            grouped[cid]["dates"].append(None)

    text = "🛒 **Ваша корзина:**\n\n"
    for cid, info in grouped.items():
        name = info["name"]
        url = info["url"]
        price = info["price"]
        dates = info["dates"]
        count = len(dates)

        text += f"📢 {name}\n"

        # Кнопка-ссылка вместо автопревью
        if url:
            text += f"🔗 [Открыть канал]({url})\n"

        formatted_dates = []
        for d in dates:
            if d is None:
                continue
            try:
                dt = datetime.strptime(d, '%Y-%m-%d')
                formatted_dates.append(dt.strftime('%d-%m-%Y'))
            except ValueError:
                if len(d) == 10 and d[4] == '-' and d[7] == '-':
                    formatted_dates.append(d)

        if formatted_dates:
            text += f"├ Даты: {', '.join(formatted_dates)}\n"
        else:
            text += "├ Даты: не указаны\n"

        text += f"├ Сумма: {price}$\n"
        total_canal = price * count
        text += f"╰ Итого: {price}$ × {count} = {total_canal}$\n\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Оформить заказ", callback_data="checkout")
    builder.button(text="🗑 Очистить корзину", callback_data="clear_cart")
    builder.button(text="↩️ Главное меню", callback_data="main_menu")
    builder.adjust(1)

    if isinstance(event, types.Message):
        await msg.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await msg.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown", disable_web_page_preview=True)

@router.callback_query(F.data == "clear_cart")
async def clear_cart_cb(callback: types.CallbackQuery):
    cart_items = await get_cart(callback.from_user.id)
    for item in cart_items:
        if 'date' in item and item['date'] and item.get('id'):
            try:
                await release_slot(item['id'], item['date'])
            except Exception as e:
                print(f"Ошибка освобождения слота {item}: {e}")
    await clear_cart_db(callback.from_user.id)
    await callback.answer("Корзина очищена")
    await show_cart(callback)

@router.callback_query(F.data == "checkout")
async def start_checkout(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cart = await get_cart(user_id)
    if not cart:
        await callback.answer("Корзина пуста", show_alert=True)
        return

    if not await check_daily_order_limit(user_id):
        await callback.answer("Вы исчерпали дневной лимит заказов.", show_alert=True)
        return

    total = sum(item.get("price", 0) for item in cart)
    balance = await get_user_balance(user_id)

    if balance < total:
        await callback.answer(f"Недостаточно средств. Баланс: {balance}$.", show_alert=True)
        return

    await callback.message.edit_text(
        f"Оформить заказ на сумму {total}$?\nВаш баланс: {balance}$",
        reply_markup=InlineKeyboardBuilder([
            [types.InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_order"),
             types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_order")]
        ]).as_markup()
    )
    await state.set_state(OrderStates.waiting_for_confirmation)
    await callback.answer()

@router.callback_query(OrderStates.waiting_for_confirmation, F.data == "confirm_order")
async def confirm_order(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cart = await get_cart(user_id)
    if not cart:
        await callback.answer("Корзина пуста", show_alert=True)
        await state.clear()
        return

    total = sum(item.get("price", 0) for item in cart)
    user = await get_user(user_id)
    username = user['username'] if user else str(user_id)

    success = await debit_balance(user_id, total, None, "Оплата заказа")
    if not success:
        await callback.answer("Не удалось списать средства.", show_alert=True)
        await state.clear()
        return

    order_id = await save_order(user_id, username, cart, total, budget=0, contact="", status="в обработке")

    for item in cart:
        if 'date' in item and item['date']:
            await book_slot(item['id'], item['date'], user_id)

    await increment_daily_orders(user_id)
    await clear_cart_db(user_id)

    for aid in ADMIN_IDS:
        try:
            items_text = "\n".join(f"{it['name']} ({it['price']}$)" for it in cart)
            await callback.bot.send_message(aid, f"💰 Новый заказ #{order_id}\nПользователь: {user_id}\nСостав:\n{items_text}\nСумма: {total}$")
        except Exception:
            pass

    await callback.message.edit_text(
        f"✅ Заказ #{order_id} оформлен!\nСумма: {total}$\nОжидайте выполнения.",
        reply_markup=back_to_menu_keyboard()
    )
    await state.clear()

@router.callback_query(OrderStates.waiting_for_confirmation, F.data == "cancel_order")
async def cancel_order_cb(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Оформление отменено.", reply_markup=back_to_menu_keyboard())
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery):
    from handlers.start import send_welcome
    await send_welcome(callback.bot, callback.from_user.id, callback.from_user.id, callback.from_user.first_name, callback.from_user.username)
    await callback.answer()
