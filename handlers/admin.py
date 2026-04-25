import os
import asyncio
import time
import asyncpg
import json
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import (get_all_channels, add_channel, delete_channel, update_channel,
                      get_orders, get_order_by_id, update_order_status, return_balance,
                      clear_non_successful_orders, clear_all_orders,
                      get_all_categories, add_category, delete_category, get_category_by_id,
                      get_or_create_user, update_user_balance, debit_balance, get_user_balance)
from states import (AddChannelStates, EditChannelStates, AddCategoryStates,
                    AdminBalanceStates, MassAddStates, QuickAddStates)
from keyboards import (get_admin_keyboard, get_admin_list_keyboard, get_admin_remove_keyboard,
                       get_admin_orders_keyboard, get_edit_channel_keyboard, get_stats_keyboard,
                       get_categories_admin_keyboard, get_category_actions_keyboard,
                       get_category_selection_keyboard, cancel_keyboard, get_main_keyboard)
from config import ADMIN_IDS

router = Router()

# ---------- Вход в админ‑панель ----------
@router.message(F.text == "🔑 Админ‑панель")
async def admin_panel_msg(m: Message):
    if m.from_user.id in ADMIN_IDS:
        await m.answer("👑 Админ‑панель", reply_markup=get_admin_keyboard())
    else:
        await m.answer("Нет прав")

# ---------- Кнопка «Назад» и отмена ----------
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

# ---------- Список каналов (без диагностики, но счётчик останется в логах) ----------
@router.callback_query(F.data == "admin_list")
async def adm_list(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет прав", True); return
    ch = await get_all_channels()
    if not ch:
        await cb.message.edit_text("❌ Не удалось загрузить каналы. Попробуйте позже.", reply_markup=get_main_keyboard(cb.from_user.id))
        await cb.answer()
        return
    await cb.message.edit_text("📋 Список каналов\nНажмите на канал для подробностей:", reply_markup=get_admin_list_keyboard(ch))
    await cb.answer()

# ---------- Просмотр конкретного канала ----------
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

# ... (весь остальной код admin.py остаётся точно таким же, как в предыдущей полной версии, включая редактирование, удаление, добавление каналов, быстрые инструменты, заявки, статистику и очистку)
# Я не дублирую его здесь ради краткости, но вы можете взять последний полный admin.py и вставить вместо этого комментария.
# Главное – добавить новый обработчик /count_channels.

# ---------- НОВАЯ КОМАНДА: /count_channels ----------
@router.message(F.from_user.id.in_(ADMIN_IDS), F.text == "/count_channels")
async def count_channels_cmd(m: Message):
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        total = await conn.fetchval("SELECT COUNT(*) FROM channels")
    finally:
        await conn.close()
    await m.answer(f"📊 Всего каналов в БД: {total}")
