from aiogram import F, Router
from aiogram.types import CallbackQuery

from database import (
    get_channel_count,
    get_daily_revenue,
    get_order_stats,
    get_top_buyers,
    get_top_channels,
    get_weekly_orders,
)
from keyboards import get_stats_keyboard
from utils import admin_only_callback

router = Router()

@router.callback_query(F.data == "admin_stats")
async def admin_stats_cb(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    try:
        tot_ord, tot_sum, stat_rows = await get_order_stats()
        chan_cnt = await get_channel_count()
        week_rows = await get_weekly_orders(7)

        status_lines = "\n".join(
            f"{'🟡' if s=='в обработке' else '🟢' if s=='оплачена' else '✅' if s=='выполнена' else '❌'} {s}: {c}"
            for s, c in stat_rows
        )
        week_lines = "\n".join(
            f"{d}: {cnt} заявок, {s or 0}$" for d, cnt, s in week_rows
        ) if week_rows else ""

        txt = f"📊 Статистика ESVIG Service\n\n📦 Всего заявок: {tot_ord}\n💰 Общая сумма: {tot_sum or 0}$\n📋 Каналов: {chan_cnt}\n\n🔄 По статусам:\n{status_lines}\n"
        if week_lines:
            txt += f"\n📅 Последние 7 дней:\n{week_lines}"
        await cb.message.edit_text(txt, reply_markup=get_stats_keyboard())
        await cb.answer()
    except Exception as e:
        await cb.answer(f"Ошибка загрузки статистики: {e}", show_alert=True)

@router.callback_query(F.data == "top_channels")
async def top_channels_cb(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    top = await get_top_channels(10)
    if not top:
        await cb.answer("Нет данных о заказах", show_alert=True)
        return
    text = "📈 Топ каналов по заказам:\n\n"
    for i, item in enumerate(top, 1):
        text += f"{i}. {item['name']} — {item['orders']} зак. на {item['total']}$\n"
    await cb.message.edit_text(text, reply_markup=get_stats_keyboard())
    await cb.answer()

@router.callback_query(F.data == "top_buyers")
async def top_buyers_cb(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    buyers = await get_top_buyers(10)
    if not buyers:
        await cb.answer("Нет данных о покупателях", show_alert=True)
        return
    text = "👥 Топ покупателей:\n\n"
    for i, b in enumerate(buyers, 1):
        text += f"{i}. {b['username']} — {b['total_spent']}$ ({b['order_count']} зак.)\n"
    await cb.message.edit_text(text, reply_markup=get_stats_keyboard())
    await cb.answer()

@router.callback_query(F.data == "daily_revenue")
async def daily_revenue_cb(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    revenue = await get_daily_revenue(7)
    if not revenue:
        await cb.answer("Нет данных о доходах", show_alert=True)
        return
    text = "📈 Доходы по дням:\n\n"
    for day in revenue:
        text += f"{day['day']}: {day['orders']} зак., {day['revenue']}$\n"
    await cb.message.edit_text(text, reply_markup=get_stats_keyboard())
    await cb.answer()
