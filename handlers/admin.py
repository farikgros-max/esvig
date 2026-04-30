import os, asyncio, json, logging, re, time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

import asyncpg

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
                      get_seller_application_by_id)
from states import (AddChannelStates, EditChannelStates, AddCategoryStates,
                    AdminBalanceStates, MassAddStates, QuickAddStates)
from keyboards import (get_admin_keyboard, get_admin_channels_menu_keyboard,
                       get_admin_orders_menu_keyboard,
                       get_admin_list_keyboard, get_admin_remove_keyboard,
                       get_admin_orders_keyboard, get_edit_channel_keyboard, get_stats_keyboard,
                       get_categories_admin_keyboard, get_category_actions_keyboard,
                       get_category_selection_keyboard, cancel_keyboard, get_main_keyboard,
                       get_admin_categories_keyboard, get_confirm_delete_category_keyboard)
from config import ADMIN_IDS, ORDER_CHANNEL_ID, DATABASE_URL
from utils import is_admin, admin_only_message, admin_only_callback, log_admin_action

router = Router()
admin_logger = logging.getLogger('admin_actions')
admin_logger.setLevel(logging.INFO)
fh = logging.FileHandler('admin_actions.log')
fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
admin_logger.addHandler(fh)

class AdminSupportStates(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_broadcast_confirm = State()

# ---------- Универсальный сброс любого состояния ----------
@router.message(Command("cancel"))
async def cancel_any_state(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🚫 Действие отменено. Можете начать заново.")

# ================== НАВИГАЦИЯ АДМИНКИ ==================
@router.message(F.text == "🔑 Админ‑панель")
async def admin_panel_msg(m: Message):
    if not await admin_only_message(m):
        return
    await m.answer("👑 Админ‑панель", reply_markup=get_admin_keyboard())

@router.callback_query(F.data == "admin_back")
async def adm_back(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
    await cb.answer()

# ---------- Меню «Каналы» ----------
@router.callback_query(F.data == "admin_channels_menu")
async def admin_channels_menu(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await cb.message.edit_text("📋 Управление каналами:", reply_markup=get_admin_channels_menu_keyboard())
    await cb.answer()

@router.callback_query(F.data == "admin_back_to_channels")
async def back_to_channels_menu(cb: CallbackQuery):
    await admin_channels_menu(cb)

# ---------- Меню «Заявки» ----------
@router.callback_query(F.data == "admin_orders_menu")
async def admin_orders_menu(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await cb.message.edit_text("📋 Заявки:", reply_markup=get_admin_orders_menu_keyboard())
    await cb.answer()

@router.callback_query(F.data == "admin_back_to_orders")
async def back_to_orders_menu(cb: CallbackQuery):
    await admin_orders_menu(cb)

# ---------- Управление категориями ----------
@router.callback_query(F.data == "admin_categories")
async def admin_categories_menu(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await cb.message.edit_text("🏷 Управление категориями", reply_markup=await get_categories_admin_keyboard(get_all_categories))
    await cb.answer()

@router.callback_query(F.data == "admin_add_category")
async def admin_add_category_start(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await cb.message.edit_text("Введите **короткое имя** категории (на английском, например 'mining'):", parse_mode="Markdown")
    await state.set_state(AddCategoryStates.waiting_for_name)
    await cb.answer()

@router.message(AddCategoryStates.waiting_for_name)
async def add_cat_name(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    name = m.text.strip()
    if not name:
        await m.answer("Имя не может быть пустым")
        return
    await state.update_data(name=name)
    await m.answer("Введите отображаемое название категории (например 'Майнинг'):")
    await state.set_state(AddCategoryStates.waiting_for_display_name)

@router.message(AddCategoryStates.waiting_for_display_name)
async def add_cat_display(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    data = await state.get_data()
    name = data['name']
    display = m.text.strip()
    if not display:
        await m.answer("Название не может быть пустым")
        return
    await add_category(name, display)
    log_admin_action(m.from_user.id, f"added category '{name}'")
    await m.answer(f"✅ Категория '{display}' добавлена", reply_markup=get_admin_channels_menu_keyboard())
    await state.clear()

@router.callback_query(F.data.startswith("admin_category_"))
async def admin_category_detail(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cat_id = int(cb.data.split("_")[2])
    cat = await get_category_by_id(cat_id)
    if not cat:
        await cb.answer("Категория не найдена", True)
        return
    await cb.message.edit_text(
        f"Категория: {cat['display_name']} (id={cat_id}, имя={cat['name']})",
        reply_markup=get_category_actions_keyboard(cat_id)
    )
    await cb.answer()

@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def confirm_delete_category(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cat_id = int(cb.data.split("_")[-1])
    cat = await get_category_by_id(cat_id)
    if not cat:
        await cb.answer("Категория не найдена", True)
        return
    await cb.message.edit_text(
        f"Удалить категорию «{cat['display_name']}» и все её каналы?",
        reply_markup=get_confirm_delete_category_keyboard(cat_id)
    )
    await cb.answer()

@router.callback_query(F.data.startswith("exec_delete_category_"))
async def exec_delete_category(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cat_id = int(cb.data.split("_")[-1])
    await delete_category(cat_id)
    log_admin_action(cb.from_user.id, f"deleted category {cat_id}")
    await cb.answer("Категория удалена", False)
    await admin_categories_menu(cb)

# ---------- Список каналов (внутри меню «Каналы») ----------
@router.callback_query(F.data == "admin_list")
async def admin_list_categories(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await cb.message.edit_text("Выберите категорию:", reply_markup=await get_admin_categories_keyboard(get_all_categories))
    await cb.answer()

@router.callback_query(F.data == "admin_cat_all")
async def admin_list_all_channels(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    ch = await get_all_channels()
    if not ch:
        await cb.message.edit_text("Нет каналов.", reply_markup=get_admin_channels_menu_keyboard())
        await cb.answer()
        return
    kb, page, total = get_admin_list_keyboard(ch, 0, category_id="all")
    await cb.message.edit_text(f"📋 Все каналы (страница 1/{total})", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "admin_cat_none")
async def admin_list_uncategorized_channels(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch('SELECT id, name, price, subscribers, url, description, category_id, active FROM channels WHERE category_id IS NULL')
    await conn.close()
    if not rows:
        await cb.message.edit_text("Нет каналов без категории.", reply_markup=get_admin_channels_menu_keyboard())
        await cb.answer()
        return
    ch = {}
    for r in rows:
        ch[r['id']] = {
            "name": r['name'],
            "price": r['price'],
            "subscribers": r['subscribers'],
            "url": r['url'],
            "description": r['description'],
            "category_id": None,
            "active": r['active']
        }
    kb, page, total = get_admin_list_keyboard(ch, 0, category_id="none")
    await cb.message.edit_text(f"📋 Каналы без категории (страница 1/{total})", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("admin_cat_"))
async def admin_list_channels(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cat_id = int(cb.data.split("_")[2])
    ch = await get_all_channels(cat_id)
    if not ch:
        await cb.message.edit_text("В этой категории нет каналов.", reply_markup=get_admin_channels_menu_keyboard())
        await cb.answer()
        return
    kb, page, total = get_admin_list_keyboard(ch, 0, category_id=cat_id)
    await cb.message.edit_text(f"📋 Каналы в категории (страница 1/{total})", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("admin_list_page_"))
async def admin_list_page(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    parts = cb.data.split("_")
    page = int(parts[3])
    cat_id = parts[4]
    if cat_id == "all":
        ch = await get_all_channels()
    elif cat_id == "none":
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch('SELECT id, name, price, subscribers, url, description, category_id, active FROM channels WHERE category_id IS NULL')
        await conn.close()
        ch = {}
        for r in rows:
            ch[r['id']] = {
                "name": r['name'],
                "price": r['price'],
                "subscribers": r['subscribers'],
                "url": r['url'],
                "description": r['description'],
                "category_id": None,
                "active": r['active']
            }
    else:
        ch = await get_all_channels(int(cat_id))
    if not ch:
        await cb.message.edit_text("Нет каналов.", reply_markup=get_admin_channels_menu_keyboard())
        await cb.answer()
        return
    kb, cur, total = get_admin_list_keyboard(ch, page, category_id=cat_id)
    await cb.message.edit_text(f"📋 Каналы (страница {cur+1}/{total})", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "admin_list_back")
async def admin_list_back(cb: CallbackQuery):
    await admin_channels_menu(cb)   # возврат в меню каналов

# ---------- Просмотр канала ----------
@router.callback_query(F.data.startswith("admin_view_"))
async def adm_view_chan(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cid = cb.data.replace("admin_view_", "")
    ch = await get_all_channels()
    info = ch.get(cid)
    if not info:
        await cb.answer("Канал не найден", True)
        return
    cat_name = ""
    if info.get('category_id'):
        cat = await get_category_by_id(info['category_id'])
        if cat:
            cat_name = cat['display_name']
    active = info.get('active', True)
    status_btn = InlineKeyboardButton(
        text="🟢 Активен" if active else "🔴 Скрыт",
        callback_data=f"toggle_active_{cid}"
    )
    txt = f"📌 {info['name']}\n🔗 {info['url']}\n💰 {info['price']}$\n👥 {info['subscribers']} подп.\n📝 {info.get('description','Нет описания')}"
    if cat_name:
        txt += f"\n🏷 {cat_name}"
    txt += f"\n\nСтатус: {'🟢 активен' if active else '🔴 скрыт'}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_channel_{cid}")],
        [status_btn],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_list_back")]
    ])
    await cb.message.edit_text(txt, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("toggle_active_"))
async def toggle_active_cb(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cid = cb.data.replace("toggle_active_", "")
    new_state = await toggle_channel_active(cid)
    log_admin_action(cb.from_user.id, f"toggled channel {cid} active={new_state}")
    await cb.answer(f"Канал теперь {'активен' if new_state else 'скрыт'}", show_alert=False)
    await adm_view_chan(cb)

# ---------- Редактирование канала ----------
@router.callback_query(F.data.startswith("edit_channel_"))
async def edit_chan_menu(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cid = cb.data.replace("edit_channel_", "")
    ch = await get_all_channels()
    if cid not in ch:
        await cb.answer("Канал не найден", True)
        return
    await cb.message.edit_text(f"Редактирование канала {ch[cid]['name']}\nВыберите, что изменить:", reply_markup=get_edit_channel_keyboard(cid))
    await cb.answer()

@router.callback_query(F.data.startswith("edit_") & ~F.data.startswith("edit_channel_"))
async def edit_field(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb, show_alert=False):
        return
    parts = cb.data.split("_",2)
    if len(parts)<3:
        await cb.answer("Ошибка", True)
        return
    cid, field = parts[1], parts[2]
    ch = await get_all_channels()
    if cid not in ch:
        await cb.answer("Канал не найден", True)
        return
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
    if not await admin_only_callback(cb, show_alert=False):
        return
    parts = cb.data.split("_")
    cid = parts[3]
    cat_id = int(parts[4])
    await update_channel(cid, category_id=cat_id)
    log_admin_action(cb.from_user.id, f"updated channel {cid} category to {cat_id}")
    await cb.answer("Категория обновлена", False)
    await adm_view_chan(cb)
    await state.clear()

@router.message(EditChannelStates.waiting_for_name)
async def e_name(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    d = await state.get_data()
    await update_channel(d['ch_id'], name=m.text)
    log_admin_action(m.from_user.id, f"updated channel {d['ch_id']} name")
    await m.answer(f"✅ Название изменено на {m.text}")
    await state.clear()

@router.message(EditChannelStates.waiting_for_price)
async def e_price(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    if not m.text.isdigit():
        await m.answer("Введите число"); return
    d = await state.get_data()
    await update_channel(d['ch_id'], price=int(m.text))
    log_admin_action(m.from_user.id, f"updated channel {d['ch_id']} price")
    await m.answer(f"✅ Цена изменена на {m.text}$")
    await state.clear()

@router.message(EditChannelStates.waiting_for_subscribers)
async def e_subs(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    if not m.text.isdigit():
        await m.answer("Введите число"); return
    d = await state.get_data()
    await update_channel(d['ch_id'], subs=int(m.text))
    log_admin_action(m.from_user.id, f"updated channel {d['ch_id']} subscribers")
    await m.answer(f"✅ Количество подписчиков изменено на {m.text}")
    await state.clear()

@router.message(EditChannelStates.waiting_for_url)
async def e_url(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Ссылка должна начинаться с https://t.me/")
        return
    d = await state.get_data()
    await update_channel(d['ch_id'], url=url)
    log_admin_action(m.from_user.id, f"updated channel {d['ch_id']} url")
    await m.answer(f"✅ Ссылка изменена на {url}")
    await state.clear()

@router.message(EditChannelStates.waiting_for_description)
async def e_desc(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    d = await state.get_data()
    await update_channel(d['ch_id'], desc=m.text)
    log_admin_action(m.from_user.id, f"updated channel {d['ch_id']} description")
    await m.answer("✅ Описание изменено")
    await state.clear()

# ---------- Удаление канала ----------
@router.callback_query(F.data == "admin_remove")
async def adm_rem_menu(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    ch = await get_all_channels()
    if not ch:
        await cb.message.edit_text("Нет каналов для удаления", reply_markup=get_admin_channels_menu_keyboard())
        await cb.answer()
        return
    await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard(ch))
    await cb.answer()

@router.callback_query(F.data.startswith("admin_del_"))
async def adm_del(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cid = cb.data.replace("admin_del_", "")
    ch = await get_all_channels()
    if cid in ch:
        name = ch[cid]['name']
        await delete_channel(cid)
        log_admin_action(cb.from_user.id, f"deleted channel {cid} ({name})")
        await cb.answer(f"✅ Канал {name} удалён", False)
        new_ch = await get_all_channels()
        if not new_ch:
            await cb.message.edit_text("Все каналы удалены", reply_markup=get_admin_channels_menu_keyboard())
        else:
            await cb.message.edit_text("❌ Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard(new_ch))
    else:
        await cb.answer("Канал не найден", True)

# ---------- Добавление канала (стандартное) ----------
@router.callback_query(F.data == "admin_add")
async def adm_add_start(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb):
        return
    await cb.message.edit_text("➕ Выберите категорию для нового канала:", reply_markup=await get_category_selection_keyboard(get_all_categories, "add_chan_cat"))
    await state.set_state(AddChannelStates.waiting_for_category)
    await cb.answer()

@router.callback_query(F.data.startswith("add_chan_cat_"), AddChannelStates.waiting_for_category)
async def add_channel_category_chosen(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb):
        return
    cat_id = int(cb.data.split("_")[3])
    await state.update_data(category_id=cat_id)
    await cb.message.edit_text("Введите название канала:", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_name)
    await cb.answer()

@router.message(AddChannelStates.waiting_for_name)
async def a_name(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    await state.update_data(name=m.text)
    await m.answer("Введите цену (число):", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_price)

@router.message(AddChannelStates.waiting_for_price)
async def a_price(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    if not m.text.isdigit():
        await m.answer("Введите число")
        return
    await state.update_data(price=int(m.text))
    await m.answer("Введите количество подписчиков (число):", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_subscribers)

@router.message(AddChannelStates.waiting_for_subscribers)
async def a_subs(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    if not m.text.isdigit():
        await m.answer("Введите число")
        return
    await state.update_data(subscribers=int(m.text))
    await m.answer("Введите ссылку (https://t.me/...):", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_url)

@router.message(AddChannelStates.waiting_for_url)
async def a_url(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Ссылка должна начинаться с https://t.me/")
        return
    await state.update_data(url=url)
    await m.answer("Введите описание канала:", reply_markup=cancel_keyboard())
    await state.set_state(AddChannelStates.waiting_for_description)

@router.message(AddChannelStates.waiting_for_description)
async def a_desc(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    await state.update_data(description=m.text)
    data = await state.get_data()
    new_id = f"channel_{int(time.time())}"
    cat_id = data['category_id']
    await add_channel(new_id, data['name'], data['price'], data['subscribers'], data['url'], data['description'], cat_id)
    log_admin_action(m.from_user.id, f"added channel {new_id} ({data['name']})")
    cat = await get_category_by_id(cat_id)
    cat_name = cat['display_name'] if cat else ""
    await m.answer(f"✅ Канал {data['name']} добавлен в категорию {cat_name}!", reply_markup=get_admin_channels_menu_keyboard())
    await state.clear()

# ========== ДОПОЛНИТЕЛЬНЫЕ ИНСТРУМЕНТЫ ==========

# ---------- Просмотр логов ----------
@router.message(F.from_user.id.in_(ADMIN_IDS), F.text == "/logs")
async def show_logs(m: Message):
    if not await admin_only_message(m):
        return
    try:
        if not os.path.exists('bot_errors.log'):
            await m.answer("Файл логов не найден.")
            return
        with open('bot_errors.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        last_lines = lines[-20:] if len(lines) >= 20 else lines
        if not last_lines:
            await m.answer("Логи пусты.")
            return
        text = "📄 Последние записи в логах:\n" + "".join(last_lines)
        if len(text) > 4000:
            text = text[-4000:]
        await m.answer(text)
    except Exception as e:
        await m.answer(f"Ошибка при чтении логов: {e}")

# ---------- Просмотр логов действий администратора ----------
@router.message(F.from_user.id.in_(ADMIN_IDS), F.text == "/admin_logs")
async def show_admin_logs(m: Message):
    if not await admin_only_message(m):
        return
    try:
        if not os.path.exists('admin_actions.log'):
            await m.answer("Файл логов администратора не найден.")
            return
        with open('admin_actions.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        last_lines = lines[-15:] if len(lines) >= 15 else lines
        if not last_lines:
            await m.answer("Логи администратора пусты.")
            return
        text = "📄 Последние действия администратора:\n" + "".join(last_lines)
        if len(text) > 4000:
            text = text[-4000:]
        await m.answer(text)
    except Exception as e:
        await m.answer(f"Ошибка при чтении логов администратора: {e}")

# ---------- Статистика (общая) ----------
@router.callback_query(F.data == "admin_stats")
async def admin_stats_cb(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    try:
        conn = await asyncpg.connect(DATABASE_URL)
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

@router.callback_query(F.data == "export_orders")
async def export_orders_cb(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    await export_orders(cb.message)
    await cb.answer()

async def export_orders(message: Message):
    from database import get_orders
    if not is_admin(message.from_user.id):
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
        log_admin_action(message.from_user.id, "exported orders")
    except Exception as e:
        await message.answer(f"❌ Ошибка экспорта: {e}")
        logging.error(f"Export error: {e}")

@router.message(F.from_user.id.in_(ADMIN_IDS), F.text == "/export")
async def export_cmd(m: Message):
    if not await admin_only_message(m):
        return
    await export_orders(m)

# ---------- /update_subs ----------
@router.message(F.from_user.id.in_(ADMIN_IDS), F.text == "/update_subs")
async def update_subs_cmd(m: Message):
    if not await admin_only_message(m):
        return
    await m.answer("⏳ Обновляю подписчиков для всех каналов...")
    channels = await get_all_channels()
    if not channels:
        await m.answer("Нет каналов для обновления.")
        return
    updated = 0
    failed = 0
    for cid, info in channels.items():
        url = info.get('url', '')
        match = re.match(r'(?:https?://)?t(?:elegram)?\.me/(?:joinchat/)?([a-zA-Z0-9_]+)', url)
        if not match:
            failed += 1
            continue
        username = match.group(1)
        try:
            chat = await m.bot.get_chat(f"@{username}" if not username.startswith("@") else username)
            new_name = chat.title or chat.full_name or info['name']
            try:
                new_subs = await m.bot.get_chat_member_count(chat.id)
            except Exception:
                new_subs = info['subscribers']
            await update_channel(cid, name=new_name, subs=new_subs)
            updated += 1
        except Exception as e:
            print(f"Failed to update {url}: {e}")
            failed += 1
        await asyncio.sleep(0.5)
    await m.answer(f"✅ Обновлено: {updated} каналов\n❌ Не удалось: {failed}")

# ---------- Быстрое добавление канала ----------
class QuickAddStates(StatesGroup):
    waiting_for_channel_link = State()
    waiting_for_price = State()
    waiting_for_category = State()

@router.callback_query(F.data == "quick_add")
async def quick_add_start(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await cb.message.edit_text(
        "⚡ Отправьте ссылку на канал (например, https://t.me/username):",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(QuickAddStates.waiting_for_channel_link)
    await cb.answer()

@router.message(QuickAddStates.waiting_for_channel_link)
async def quick_add_link_received(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    url = m.text.strip()
    match = re.match(r'(?:https?://)?t(?:elegram)?\.me/(?:joinchat/)?([a-zA-Z0-9_]+)', url)
    if not match:
        await m.answer("Не удалось распознать ссылку. Убедитесь, что формат верный: https://t.me/username")
        return
    username = match.group(1)
    try:
        chat = await m.bot.get_chat(f"@{username}" if not username.startswith("@") else username)
        name = chat.title or chat.full_name or "Без названия"
        try:
            count = await m.bot.get_chat_member_count(chat.id)
        except Exception:
            count = 0
            await m.answer("⚠️ Не удалось получить количество подписчиков. Записано 0.")
        await state.update_data(quick_name=name, quick_subs=count, quick_url=f"https://t.me/{username}")
        await m.answer(f"Канал: {name}\nПодписчиков: {count}\n\nВведите цену (число):")
        await state.set_state(QuickAddStates.waiting_for_price)
    except Exception as e:
        await m.answer(f"Не удалось получить информацию о канале: {e}")
        await state.clear()

@router.message(QuickAddStates.waiting_for_price)
async def quick_add_price_received(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    if not m.text.isdigit():
        await m.answer("Введите цену целым числом.")
        return
    price = int(m.text)
    await state.update_data(quick_price=price)
    # Выбор категории
    cats = await get_all_categories()
    kb_rows = []
    for i in range(0, len(cats), 2):
        row = []
        row.append(InlineKeyboardButton(text=cats[i]['display_name'], callback_data=f"quick_cat_{cats[i]['id']}"))
        if i+1 < len(cats):
            row.append(InlineKeyboardButton(text=cats[i+1]['display_name'], callback_data=f"quick_cat_{cats[i+1]['id']}"))
        kb_rows.append(row)
    kb_rows.append([
        InlineKeyboardButton(text="⏭ Без категории", callback_data="quick_cat_skip"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_channel")
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await m.answer("Выберите категорию:", reply_markup=kb)
    await state.set_state(QuickAddStates.waiting_for_category)

@router.callback_query(F.data.startswith("quick_cat_"), QuickAddStates.waiting_for_category)
async def quick_add_category_chosen(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb):
        return
    cat_id = int(cb.data.split("_")[2])
    data = await state.get_data()
    new_id = f"channel_{int(time.time())}"
    await add_channel(new_id, data['quick_name'], data['quick_price'], data['quick_subs'], data['quick_url'], "", cat_id)
    log_admin_action(cb.from_user.id, f"quick-added channel {new_id}")
    await cb.message.edit_text(f"✅ Канал {data['quick_name']} добавлен!", reply_markup=get_admin_channels_menu_keyboard())
    await state.clear()
    await cb.answer()

@router.callback_query(F.data == "quick_cat_skip", QuickAddStates.waiting_for_category)
async def quick_add_skip_category(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb):
        return
    data = await state.get_data()
    new_id = f"channel_{int(time.time())}"
    await add_channel(new_id, data['quick_name'], data['quick_price'], data['quick_subs'], data['quick_url'], "", None)
    log_admin_action(cb.from_user.id, f"quick-added channel {new_id} (no category)")
    await cb.message.edit_text(f"✅ Канал {data['quick_name']} добавлен (без категории)!", reply_markup=get_admin_channels_menu_keyboard())
    await state.clear()
    await cb.answer()

# ---------- Массовое добавление каналов ----------
@router.callback_query(F.data == "bulk_add")
async def bulk_add_start(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await cb.message.edit_text(
        "📥 Отправьте JSON-массив с данными каналов.\n"
        "Формат: [{\"name\": \"...\", \"price\": ..., \"subscribers\": ..., \"url\": \"...\", \"description\": \"...\", \"category\": \"id\"}, ...]\n"
        "Поля description и category необязательны. Если category отсутствует — канал будет без категории.",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(MassAddStates.waiting_for_bulk_json)
    await cb.answer()

@router.message(MassAddStates.waiting_for_bulk_json)
async def bulk_add_json_received(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    try:
        data = json.loads(m.text.strip())
        if not isinstance(data, list):
            raise ValueError("Ожидался массив JSON")
        added = 0
        errors = []
        for idx, item in enumerate(data):
            try:
                name = item['name']
                price = int(item['price'])
                subs = int(item.get('subscribers', 0))
                url = item['url']
                desc = item.get('description', '')
                cat_id = item.get('category')
                new_id = f"channel_{int(time.time())}_{idx}"
                await add_channel(new_id, name, price, subs, url, desc, cat_id)
                added += 1
                log_admin_action(m.from_user.id, f"bulk-added channel {new_id}")
            except Exception as e:
                errors.append(f"{item.get('name', 'неизвестно')}: {e}")
        result = f"✅ Добавлено каналов: {added}"
        if errors:
            result += f"\n❌ Ошибки: {', '.join(errors[:5])}"
        await m.answer(result, reply_markup=get_admin_channels_menu_keyboard())
        await state.clear()
    except json.JSONDecodeError:
        await m.answer("Неверный JSON. Попробуйте снова.")
    except Exception as e:
        await m.answer(f"Ошибка при обработке: {e}")
        await state.clear()

# ---------- Отмена для новых состояний ----------
@router.callback_query(F.data == "cancel_add_channel", MassAddStates.waiting_for_bulk_json)
@router.callback_query(F.data == "cancel_add_channel", QuickAddStates.waiting_for_channel_link)
@router.callback_query(F.data == "cancel_add_channel", QuickAddStates.waiting_for_price)
@router.callback_query(F.data == "cancel_add_channel", QuickAddStates.waiting_for_category)
@router.callback_query(F.data == "cancel_add_channel", AdminSupportStates.waiting_for_broadcast_message)
@router.callback_query(F.data == "cancel_add_channel", AdminSupportStates.waiting_for_broadcast_confirm)
async def cancel_new_processes(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
    await cb.answer()

# ---------- Заявки (покупателей и продавцов) ----------
@router.callback_query(F.data == "admin_orders")
async def adm_orders(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    ords = await get_orders(20)
    if not ords:
        await cb.message.edit_text("Нет заявок", reply_markup=get_admin_orders_menu_keyboard())
        await cb.answer()
        return
    await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))
    await cb.answer()

@router.callback_query(F.data.startswith("admin_order_"))
async def adm_view_order(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    oid = int(cb.data.split("_")[2])
    ordd = await get_order_by_id(oid)
    if not ordd:
        await cb.answer("Заявка не найдена", True); return
    em = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌', 'ожидает оплаты':'🕒', 'вывод':'💰'}
    txt = f"📄 Заявка #{ordd['id']}\n👤 @{ordd['username']}\n💰 Сумма: {ordd['total']}$\n📌 Статус: {em.get(ordd['status'],'⚪')} {ordd['status']}\n\nВыберите новый статус:"
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
    if not await admin_only_callback(cb):
        return
    parts = cb.data.split("_")
    oid = int(parts[2])
    new_st = "_".join(parts[3:])
    order = await get_order_by_id(oid)
    if not order:
        await cb.answer("Заявка не найдена", True); return

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
    if new_st != 'отменена':
        try:
            await cb.bot.send_message(order['user_id'], f"📢 Статус вашей заявки #{oid} изменён на: {new_st}")
        except: pass
    ords = await get_orders(20)
    await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))

# ---------- Ручное изменение баланса ----------
@router.callback_query(F.data == "admin_balance")
async def admin_balance_start(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb):
        return
    await cb.message.edit_text("Введите Telegram ID пользователя:", reply_markup=cancel_keyboard())
    await state.set_state(AdminBalanceStates.waiting_for_user_id)
    await cb.answer()

@router.message(AdminBalanceStates.waiting_for_user_id)
async def process_balance_user_id(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    if not m.text.isdigit():
        await m.answer("Введите числовой ID")
        return
    target_id = int(m.text)
    await state.update_data(target_id=target_id)
    await m.answer("Введите сумму (положительное – пополнение, отрицательное – списание):", reply_markup=cancel_keyboard())
    await state.set_state(AdminBalanceStates.waiting_for_amount)

@router.message(AdminBalanceStates.waiting_for_amount)
async def process_balance_amount(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
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
        log_admin_action(m.from_user.id, f"added {amount}$ to user {target_id}")
        await m.answer(f"✅ Баланс пользователя {target_id} пополнен на {amount}$", reply_markup=get_admin_keyboard())
    else:
        success = await debit_balance(target_id, -amount, None, f"Ручное списание админом {m.from_user.id}")
        if success:
            log_admin_action(m.from_user.id, f"deducted {-amount}$ from user {target_id}")
            await m.answer(f"✅ С баланса пользователя {target_id} списано {-amount}$", reply_markup=get_admin_keyboard())
        else:
            bal = await get_user_balance(target_id)
            await m.answer(f"❌ Недостаточно средств. Текущий баланс: {bal}$", reply_markup=get_admin_keyboard())
    await state.clear()

# ---------- Очистка заявок ----------
@router.callback_query(F.data == "confirm_clear_failed")
async def ask_clear_failed(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, очистить неуспешные", callback_data="clear_failed_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="clear_no")]
    ])
    await cb.message.edit_text("⚠️ Будут удалены все заявки со статусами «в обработке» и «отменена». Оплаченные и выполненные останутся.", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "confirm_clear_all")
async def ask_clear_all(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, полная очистка", callback_data="clear_all_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="clear_no")]
    ])
    await cb.message.edit_text("⚠️ **Полная очистка**: будут удалены **все** заявки (и у вас, и у покупателей). Это действие необратимо.", reply_markup=kb, parse_mode="Markdown")
    await cb.answer()

@router.callback_query(F.data == "clear_failed_yes")
async def clear_failed(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    try:
        await clear_non_successful_orders()
        await cb.message.edit_text("✅ Неуспешные заявки удалены.", reply_markup=get_admin_keyboard())
    except Exception as e:
        print(f"Ошибка очистки: {e}")
        await cb.message.edit_text("❌ Ошибка при очистке. Попробуйте позже.")
    await cb.answer()

@router.callback_query(F.data == "clear_all_yes")
async def clear_all(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    try:
        await clear_all_orders()
        await cb.message.edit_text("✅ Все заявки удалены.", reply_markup=get_admin_keyboard())
    except Exception as e:
        print(f"Ошибка очистки: {e}")
        await cb.message.edit_text("❌ Ошибка при очистке. Попробуйте позже.")
    await cb.answer()

@router.callback_query(F.data == "clear_no")
async def clear_no(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    await cb.message.delete()
    await cb.answer("Очистка отменена")

# ---------- Поиск каналов ----------
@router.message(F.from_user.id.in_(ADMIN_IDS), F.text.startswith("/find_channels"))
async def find_channels(m: Message):
    if not await admin_only_message(m):
        return
    query = m.text.replace("/find_channels", "").strip()
    if not query:
        await m.answer("Использование: /find_channels <текст>")
        return
    all_ch = await get_all_channels()
    found = {k: v for k, v in all_ch.items() if query.lower() in v['name'].lower()}
    if not found:
        await m.answer("Ничего не найдено.")
        return
    kb, page, total = get_admin_list_keyboard(found, 0, category_id="all")
    await m.answer(f"Результаты поиска «{query}» (страница 1/{total}):", reply_markup=kb)

# ---------- Резервное копирование ----------
@router.message(F.from_user.id.in_(ADMIN_IDS), F.text == "/backup")
async def backup_cmd(m: Message):
    if not await admin_only_message(m):
        return
    await m.answer("⏳ Создаю резервную копию базы данных...")
    try:
        filename = await backup_database()
        from aiogram.types import FSInputFile
        file = FSInputFile(filename)
        await m.answer_document(file, caption="📦 Резервная копия базы данных")
        os.remove(filename)
    except Exception as e:
        await m.answer(f"❌ Ошибка при создании бэкапа: {e}")

# ========== МАССОВАЯ РАССЫЛКА С ПОДТВЕРЖДЕНИЕМ ==========
@router.message(F.from_user.id.in_(ADMIN_IDS), F.text == "/broadcast")
@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(cb_or_msg, state: FSMContext):
    if isinstance(cb_or_msg, CallbackQuery):
        cb = cb_or_msg
        if not await admin_only_callback(cb, show_alert=False):
            return
        await cb.message.answer("Введите сообщение для рассылки:", reply_markup=cancel_keyboard())
        await cb.answer()
    else:
        if not await admin_only_message(cb_or_msg):
            return
        await cb_or_msg.answer("Введите сообщение для рассылки:", reply_markup=cancel_keyboard())
    await state.set_state(AdminSupportStates.waiting_for_broadcast_message)

@router.message(AdminSupportStates.waiting_for_broadcast_message)
async def broadcast_text_received(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    text = m.text
    await state.update_data(broadcast_text=text)
    preview = f"Рассылка:\n\n{text}\n\nПодтвердить отправку?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="broadcast_confirm"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
    ])
    await m.answer(preview, reply_markup=kb)
    await state.set_state(AdminSupportStates.waiting_for_broadcast_confirm)

@router.callback_query(F.data == "broadcast_confirm", AdminSupportStates.waiting_for_broadcast_confirm)
async def confirm_broadcast(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb, show_alert=False):
        return
    data = await state.get_data()
    text = data.get('broadcast_text', '')
    await state.clear()
    await cb.message.edit_text("⏳ Выполняется рассылка...")
    user_ids = await get_all_user_ids()
    sent = 0
    for uid in user_ids:
        try:
            await cb.bot.send_message(uid, f"📢 Рассылка:\n\n{text}")
            sent += 1
        except Exception:
            pass
    await cb.message.edit_text(f"✅ Рассылка завершена. Отправлено {sent} из {len(user_ids)} пользователям.")
    await cb.answer()

@router.callback_query(F.data == "broadcast_cancel", AdminSupportStates.waiting_for_broadcast_confirm)
async def cancel_broadcast_inline(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await state.clear()
    await cb.message.edit_text("Рассылка отменена.", reply_markup=get_admin_keyboard())
    await cb.answer()

# ========== ЗАЯВКИ ПРОДАВЦОВ ==========
@router.callback_query(F.data == "admin_seller_applications")
async def admin_seller_applications(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    applications = await get_seller_applications('pending')
    if not applications:
        await cb.message.edit_text("Нет новых заявок от продавцов.", reply_markup=get_admin_orders_menu_keyboard())
        await cb.answer()
        return
    text = "📋 Заявки от продавцов:\n\n"
    for app in applications[:10]:
        text += f"#{app['id']} | @{app['username']} | {app['channel_name']} | {app['price']}$\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📄 Заявка #{app['id']}", callback_data=f"review_seller_{app['id']}")] for app in applications[:10]
    ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_to_orders")]])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("review_seller_"))
async def review_seller(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    app_id = int(cb.data.split("_")[2])
    app = await get_seller_application_by_id(app_id)
    if not app:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    text = (
        f"📄 Заявка #{app['id']}\n"
        f"👤 @{app['username']}\n"
        f"📢 Канал: {app['channel_name']}\n"
        f"🔗 Ссылка: {app['channel_url']}\n"
        f"💰 Цена: {app['price']}$\n"
        f"📝 Описание: {app['description']}\n"
        f"Статус: {app['status']}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_seller_{app_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_seller_{app_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_seller_applications")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("approve_seller_"))
async def approve_seller(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    app_id = int(cb.data.split("_")[2])
    success = await approve_seller_application(app_id)
    if success:
        await cb.answer("Заявка одобрена!", show_alert=False)
        log_admin_action(cb.from_user.id, f"approved seller application {app_id}")

        app = await get_seller_application_by_id(app_id)
        if app:
            # уведомление продавцу
            try:
                await cb.bot.send_message(
                    app['user_id'],
                    f"✅ Ваша заявка на канал «{app['channel_name']}» одобрена! Теперь он доступен в каталоге."
                )
            except Exception as e:
                print(f"Не удалось уведомить продавца {app['user_id']}: {e}")

            # Добавление канала в общий каталог
            try:
                new_id = f"channel_{int(time.time())}"
                await add_channel(
                    ch_id=new_id,
                    name=app['channel_name'],
                    price=app['price'],
                    subscribers=0,
                    url=app['channel_url'],
                    desc=app.get('description', ''),
                    category_id=app.get('category_id')
                )
                log_admin_action(cb.from_user.id, f"added channel {new_id} from seller application {app_id}")
            except Exception as e:
                print(f"Ошибка добавления канала из заявки {app_id}: {e}")
    else:
        await cb.answer("Не удалось одобрить заявку", show_alert=True)
    await admin_seller_applications(cb)

@router.callback_query(F.data.startswith("reject_seller_"))
async def reject_seller(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    app_id = int(cb.data.split("_")[2])
    success = await reject_seller_application(app_id)
    if success:
        await cb.answer("Заявка отклонена", show_alert=False)
        log_admin_action(cb.from_user.id, f"rejected seller application {app_id}")
    else:
        await cb.answer("Не удалось отклонить заявку", show_alert=True)
    await admin_seller_applications(cb)
