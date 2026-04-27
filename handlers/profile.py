from aiogram import Router, F
from aiogram.types import Message

from database import (
    get_or_create_user,
    get_orders_by_user,
    get_user_balance,
    update_user_balance,
    debit_balance,
    get_order_by_id,
    update_order_status,
    return_balance
)

router = Router()


# ---------------- PROFILE ----------------

@router.message(F.text == "👤 Мой профиль")
async def profile(m: Message):
    user = await get_or_create_user(m.from_user.id, m.from_user.username)

    balance = await get_user_balance(m.from_user.id)
    orders = await get_orders_by_user(m.from_user.id)

    text = (
        f"👤 Профиль\n\n"
        f"🆔 ID: {m.from_user.id}\n"
        f"💰 Баланс: {balance}$\n"
        f"📦 Заказов: {len(orders)}\n"
        f"📛 Username: @{m.from_user.username if m.from_user.username else 'нет'}"
    )

    await m.answer(text)


# ---------------- ORDERS LIST ----------------

@router.message(F.text == "📦 Мои заказы")
async def my_orders(m: Message):
    orders = await get_orders_by_user(m.from_user.id)

    if not orders:
        await m.answer("У вас нет заказов")
        return

    text = "📦 Ваши заказы:\n\n"

    for o in orders[:10]:
        text += (
            f"#{o['id']} | {o['total']}$ | {o['status']}\n"
        )

    await m.answer(text)


# ---------------- SINGLE ORDER ----------------

@router.message(F.text.startswith("заказ "))
async def order_info(m: Message):
    try:
        order_id = int(m.text.split()[1])
    except:
        await m.answer("Неверный формат. Пример: заказ 1")
        return

    order = await get_order_by_id(order_id)

    if not order:
        await m.answer("Заказ не найден")
        return

    text = (
        f"📦 Заказ #{order['id']}\n"
        f"👤 User: {order['username']}\n"
        f"💰 Сумма: {order['total']}$\n"
        f"📊 Статус: {order['status']}\n"
        f"📞 Контакт: {order['contact']}"
    )

    await m.answer(text)
