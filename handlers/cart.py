import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import (get_user_balance, save_order, update_order_status,
                      check_daily_order_limit, get_or_create_user, debit_balance,
                      save_cart_db, load_cart_db, clear_cart_db)
from states import OrderForm
from texts import CART_EMPTY, DAILY_LIMIT, NO_FUNDS, ORDER_SUCCESS
from keyboards import get_cart_keyboard, get_main_keyboard
from config import ADMIN_IDS, ORDER_CHANNEL_ID

router = Router()

async def get_cart(uid):
    return await load_cart_db(uid)

async def save_cart(uid, cart):
    await save_cart_db(uid, cart)

@router.message(F.text == "🛒 Корзина")
async def show_cart(m: Message):
    cart = await get_cart(m.from_user.id)
    if not cart:
        await m.answer(CART_EMPTY)
        return
    kb = get_cart_keyboard(cart)
    await m.answer("🛒 Ваша корзина:", reply_markup=kb)

@router.callback_query(F.data.startswith("cart_add_"))
async def add_to_cart(cb: CallbackQuery):
    # Этот обработчик уже есть в catalog.py, но на всякий случай оставим
    pass

@router.callback_query(F.data.startswith("remove_"))
async def remove_from_cart(cb: CallbackQuery):
    idx = int(cb.data.split("_")[1])
    cart = await get_cart(cb.from_user.id)
    if idx < 0 or idx >= len(cart):
        await cb.answer("Элемент не найден", True)
        return
    removed = cart.pop(idx)
    await save_cart(cb.from_user.id, cart)
    await cb.answer(f"❌ {removed['name']} удалён из корзины", False)
    if not cart:
        await cb.message.edit_text(CART_EMPTY)
    else:
        kb = get_cart_keyboard(cart)
        await cb.message.edit_text("🛒 Ваша корзина:", reply_markup=kb)

@router.callback_query(F.data == "clear_cart")
async def clear_cart(cb: CallbackQuery):
    await clear_cart_db(cb.from_user.id)
    await cb.message.edit_text("🗑 Корзина очищена")
    await cb.answer()

@router.callback_query(F.data == "checkout")
async def checkout_cb(cb: CallbackQuery, state: FSMContext):
    cart = await get_cart(cb.from_user.id)
    if not cart:
        await cb.message.edit_text(CART_EMPTY, reply_markup=get_main_keyboard(cb.from_user.id))
        await cb.answer()
        return
    total = sum(i['price'] for i in cart)
    await state.update_data(cart=cart, total=total)
    await cb.message.edit_text(f"💳 Оформление заказа\n\nСумма: {total}$\nВведите ваш бюджет (цифрами, ≥ суммы):")
    await state.set_state(OrderForm.waiting_for_budget)
    await cb.answer()

@router.message(OrderForm.waiting_for_budget)
async def budget_input(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите число")
        return
    budget = int(m.text)
    d = await state.get_data()
    total = d.get("total", 0)
    if budget < total:
        await m.answer(f"Бюджет ({budget}$) меньше суммы ({total}$). Введите {total}$ или больше:")
        return
    await state.update_data(budget=budget)
    await m.answer("Напишите ваш Telegram username (например, @username) или другой контакт:")
    await state.set_state(OrderForm.waiting_for_contact)

@router.message(OrderForm.waiting_for_contact)
async def contact_input(m: Message, state: FSMContext):
    d = await state.get_data()
    cart = d.get("cart", [])
    total = d.get("total", 0)
    budget = d.get("budget", 0)
    contact = m.text.strip()
    username = m.from_user.username or "не указан"

    can_order = await check_daily_order_limit(m.from_user.id)
    if not can_order:
        user_info = await get_or_create_user(m.from_user.id)
        await m.answer(DAILY_LIMIT.format(limit=user_info['daily_limit']))
        await state.clear()
        return

    balance = await get_user_balance(m.from_user.id)
    if balance < total:
        order_id = await save_order(m.from_user.id, username, cart, total, budget, contact, status='ожидает оплаты')
        await clear_cart_db(m.from_user.id)
        await m.answer(
            f"⚠️ Недостаточно средств. Ваш баланс: {balance}$\n"
            f"Заказ #{order_id} создан и ожидает оплаты.\n"
            "Пополните баланс и нажмите «🔍 Проверить платёж» в профиле.",
            reply_markup=get_main_keyboard(m.from_user.id)
        )
        await state.clear()
        return

    order_id = await save_order(m.from_user.id, username, cart, total, budget, contact, status='оплачена')
    success = await debit_balance(m.from_user.id, total, order_id, description=f"Оплата заказа #{order_id}")
    if not success:
        await update_order_status(order_id, 'отменена')
        await m.answer("Не удалось списать средства. Заказ отменён. Обратитесь в поддержку.")
        await state.clear()
        return

    # Букирование слотов, если в корзине указаны даты
    for item in cart:
        if 'date' in item:
            await book_slot(item['id'], item['date'], m.from_user.id)

    await clear_cart_db(m.from_user.id)

    items = "\n".join(f"• {i['name']} — {i['price']}$" + (f" (дата: {i['date']})" if 'date' in i else "") for i in cart)
    report = (f"🟢 НОВАЯ ОПЛАЧЕННАЯ ЗАЯВКА #{order_id}\n"
              f"👤 @{username}\n"
              f"📦 Состав:\n{items}\n"
              f"💰 Сумма: {total}$\n"
              f"💵 Бюджет: {budget}$\n"
              f"📞 Контакт: {contact}")

    for aid in ADMIN_IDS:
        try:
            await m.bot.send_message(aid, report)
        except: pass

    if ORDER_CHANNEL_ID:
        try:
            await m.bot.send_message(ORDER_CHANNEL_ID, report)
        except Exception as e:
            print(f"Не удалось отправить уведомление в канал {ORDER_CHANNEL_ID}: {e}")

    await m.answer(ORDER_SUCCESS.format(order_id=order_id, total=total),
                   reply_markup=get_main_keyboard(m.from_user.id))
    await state.clear()

@router.callback_query(F.data == "cancel_add_channel", OrderForm.waiting_for_deposit_amount)
@router.callback_query(F.data == "cancel_add_channel", OrderForm.waiting_for_budget)
async def cancel_checkout(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Оформление отменено", reply_markup=get_main_keyboard(cb.from_user.id))
    await cb.answer()
