from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import (get_user_balance, save_order, update_order_status,
                      check_daily_order_limit, get_or_create_user, debit_balance)
from states import OrderForm
from texts import CART_EMPTY, DAILY_LIMIT, NO_FUNDS, ORDER_SUCCESS
from keyboards import get_cart_keyboard, get_main_keyboard
from config import ADMIN_IDS

router = Router()

# Корзина
user_carts = {}

def get_cart(uid):
    if uid not in user_carts:
        user_carts[uid] = []
    return user_carts[uid]

def save_cart(uid, cart):
    user_carts[uid] = cart

@router.message(F.text == "🛒 Корзина")
async def cart(m: Message):
    c = get_cart(m.from_user.id)
    if not c:
        await m.answer(CART_EMPTY)
        return
    total = sum(i['price'] for i in c)
    items_str = "\n".join(f"{idx+1}. {i['name']} — {i['price']}$" for idx,i in enumerate(c))
    await m.answer(f"🛒 Ваша корзина:\n\n{items_str}\n\nИтого: {total}$", reply_markup=get_cart_keyboard(c))

@router.callback_query(F.data == "clear_cart")
async def clear_cart(cb: CallbackQuery):
    user_carts[cb.from_user.id] = []
    await cb.answer("🗑 Корзина очищена", False)
    await cb.message.delete()
    await cb.message.answer(CART_EMPTY, reply_markup=get_main_keyboard(cb.from_user.id))

@router.callback_query(F.data.startswith("remove_"))
async def ask_remove_item(cb: CallbackQuery):
    idx = int(cb.data.split("_")[1])
    cart = get_cart(cb.from_user.id)
    if 0 <= idx < len(cart):
        item = cart[idx]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_remove_{idx}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cart_cancel")]
        ])
        await cb.message.edit_text(
            f"Удалить «{item['name']}» из корзины?",
            reply_markup=kb
        )
    else:
        await cb.answer("Товар не найден", show_alert=True)
    await cb.answer()

@router.callback_query(F.data.startswith("confirm_remove_"))
async def confirm_remove(cb: CallbackQuery):
    idx = int(cb.data.split("_")[2])
    cart = get_cart(cb.from_user.id)
    if 0 <= idx < len(cart):
        removed = cart.pop(idx)
        save_cart(cb.from_user.id, cart)
        await cb.answer(f"❌ {removed['name']} удалён", show_alert=False)
    else:
        await cb.answer("Ошибка: товар уже не существует", show_alert=True)
    if not cart:
        await cb.message.delete()
        await cb.message.answer(CART_EMPTY, reply_markup=get_main_keyboard(cb.from_user.id))
    else:
        total = sum(i['price'] for i in cart)
        items_str = "\n".join(f"{i+1}. {item['name']} — {item['price']}$" for i,item in enumerate(cart))
        await cb.message.edit_text(
            f"🛒 Ваша корзина:\n\n{items_str}\n\nИтого: {total}$",
            reply_markup=get_cart_keyboard(cart)
        )
    await cb.answer()

@router.callback_query(F.data == "cart_cancel")
async def cart_cancel(cb: CallbackQuery):
    cart = get_cart(cb.from_user.id)
    if not cart:
        await cb.message.delete()
        await cb.message.answer(CART_EMPTY, reply_markup=get_main_keyboard(cb.from_user.id))
        await cb.answer()
        return
    total = sum(i['price'] for i in cart)
    items_str = "\n".join(f"{i+1}. {item['name']} — {item['price']}$" for i,item in enumerate(cart))
    await cb.message.edit_text(
        f"🛒 Ваша корзина:\n\n{items_str}\n\nИтого: {total}$",
        reply_markup=get_cart_keyboard(cart)
    )
    await cb.answer()

@router.callback_query(F.data == "checkout")
async def checkout_cb(cb: CallbackQuery, state: FSMContext):
    cart = get_cart(cb.from_user.id)
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
async def budg(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите число")
        return
    budget = int(m.text)
    d = await state.get_data()
    total = d.get("total",0)
    if budget < total:
        await m.answer(f"Бюджет ({budget}$) меньше суммы ({total}$). Введите {total}$ или больше:")
        return
    await state.update_data(budget=budget)
    await m.answer("Напишите ваш Telegram username (например, @username) или другой контакт:")
    await state.set_state(OrderForm.waiting_for_contact)

@router.message(OrderForm.waiting_for_contact)
async def cont(m: Message, state: FSMContext):
    d = await state.get_data()
    cart = d.get("cart",[])
    total = d.get("total",0)
    budget = d.get("budget",0)
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
        await m.answer(NO_FUNDS.format(balance=balance, total=total))
        await state.clear()
        return

    order_id = await save_order(m.from_user.id, username, cart, total, budget, contact, status='оплачена')
    success = await debit_balance(m.from_user.id, total, order_id, description=f"Оплата заказа #{order_id}")
    if not success:
        await update_order_status(order_id, 'отменена')
        await m.answer("Не удалось списать средства. Заказ отменён. Обратитесь в поддержку.")
        await state.clear()
        return

    items = "\n".join(f"• {i['name']} — {i['price']}$" for i in cart)
    report = f"🟢 НОВАЯ ОПЛАЧЕННАЯ ЗАЯВКА #{order_id}\n👤 @{username}\n📦 Состав:\n{items}\n💰 Сумма: {total}$\n💵 Бюджет: {budget}$\n📞 Контакт: {contact}"
    for aid in ADMIN_IDS:
        try:
            await m.bot.send_message(aid, report)
        except: pass
    user_carts[m.from_user.id] = []
    await m.answer(ORDER_SUCCESS.format(order_id=order_id, total=total),
                   reply_markup=get_main_keyboard(m.from_user.id))
    await state.clear()
