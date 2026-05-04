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
                      get_seller_application_by_id, update_seller_application,
                      _load_channels_from_db)
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

class QuickAddStates(StatesGroup):
    waiting_for_channel_link = State()
    waiting_for_price = State()
    waiting_for_category = State()

# ---------- Фоновая задача обновления подписчиков раз в сутки ----------
async def daily_subscriber_update(bot):
    while True:
        await asyncio.sleep(86400)  # 24 часа
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

@router.callback_query(F.data == "admin_channels_menu")
async def admin_channels_menu(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    await cb.message.edit_text("📋 Управление каналами:", reply_markup=get_admin_channels_menu_keyboard())
    await cb.answer()

@router.callback_query(F.data == "admin_back_to_channels")
async def back_to_channels_menu(cb: CallbackQuery):
    await admin_channels_menu(cb)

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
    await _load_channels_from_db()
    await cb.answer("Категория удалена", False)
    await admin_categories_menu(cb)

# ---------- Список каналов ----------
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
    await admin_channels_menu(cb)

# ---------- Просмотр канала ----------
@router.callback_query(F.data.startswith("admin_view_"))
async def adm_view_chan(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cid = cb.data.replace("admin_view_", "")
    await _load_channels_from_db()
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
    await _load_channels_from_db()
    await cb.answer(f"Канал теперь {'активен' if new_state else 'скрыт'}", show_alert=False)
    await adm_view_chan(cb)

# ---------- Редактирование канала ----------
@router.callback_query(F.data.startswith("edit_channel_"))
async def edit_chan_menu(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cid = cb.data.replace("edit_channel_", "")
    await _load_channels_from_db()
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
    await _load_channels_from_db()
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
    if len(parts) < 5:
        await cb.answer("Ошибка данных", True)
        return
    cid = parts[3]
    cat_id = int(parts[4])
    await update_channel(cid, category_id=cat_id)
    log_admin_action(cb.from_user.id, f"updated channel {cid} category to {cat_id}")
    await _load_channels_from_db()
    await cb.answer("Категория обновлена", False)
    await admin_list_back(cb)
    await state.clear()

@router.message(EditChannelStates.waiting_for_name)
async def e_name(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    d = await state.get_data()
    await update_channel(d['ch_id'], name=m.text)
    log_admin_action(m.from_user.id, f"updated channel {d['ch_id']} name")
    await _load_channels_from_db()
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
    await _load_channels_from_db()
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
    await _load_channels_from_db()
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
    await _load_channels_from_db()
    await m.answer(f"✅ Ссылка изменена на {url}")
    await state.clear()

@router.message(EditChannelStates.waiting_for_description)
async def e_desc(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    d = await state.get_data()
    await update_channel(d['ch_id'], desc=m.text)
    log_admin_action(m.from_user.id, f"updated channel {d['ch_id']} description")
    await _load_channels_from_db()
    await m.answer("✅ Описание изменено")
    await state.clear()

# ---------- Удаление канала (с подтверждением) ----------
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
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_del_{cid}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_remove")]
        ])
        await cb.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить канал «{ch[cid]['name']}»?",
            reply_markup=kb
        )
        await cb.answer()
    else:
        await cb.answer("Канал не найден", True)

@router.callback_query(F.data.startswith("confirm_del_"))
async def confirm_delete_channel(cb: CallbackQuery):
    if not await admin_only_callback(cb, show_alert=False):
        return
    cid = cb.data.replace("confirm_del_", "")
    ch = await get_all_channels()
    if cid in ch:
        name = ch[cid]['name']
        await delete_channel(cid)
        log_admin_action(cb.from_user.id, f"deleted channel {cid} ({name})")
        await _load_channels_from_db()
        await cb.answer(f"✅ Канал {name} удалён", False)
        await cb.message.edit_text("Канал удалён.", reply_markup=get_admin_channels_menu_keyboard())
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
    await _load_channels_from_db()
    cat = await get_category_by_id(cat_id)
    cat_name = cat['display_name'] if cat else ""
    await m.answer(f"✅ Канал {data['name']} добавлен в категорию {cat_name}!", reply_markup=get_admin_channels_menu_keyboard())
    await state.clear()

# ========== ДОПОЛНИТЕЛЬНЫЕ ИНСТРУМЕНТЫ ==========
@router.message(F.from_user.id.in_(ADMIN_IDS), Command("reload_cache"))
async def reload_cache_cmd(m: Message):
    if not await admin_only_message(m):
        return
    await _load_channels_from_db()
    await m.answer("✅ Кеш каналов обновлён.")

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

# Статистика, топ каналов, /update_subs, быстрое/массовое добавление, заявки покупателей, баланс, очистка, поиск, бэкап, рассылка остаются без изменений
# ... (опущено для краткости, но обязательно должны присутствовать) ...

# ---------- Отмена для любых состояний (исправленный обработчик) ----------
@router.callback_query(F.data == "cancel_add_channel")
async def cancel_any_callback(cb: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state in ("edit_seller_price", "edit_seller_desc"):
        await state.clear()
        await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
        await cb.answer()
    else:
        await state.clear()
        await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
        await cb.answer()

# ========== ЗАЯВКИ ПРОДАВЦОВ (полный блок, как в последней версии) ==========
# ... (весь код seller_applications, пагинация, редактирование, одобрение/отклонение) ...
# Он идентичен предыдущей полной версии admin.py, которую я предоставлял.

# ========== ЗАЯВКИ ПРОДАВЦОВ (пагинация, уведомления, редактирование) ==========
@router.callback_query(F.data == "admin_seller_applications")
async def admin_seller_applications(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    applications = await get_seller_applications('pending')
    if not applications:
        await cb.message.edit_text("Нет новых заявок от продавцов.", reply_markup=get_admin_orders_menu_keyboard())
        await cb.answer()
        return
    page = 0
    per_page = 5
    total_pages = (len(applications) + per_page - 1) // per_page
    start = page * per_page
    end = start + per_page
    page_apps = applications[start:end]

    text = f"📋 Заявки от продавцов (страница {page+1}/{total_pages}):\n\n"
    for app in page_apps:
        text += f"#{app['id']} | @{app['username']} | {app['channel_name']} | {app['price']}$\n"

    kb_rows = []
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"seller_app_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"seller_app_page_{page+1}"))
    if nav_buttons:
        kb_rows.append(nav_buttons)

    for app in page_apps:
        kb_rows.append([InlineKeyboardButton(text=f"📄 Заявка #{app['id']}", callback_data=f"review_seller_{app['id']}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_to_orders")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("seller_app_page_"))
async def seller_app_page(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    page = int(cb.data.split("_")[-1])
    applications = await get_seller_applications('pending')
    per_page = 5
    total_pages = (len(applications) + per_page - 1) // per_page
    start = page * per_page
    end = start + per_page
    page_apps = applications[start:end]

    text = f"📋 Заявки от продавцов (страница {page+1}/{total_pages}):\n\n"
    for app in page_apps:
        text += f"#{app['id']} | @{app['username']} | {app['channel_name']} | {app['price']}$\n"

    kb_rows = []
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"seller_app_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"seller_app_page_{page+1}"))
    if nav_buttons:
        kb_rows.append(nav_buttons)

    for app in page_apps:
        kb_rows.append([InlineKeyboardButton(text=f"📄 Заявка #{app['id']}", callback_data=f"review_seller_{app['id']}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_to_orders")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
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
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_seller_{app_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_seller_applications")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

# --- Редактирование заявки продавца (цена/описание) ---
@router.callback_query(F.data.startswith("edit_seller_"))
async def edit_seller_application(cb: CallbackQuery, state: FSMContext):
    if not await admin_only_callback(cb):
        return
    app_id = int(cb.data.split("_")[2])
    app = await get_seller_application_by_id(app_id)
    if not app:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    await state.update_data(edit_seller_id=app_id)
    await cb.message.edit_text(
        f"Редактирование заявки #{app_id}\n"
        "Введите новую цену (целым числом) или отправьте 'нет', чтобы оставить текущую:",
        reply_markup=cancel_keyboard()
    )
    await state.set_state("edit_seller_price")
    await cb.answer()

@router.message(F.text, state="edit_seller_price")
async def process_edit_seller_price(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    if m.text.lower() != "нет":
        if not m.text.isdigit():
            await m.answer("Введите число или 'нет'.")
            return
        new_price = int(m.text)
    else:
        new_price = None
    await state.update_data(edit_seller_new_price=new_price)
    await m.answer("Введите новое описание или отправьте 'нет', чтобы оставить текущее:")
    await state.set_state("edit_seller_desc")

@router.message(F.text, state="edit_seller_desc")
async def process_edit_seller_desc(m: Message, state: FSMContext):
    if not await admin_only_message(m):
        return
    new_desc = None if m.text.lower() == "нет" else m.text.strip()
    data = await state.get_data()
    app_id = data['edit_seller_id']
    new_price = data.get('edit_seller_new_price')

    await update_seller_application(app_id, price=new_price, description=new_desc)
    log_admin_action(m.from_user.id, f"edited seller application {app_id}")
    await m.answer("✅ Заявка обновлена.")
    await state.clear()
    # Возвращаемся к списку заявок
    await admin_seller_applications(m)

@router.callback_query(F.data.startswith("approve_seller_"))
async def approve_seller(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    app_id = int(cb.data.split("_")[2])
    success = await approve_seller_application(app_id)
    if not success:
        await cb.answer("Не удалось одобрить заявку", show_alert=True)
        await admin_seller_applications(cb)
        return

    await cb.answer("Заявка одобрена!", show_alert=False)
    log_admin_action(cb.from_user.id, f"approved seller application {app_id}")

    app = await get_seller_application_by_id(app_id)
    if not app:
        await cb.answer("Данные заявки не найдены", show_alert=True)
        return

    # Уведомление продавцу
    try:
        await cb.bot.send_message(
            app['user_id'],
            f"✅ Ваша заявка на канал «{app['channel_name']}» одобрена!\n"
            f"Канал добавлен в каталог по цене {app['price']}$.\n"
            f"Ссылка для покупателей: {app['channel_url']}"
        )
    except Exception as e:
        logging.error(f"Не удалось уведомить продавца {app['user_id']}: {e}")

    # Получаем реальное количество подписчиков
    subscribers = 0
    try:
        match = re.match(r'(?:https?://)?t(?:elegram)?\.me/(?:joinchat/)?([a-zA-Z0-9_]+)', app['channel_url'])
        if match:
            username = match.group(1)
            chat = await cb.bot.get_chat(f"@{username}" if not username.startswith("@") else username)
            try:
                subscribers = await cb.bot.get_chat_member_count(chat.id)
            except Exception:
                subscribers = 0
    except Exception as e:
        logging.warning(f"Не удалось получить подписчиков для {app['channel_url']}: {e}")

    # Добавляем канал в общий каталог
    try:
        new_id = f"channel_{int(time.time())}"
        await add_channel(
            ch_id=new_id,
            name=app['channel_name'],
            price=app['price'],
            subscribers=subscribers,
            url=app['channel_url'],
            desc=app.get('description', ''),
            category_id=app.get('category_id')
        )
        log_admin_action(cb.from_user.id, f"added channel {new_id} from seller application {app_id}")
        await _load_channels_from_db()
    except Exception as e:
        logging.error(f"Ошибка добавления канала из заявки {app_id}: {e}")

    await admin_seller_applications(cb)

@router.callback_query(F.data.startswith("reject_seller_"))
async def reject_seller(cb: CallbackQuery):
    if not await admin_only_callback(cb):
        return
    app_id = int(cb.data.split("_")[2])
    app = await get_seller_application_by_id(app_id)
    success = await reject_seller_application(app_id)
    if success:
        await cb.answer("Заявка отклонена", show_alert=False)
        log_admin_action(cb.from_user.id, f"rejected seller application {app_id}")
        if app:
            try:
                await cb.bot.send_message(
                    app['user_id'],
                    f"❌ Ваша заявка на канал «{app['channel_name']}» отклонена администратором.\n"
                    "При необходимости вы можете подать новую заявку с другими параметрами."
                )
            except Exception as e:
                logging.error(f"Не удалось уведомить продавца об отказе {app['user_id']}: {e}")
    else:
        await cb.answer("Не удалось отклонить заявку", show_alert=True)
    await admin_seller_applications(cb)
