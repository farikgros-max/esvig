import os
import asyncio
import time
import asyncpg
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import (get_all_channels, add_channel, delete_channel, update_channel,
                      get_orders, get_order_by_id, update_order_status, return_balance,
                      clear_non_successful_orders, clear_all_orders,
                      get_all_categories, add_category, delete_category, get_category_by_id,
                      get_or_create_user, update_user_balance, debit_balance, get_user_balance)
from states import (AddChannelStates, EditChannelStates, AddCategoryStates,
                    AdminBalanceStates)
from keyboards import (get_admin_keyboard, get_admin_list_keyboard, get_admin_remove_keyboard,
                       get_admin_orders_keyboard, get_edit_channel_keyboard, get_stats_keyboard,
                       get_categories_admin_keyboard, get_category_actions_keyboard,
                       get_category_selection_keyboard, cancel_keyboard, get_main_keyboard)
from config import ADMIN_IDS

router = Router()

# ========== Админ‑панель (полная) ==========
@router.callback_query(F.data == "cancel_add_channel")
async def cancel_add_channel(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", show_alert=True); return
    await state.clear()
    await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
    await cb.answer()

@router.callback_query(F.data == "admin_back")
async def adm_back(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
    await cb.answer()

# ---------- Управление категориями ----------
@router.callback_query(F.data == "admin_categories")
async def admin_categories_menu(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    await cb.message.edit_text("🏷 Управление категориями", reply_markup=await get_categories_admin_keyboard(get_all_categories))
    await cb.answer()

@router.callback_query(F.data == "admin_add_category")
async def admin_add_category_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    await cb.message.edit_text("Введите **короткое имя** категории (на английском, например 'mining'):", parse_mode="Markdown")
    await state.set_state(AddCategoryStates.waiting_for_name)
    await cb.answer()

@router.message(AddCategoryStates.waiting_for_name)
async def add_cat_name(m: Message, state: FSMContext):
    name = m.text.strip()
    if not name:
        await m.answer("Имя не может быть пустым")
        return
    await state.update_data(name=name)
    await m.answer("Введите отображаемое название категории (например 'Майнинг'):")
    await state.set_state(AddCategoryStates.waiting_for_display_name)

@router.message(AddCategoryStates.waiting_for_display_name)
async def add_cat_display(m: Message, state: FSMContext):
    data = await state.get_data()
    name = data['name']
    display = m.text.strip()
    if not display:
        await m.answer("Название не может быть пустым")
        return
    await add_category(name, display)
    await m.answer(f"✅ Категория '{display}' добавлена", reply_markup=get_admin_keyboard())
    await state.clear()

@router.callback_query(F.data.startswith("admin_category_"))
async def admin_category_detail(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    cat_id = int(cb.data.split("_")[2])
    cat = await get_category_by_id(cat_id)
    if not cat:
        await cb.answer("Категория не найдена", True)
        return
    await cb.message.edit_text(f"Категория: {cat['display_name']} (id={cat_id}, имя={cat['name']})", reply_markup=get_category_actions_keyboard(cat_id))
    await cb.answer()

@router.callback_query(F.data.startswith("admin_del_category_"))
async def admin_del_category(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    cat_id = int(cb.data.split("_")[3])
    await delete_category(cat_id)
    await cb.answer("Категория удалена", False)
    await admin_categories_menu(cb)

# ---------- Список каналов и действия с ними ----------
@router.callback_query(F.data == "admin_list")
async def adm_list(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    ch = await get_all_channels()
    if len(ch) < 2:
        await asyncio.sleep(0.2)
        ch = await get_all_channels()
    print(f"[DEBUG] admin_list: получено каналов = {len(ch)}")
    if not ch:
        await cb.message.delete()
        await cb.message.answer("Список каналов пуст", reply_markup=get_main_keyboard(cb.from_user.id))
        await cb.answer()
        return
    await cb.message.edit_text("📋 Список каналов\nНажмите на канал для подробностей:", reply_markup=get_admin_list_keyboard(ch))
    await cb.answer()

@router.callback_query(F.data.startswith("admin_view_"))
async def adm_view_chan(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    ch = await get_all_channels()
    cid = cb.data.replace("admin_view_", "")
    info = ch.get(cid)
    if not info: await cb.answer("Канал не найден", True); return
    cat_name = ""
    if info.get('category_id'):
        cat = await get_category_by_id(info['category_id'])
        if cat:
            cat_name = cat['display_name']
    txt = f"📌 {info['name']}\n🔗 {info['url']}\n💰 {info['price']}$\n👥 {info['subscribers']} подп.\n📝 {info.get('description','Нет описания')}"
    if cat_name:
        txt += f"\n🏷 {cat_name}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_channel_{cid}")],[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_list")]])
    await cb.message.edit_text(txt, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("edit_channel_"))
async def edit_chan_menu(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    cid = cb.data.replace("edit_channel_", "")
    ch = await get_all_channels()
    if cid not in ch: await cb.answer("Канал не найден", True); return
    await cb.message.edit_text(f"Редактирование канала {ch[cid]['name']}\nВыберите, что изменить:", reply_markup=get_edit_channel_keyboard(cid))
    await cb.answer()

@router.callback_query(F.data.startswith("edit_") & ~F.data.startswith("edit_channel_"))
async def edit_field(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    parts = cb.data.split("_",2)
    if len(parts)<3: await cb.answer("Ошибка", True); return
    cid, field = parts[1], parts[2]
    ch = await get_all_channels()
    if cid not in ch: await cb.answer("Канал не найден", True); return
    await state.update_data(ch_id=cid, field=field)
    if field == 'category':
        await cb.message.edit_text("Выберите новую категорию:", reply_markup=await get_category_selection_keyboard(get_all_categories, f"edit_chan_cat_{cid}"))
        await state.set_state(EditChannelStates.waiting_for_category)
    else:
        prompts = {'name':'Введите новое название:','price':'Введите новую цену (число):','subscribers':'Введите новое количество подписчиков (число):','url':'Введите новую ссылку (https://t.me/...):','description':'Введите новое описание:'}
        await cb.message.edit_text(prompts.get(field, "Введите значение:"))
        if field=='name': await state.set_state(EditChannelStates.waiting_for_name)
        elif field=='price': await state.set_state(EditChannelStates.waiting_for_price)
        elif field=='subscribers': await state.set_state(EditChannelStates.waiting_for_subscribers)
        elif field=='url': await state.set_state(EditChannelStates.waiting_for_url)
        elif field=='description': await state.set_state(EditChannelStates.waiting_for_description)
    await cb.answer()

@router.callback_query(F.data.startswith("edit_chan_cat_"))
async def edit_channel_category_selected(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    parts = cb.data.split("_")
    cid = parts[3]
    cat_id = int(parts[4])
    await update_channel(cid, category_id=cat_id)
    await cb.answer("Категория обновлена", False)
    await adm_view_chan(cb)
    await state.clear()

@router.message(EditChannelStates.waiting_for_name)
async def e_name(m: Message, state: FSMContext):
    d = await state.get_data()
    await update_channel(d['ch_id'], name=m.text)
    await m.answer(f"✅ Название изменено на {m.text}")
    await state.clear()

@router.message(EditChannelStates.waiting_for_price)
async def e_price(m: Message, state: FSMContext):
    if not m.text.isdigit(): await m.answer("Введите число"); return
    d = await state.get_data()
    await update_channel(d['ch_id'], price=int(m.text))
    await m.answer(f"✅ Цена изменена на {m.text}$")
    await state.clear()

@router.message(EditChannelStates.waiting_for_subscribers)
async def e_subs(m: Message, state: FSMContext):
    if not m.text.isdigit(): await m.answer("Введите число"); return
    d = await state.get_data()
    await update_channel(d['ch_id'], subs=int(m.text))
    await m.answer(f"✅ Количество подписчиков изменено на {m.text}")
    await state.clear()

@router.message(EditChannelStates.waiting_for_url)
async def e_url(m: Message, state: FSMContext):
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Ссылка должна начинаться с https://t.me/")
        return
    d = await state.get_data()
    await update_channel(d['ch_id'], url=url)
    await m.answer(f"✅ Ссылка изменена на {url}")
    await state.clear()

@router.message(EditChannelStates.waiting_for_description)
async def e_desc(m: Message, state: FSMContext):
    d = await state.get_data()
    await update_channel(d['ch_id'], desc=m.text)
    await m.answer("✅ Описание изменено")
    await state.clear()

# ---------- Удаление канала ----------
@router.callback_query(F.data == "admin_remove")
async def adm_rem_menu(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    ch = await get_all_channels()
    if not ch:
        await cb.message.delete()
        await cb.message.answer("Нет каналов для удаления", reply_markup=get_main_keyboard(cb.from_user.id))
        await cb.answer()
        return
    await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard(ch))
    await cb.answer()

@router.callback_query(F.data.startswith("admin_del_"))
async def adm_del(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    cid = cb.data.replace("admin_del_", "")
    ch = await get_all_channels()
    if cid in ch:
        name = ch[cid]['name']
        await delete_channel(cid)
        await cb.answer(f"✅ Канал {name} удалён", False)
        new_ch = await get_all_channels()
        if not new_ch:
            await cb.message.delete()
            await cb.message.answer("Все каналы удалены", reply_markup=get_main_keyboard(cb.from_user.id))
        else:
            await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard(new_ch))
    else:
        await cb.answer("Канал не найден", True)

# ---------- Добавление канала ----------
@router.callback_query(F.data == "admin_add")
async def adm_add_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Нет прав", show_alert=True)
        return
    await cb.message.edit_text("➕ Выберите категорию для нового канала:", reply_markup=await get_category_selection_keyboard(get_all_categories, "add_chan_cat"))
    await state.set_state(AddChannelStates.waiting_for_category)
    await cb.answer()

@router.callback_query(F.data.startswith("add_chan_cat_"), AddChannelStates.waiting_for_category)
async def add_channel_category_chosen(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Нет прав", show_alert=True)
        return
    cat_id = int(cb.data.split("_")[3])
    await state.update_data(category_id=cat_id)
    await cb.message.edit_text("Введите название канала:", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_name)
    await cb.answer()

@router.message(AddChannelStates.waiting_for_name)
async def a_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer("Введите цену (число):", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_price)

@router.message(AddChannelStates.waiting_for_price)
async def a_price(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите число")
        return
    await state.update_data(price=int(m.text))
    await m.answer("Введите количество подписчиков (число):", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_subscribers)

@router.message(AddChannelStates.waiting_for_subscribers)
async def a_subs(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите число")
        return
    await state.update_data(subscribers=int(m.text))
    await m.answer("Введите ссылку (https://t.me/...):", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_url)

@router.message(AddChannelStates.waiting_for_url)
async def a_url(m: Message, state: FSMContext):
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Ссылка должна начинаться с https://t.me/")
        return
    await state.update_data(url=url)
    await m.answer("Введите описание канала:", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_description)

@router.message(AddChannelStates.waiting_for_description)
async def a_desc(m: Message, state: FSMContext):
    await state.update_data(description=m.text)
    data = await state.get_data()
    new_id = f"channel_{int(time.time())}"
    cat_id = data['category_id']
    await add_channel(new_id, data['name'], data['price'], data['subscribers'], data['url'], data['description'], cat_id)
    cat = await get_category_by_id(cat_id)
    cat_name = cat['display_name'] if cat else ""
    await m.answer(f"✅ Канал {data['name']} добавлен в категорию {cat_name}!", reply_markup=get_admin_keyboard())
    await state.clear()

# ---------- Заявки (просмотр и изменение статуса) ----------
@router.callback_query(F.data == "admin_orders")
async def adm_orders(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    ords = await get_orders(20)
    if not ords: await cb.message.edit_text("Нет заявок", reply_markup=get_main_keyboard(cb.from_user.id)); await cb.answer(); return
    await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))
    await cb.answer()

@router.callback_query(F.data.startswith("admin_order_"))
async def adm_view_order(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    oid = int(cb.data.split("_")[2])
    ordd = await get_order_by_id(oid)
    if not ordd: await cb.answer("Заявка не найдена", True); return
    em = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌'}.get(ordd['status'],'⚪')
    txt = f"📄 Заявка #{ordd['id']}\n👤 @{ordd['username']}\n💰 Сумма: {ordd['total']}$\n📌 Статус: {em} {ordd['status']}\n\nВыберите новый статус:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟡 В обработке", callback_data=f"set_status_{oid}_в обработке")],
        [InlineKeyboardButton(text="🟢 Оплачена", callback_data=f"set_status_{oid}_оплачена")],
        [InlineKeyboardButton(text="✅ Выполнена", callback_data=f"set_status_{oid}_выполнена")],
        [InlineKeyboardButton(text="❌ Отменена", callback_data=f"set_status_{oid}_отменена")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_orders")]
    ])
    await cb.message.edit_text(txt, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("set_status_"))
async def set_st(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    parts = cb.data.split("_")
    oid = int(parts[2])
    new_st = "_".join(parts[3:])
    order = await get_order_by_id(oid)
    if not order: await cb.answer("Заявка не найдена", True); return

    old_status = order['status']
    if new_st == 'отменена' and old_status == 'оплачена':
        await return_balance(order['user_id'], order['total'], oid, f"Возврат за отмену заказа #{oid} админом")
        try:
            await cb.bot.send_message(order['user_id'], f"📢 Ваша заявка #{oid} была отменена администратором. Средства возвращены на баланс.")
        except: pass
        for aid in ADMIN_IDS:
            if aid != cb.from_user.id:
                try:
                    await cb.bot.send_message(aid, f"❌ Админ отменил заявку #{oid} (возврат {order['total']}$)")
                except: pass

    await update_order_status(oid, new_st)
    await cb.answer(f"✅ Статус заявки #{oid} изменён на {new_st}", False)
    try:
        await cb.bot.send_message(order['user_id'], f"📢 Статус вашей заявки #{oid} изменён на: {new_st}")
    except: pass
    ords = await get_orders(20)
    await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))

# ---------- Статистика ----------
@router.callback_query(F.data == "admin_stats")
async def admin_stats_cb(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Нет прав", show_alert=True)
        return
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    tot_ord, tot_sum = await conn.fetchrow("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders")
    stat = await conn.fetch("SELECT status, COUNT(*) FROM orders GROUP BY status")
    chan_cnt = await conn.fetchval("SELECT COUNT(*) FROM channels")
    week = await conn.fetch("SELECT DATE(created_at), COUNT(*), SUM(total) FROM orders WHERE created_at >= CURRENT_DATE - INTERVAL '7 days' GROUP BY DATE(created_at) ORDER BY DATE(created_at) ASC")
    await conn.close()
    status_lines = "\n".join(f"{'🟡' if s=='в обработке' else '🟢' if s=='оплачена' else '✅' if s=='выполнена' else '❌'} {s}: {c}" for s, c in stat)
    week_lines = "\n".join(f"{d}: {cnt} заявок, {s or 0}$" for d, cnt, s in week) if week else ""
    txt = f"📊 Статистика ESVIG Service\n\n📦 Всего заявок: {tot_ord}\n💰 Общая сумма: {tot_sum or 0}$\n📋 Каналов: {chan_cnt}\n\n🔄 По статусам:\n{status_lines}\n"
    if week_lines:
        txt += f"\n📅 Последние 7 дней:\n{week_lines}"
    await cb.message.edit_text(txt, reply_markup=get_stats_keyboard())
    await cb.answer()

# ---------- Ручное изменение баланса ----------
@router.callback_query(F.data == "admin_balance")
async def admin_balance_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Нет прав", show_alert=True)
        return
    await cb.message.edit_text("Введите Telegram ID пользователя:", reply_markup=cancel_keyboard())
    await state.set_state(AdminBalanceStates.waiting_for_user_id)
    await cb.answer()

@router.message(AdminBalanceStates.waiting_for_user_id)
async def process_balance_user_id(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите числовой ID")
        return
    target_id = int(m.text)
    await state.update_data(target_id=target_id)
    await m.answer("Введите сумму (положительное – пополнение, отрицательное – списание):", reply_markup=cancel_keyboard())
    await state.set_state(AdminBalanceStates.waiting_for_amount)

@router.message(AdminBalanceStates.waiting_for_amount)
async def process_balance_amount(m: Message, state: FSMContext):
    try:
        amount = int(m.text.strip())
    except ValueError:
        await m.answer("Введите целое число")
        return
    data = await state.get_data()
    target_id = data['target_id']
    await get_or_create_user(target_id)
    if amount >= 0:
        await update_user_balance(target_id, amount, f"Ручное пополнение админом {m.from_user.id}")
        await m.answer(f"✅ Баланс пользователя {target_id} пополнен на {amount}$", reply_markup=get_admin_keyboard())
    else:
        success = await debit_balance(target_id, -amount, None, f"Ручное списание админом {m.from_user.id}")
        if success:
            await m.answer(f"✅ С баланса пользователя {target_id} списано {-amount}$", reply_markup=get_admin_keyboard())
        else:
            bal = await get_user_balance(target_id)
            await m.answer(f"❌ Недостаточно средств. Текущий баланс: {bal}$", reply_markup=get_admin_keyboard())
    await state.clear()

# ---------- Очистка заявок ----------
@router.callback_query(F.data == "confirm_clear_failed")
async def ask_clear_failed(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Нет прав", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, очистить неуспешные", callback_data="clear_failed_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="clear_no")]
    ])
    await cb.message.edit_text("⚠️ Будут удалены все заявки со статусами «в обработке» и «отменена». Оплаченные и выполненные останутся.", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "confirm_clear_all")
async def ask_clear_all(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Нет прав", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, полная очистка", callback_data="clear_all_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="clear_no")]
    ])
    await cb.message.edit_text("⚠️ **Полная очистка**: будут удалены **все** заявки (и у вас, и у покупателей). Это действие необратимо.", reply_markup=kb, parse_mode="Markdown")
    await cb.answer()

@router.callback_query(F.data == "clear_failed_yes")
async def clear_failed(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Нет прав", show_alert=True)
        return
    try:
        await clear_non_successful_orders()
        await cb.message.edit_text("✅ Неуспешные заявки удалены.")
    except Exception as e:
        print(f"Ошибка очистки: {e}")
        await cb.message.edit_text("❌ Ошибка при очистке. Попробуйте позже.")
    await cb.answer()

@router.callback_query(F.data == "clear_all_yes")
async def clear_all(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Нет прав", show_alert=True)
        return
    try:
        await clear_all_orders()
        await cb.message.edit_text("✅ Все заявки удалены.")
    except Exception as e:
        print(f"Ошибка очистки: {e}")
        await cb.message.edit_text("❌ Ошибка при очистке. Попробуйте позже.")
    await cb.answer()

@router.callback_query(F.data == "clear_no")
async def clear_no(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Нет прав", show_alert=True)
        return
    await cb.message.delete()
    await cb.answer("Очистка отменена")
