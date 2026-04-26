from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import (
    get_user_balance, save_order, update_order_status,
    check_daily_order_limit, get_or_create_user, debit_balance
)
from states import OrderForm
from texts import CART_EMPTY, DAILY_LIMIT, NO_FUNDS, ORDER_SUCCESS
from keyboards import get_cart_keyboard, get_main_keyboard
from config import ADMIN_IDS

router = Router()

# ================= КОРЗИНА =================
user_carts = {}

def get_cart(uid):
    return user_carts.setdefault(uid, [])

def save_cart(uid, cart):
    user_carts[uid] = cart


# ================= ПРОСМОТР =================
@router.message(F.text == "🛒 Корзина")
async def cart(m: Message):
    c = get_cart(m.from_user.id)

    if not c:
        await m.answer(CART_EMPTY)
        return

    total = sum(i['price'] for i in c)
    items = "\n".join(f"{i+1}. {x['name']} — {x['price']}$" for i, x in enumerate(c))

    await m.answer(
        f"🛒 Ваша корзина:\n\n{items}\n\nИтого: {total}$",
        reply_markup=get_cart_keyboard(c)
    )


# ================= ОЧИСТКА =================
@router.callback_query(F.data == "clear_cart")
async def clear_cart(cb: CallbackQuery):
    user_carts[cb.from_user.id] = []
    await cb.answer("🗑 Корзина очищена")
    await cb.message.delete()
    await cb.message.answer(CART_EMPTY, reply_markup=get_main_keyboard(cb.from_user.id))


# ================= УДАЛЕНИЕ =================
@router.callback_query(F.data.startswith("remove_"))
async def ask_remove(cb: CallbackQuery):
    idx = int(cb.data.split("_")[1])
    cart = get_cart(cb.from_user.id)

    if idx >= len(cart):
        await cb.answer("Товар не найден", True)
        return

    item = cart[idx]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_remove_{idx}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cart_cancel")]
    ])

    await cb.message.edit_text(f"Удалить «{item['name']}»?", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("confirm_remove_"))
async def confirm_remove(cb: CallbackQuery):
    idx = int(cb.data.split("_")[2])
    cart = get_cart(cb.from_user.id)

    if idx < len(cart):
        removed = cart.pop(idx)
        save_cart(cb.from_user.id, cart)
        await cb.answer(f"❌ {removed['name']} удалён")
    else:
        await cb.answer("Уже удалён", True)

    if not cart:
        await cb.message.delete()
        await cb.message.answer(CART_EMPTY, reply_markup=get_main_keyboard(cb.from_user.id))
        return

    total = sum(i['price'] for i in cart)
    items = "\n".join(f"{i+1}. {x['name']} — {x['price']}$" for i, x in enumerate(cart))

    await cb.message.edit_text(
        f"🛒 Ваша корзина:\n\n{items}\n\nИтого: {total}$",
        reply_markup=get_cart_keyboard(cart)
    )


# ================= ОФОРМЛЕНИЕ =================
@router.callback_query(F.data == "checkout")
async def checkout(cb: CallbackQuery, state: FSMContext):
    cart = get_cart(cb.from_user.id)

    if not cart:
        await cb.message.edit_text(CART_EMPTY, reply_markup=get_main_keyboard(cb.from_user.id))
        await cb.answer()
        return

    total = sum(i['price'] for i in cart)

    await state.update_data(cart=cart, total=total)
    await cb.message.edit_text(
        f"💳 Сумма: {total}$\nВведите бюджет (≥ сумма):"
    )
    await state.set_state(OrderForm.waiting_for_budget)
    await cb.answer()


# ================= БЮДЖЕТ =================
@router.message(OrderForm.waiting_for_budget)
async def budget_step(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите число")
        return

    budget = int(m.text)
    data = await state.get_data()

    if budget < data['total']:
        await m.answer(f"Минимум: {data['total']}$")
        return

    await state.update_data(budget=budget)
    await m.answer("Введите контакт (@username):")
    await state.set_state(OrderForm.waiting_for_contact)


# ================= ЗАКАЗ =================
@router.message(OrderForm.waiting_for_contact)
async def finish_order(m: Message, state: FSMContext):
    data = await state.get_data()

    cart = data['cart']
    total = data['total']
    budget = data['budget']
    contact = m.text.strip()
    username = m.from_user.username or "не указан"

    # лимит
    if not await check_daily_order_limit(m.from_user.id):
        await m.answer("❌ Достигнут дневной лимит")
        await state.clear()
        return

    # баланс
    balance = await get_user_balance(m.from_user.id)
    if balance < total:
        await m.answer(NO_FUNDS.format(balance=balance, total=total))
        await state.clear()
        return

    # создаём заказ
    order_id = await save_order(
        m.from_user.id, username, cart, total, budget, contact, status='оплачена'
    )

    # списываем
    if not await debit_balance(m.from_user.id, total, order_id):
        await update_order_status(order_id, 'отменена')
        await m.answer("Ошибка оплаты")
        await state.clear()
        return

    # уведомление админу
    items = "\n".join(f"• {i['name']} — {i['price']}$" for i in cart)

    text = (
        f"🟢 Заказ #{order_id}\n"
        f"👤 @{username}\n\n{items}\n\n"
        f"💰 {total}$ | Бюджет {budget}$\n"
        f"📞 {contact}"
    )

    for aid in ADMIN_IDS:
        try:
            await m.bot.send_message(aid, text)
        except Exception as e:
            print("ADMIN SEND ERROR:", e)

    user_carts[m.from_user.id] = []

    await m.answer(
        ORDER_SUCCESS.format(order_id=order_id, total=total),
        reply_markup=get_main_keyboard(m.from_user.id)
    )

    await state.clear()
