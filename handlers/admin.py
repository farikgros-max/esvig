import os, asyncio, json, logging, re, time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter

from database import (get_all_channels, add_channel, delete_channel, update_channel,
                      toggle_channel_active,
                      get_orders, get_order_by_id, update_order_status, return_balance,
                      clear_non_successful_orders, clear_all_orders,
                      get_all_categories, add_category, delete_category, get_category_by_id,
                      get_or_create_user, update_user_balance, debit_balance, get_user_balance,
                      get_top_channels, get_top_buyers, get_daily_revenue, backup_database,
                      get_all_user_ids,
                      create_seller_application, get_seller_applications,
                      approve_seller_application, reject_seller_application,
                      get_seller_application_by_id, update_seller_application,
                      _load_channels_from_db,
                      get_uncategorized_channels, get_order_stats, get_channel_count, get_weekly_orders,
                      release_slot, copy_slots_to_new_channel, get_catalog_channel_id_by_url,
                      refund_cancelled_order)
from states import (AddChannelStates, EditChannelStates, AddCategoryStates,
                    AdminBalanceStates, MassAddStates, QuickAddStates)
from keyboards import (get_admin_keyboard, get_admin_channels_menu_keyboard,
                       get_admin_orders_menu_keyboard,
                       get_admin_list_keyboard, get_admin_remove_keyboard,
                       get_admin_orders_keyboard, get_edit_channel_keyboard, get_stats_keyboard,
                       get_categories_admin_keyboard, get_category_actions_keyboard,
                       get_category_selection_keyboard, cancel_keyboard, get_main_keyboard,
                       get_admin_categories_keyboard, get_confirm_delete_category_keyboard)
from config import ADMIN_IDS, ORDER_CHANNEL_ID

router = Router()
admin_logger = logging.getLogger('admin_actions')
admin_logger.setLevel(logging.INFO)
fh = logging.FileHandler('admin_actions.log')
fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
admin_logger.addHandler(fh)

class AdminSupportStates(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_broadcast_confirm = State()

# ---------- Фоновая задача обновления подписчиков раз в сутки ----------
async def daily_subscriber_update(bot):
    while True:
        await asyncio.sleep(86400)
        try:
            channels = await get_all_channels()
            for cid, info in channels.items():
                url = info.get('url', '')
                match = re.match(r'(?:https?://)?t(?:elegram)?\.me/(?:joinchat/)?([a-zA-Z0-9_]+)', url)
                if not match:
                    continue
                username = match.group(1)
                try:
                    chat = await bot.get_chat(f"@{username}" if not username.startswith("@") else username)
                    new_subs = await bot.get_chat_member_count(chat.id)
                    await update_channel(cid, subs=new_subs)
                    await asyncio.sleep(0.3)
                except Exception as e:
                    print(f"Auto update failed for {url}: {e}")
            await _load_channels_from_db()
            print("Daily subscriber update completed.")
        except Exception as e:
            print(f"Daily subscriber update error: {e}")

# ================== НАВИГАЦИЯ АДМИНКИ ==================
@router.message(F.text == "🔑 Админ‑панель")
async def admin_panel_msg(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    await m.answer("👑 Админ‑панель", reply_markup=get_admin_keyboard())

@router.callback_query(F.data == "admin_back")
async def adm_back(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        return
    await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
    await cb.answer()

@router.callback_query(F.data == "admin_channels_menu")
async def admin_channels_menu(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        return
    await cb.message.edit_text("📋 Управление каналами:", reply_markup=get_admin_channels_menu_keyboard())
    await cb.answer()

@router.callback_query(F.data == "admin_back_to_channels")
async def back_to_channels_menu(cb: CallbackQuery):
    await admin_channels_menu(cb)

@router.callback_query(F.data == "admin_orders_menu")
async def admin_orders_menu(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        return
    await cb.message.edit_text("📋 Заявки:", reply_markup=get_admin_orders_menu_keyboard())
    await cb.answer()

@router.callback_query(F.data == "admin_back_to_orders")
async def back_to_orders_menu(cb: CallbackQuery):
    await admin_orders_menu(cb)

# ================== СТАТИСТИКА ==================
@router.callback_query(F.data == "admin_stats")
async def admin_stats_cb(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    try:
        tot_ord, tot_sum, stat_rows = await get_order_stats()
        chan_cnt = await get_channel_count()
        week_rows = await get_weekly_orders(7)

        status_lines = "\n".join(
            f"{'🟡' if s['status']=='в обработке' else '🟢' if s['status']=='оплачена' else '✅' if s['status']=='выполнена' else '❌'} {s['status']}: {s['count']}"
            for s in stat_rows
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
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("⛔ Нет доступа", show_alert=True)
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
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("⛔ Нет доступа", show_alert=True)
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
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("⛔ Нет доступа", show_alert=True)
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

# ================== ЭКСПОРТ ЗАКАЗОВ (ЕДИНСТВЕННЫЙ ОБРАБОТЧИК) ==================
@router.callback_query(F.data == "export_orders")
async def export_orders_cb(cb: CallbackQuery):
    print(f"[EXPORT] Callback from user {cb.from_user.id}, ADMIN_IDS={ADMIN_IDS}")
    if cb.from_user.id not in ADMIN_IDS:
        print("[EXPORT] Access denied")
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    print("[EXPORT] Access granted, starting export...")
    await export_orders(cb.message, cb.from_user.id)
    await cb.answer()

@router.message(F.from_user.id.in_(ADMIN_IDS), F.text == "/export")
async def export_cmd(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        await m.answer("⛔ Нет доступа")
        return
    await export_orders(m, m.from_user.id)

async def export_orders(message: Message, user_id: int):
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Нет доступа")
        return
    await message.answer("⏳ Формирую отчёт...")
    try:
        orders = await get_orders(limit=10000)
        if not orders:
            await message.answer("Заказов нет.")
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
        await message.answer_document(file, caption="📋 Все заказы")
        os.remove(filename)
        admin_logger.info(f"Admin {user_id}: exported orders")
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print(err)
        await message.answer(f"❌ Ошибка экспорта:\n{err[:1500]}")


@router.callback_query(F.data.startswith("set_status_"))
async def set_st(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    parts = cb.data.split("_")
    oid = int(parts[2])
    new_st = "_".join(parts[3:])
    order = await get_order_by_id(oid)
    if not order:
        await cb.answer("Заявка не найдена", show_alert=True)
        return

    if new_st == 'отменена':
        refunded = await refund_cancelled_order(order)
        if refunded:
            try:
                await cb.bot.send_message(
                    order['user_id'],
                    f"📢 Ваша заявка #{oid} была отменена администратором. Средства возвращены на баланс.",
                )
            except Exception:
                pass
            for aid in ADMIN_IDS:
                if aid != cb.from_user.id:
                    try:
                        await cb.bot.send_message(
                            aid, f"❌ Админ отменил заявку #{oid} (возврат {order['total']}$)"
                        )
                    except Exception:
                        pass

    await update_order_status(oid, new_st)
    await cb.answer(f"✅ Статус заявки #{oid} изменён на {new_st}", False)
    if new_st != 'отменена':
        try:
            await cb.bot.send_message(order['user_id'], f"📢 Статус вашей заявки #{oid} изменён на: {new_st}")
        except: pass
    ords = await get_orders(20)
    await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))
