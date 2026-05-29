"""Дополнительные обработчики админ-панели (каналы, заявки, рассылка)."""
import json
import re

from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ADMIN_IDS
from database import (
    _load_channels_from_db,
    add_category,
    add_channel,
    approve_seller_application,
    clear_all_orders,
    clear_non_successful_orders,
    copy_slots_to_new_channel,
    delete_category,
    delete_channel,
    get_all_categories,
    get_all_channels,
    get_all_user_ids,
    get_category_by_id,
    get_channel,
    get_order_by_id,
    get_orders,
    get_seller_application_by_id,
    get_seller_applications,
    reject_seller_application,
    update_channel,
    update_user_balance,
)
from handlers.admin import AdminSupportStates, admin_logger, router
from keyboards import (
    cancel_keyboard,
    get_admin_categories_keyboard,
    get_admin_channels_menu_keyboard,
    get_admin_keyboard,
    get_admin_list_keyboard,
    get_admin_orders_keyboard,
    get_admin_orders_menu_keyboard,
    get_admin_remove_keyboard,
    get_categories_admin_keyboard,
    get_category_actions_keyboard,
    get_category_selection_keyboard,
    get_confirm_delete_category_keyboard,
    get_edit_channel_keyboard,
)
from states import AddCategoryStates, AddChannelStates, AdminBalanceStates, EditChannelStates, MassAddStates, QuickAddStates


def _admin_only(cb: CallbackQuery) -> bool:
    return cb.from_user.id in ADMIN_IDS


def _channel_id_from_url(url: str, fallback: str) -> str:
    match = re.match(r'(?:https?://)?t(?:elegram)?\.me/(?:joinchat/)?([a-zA-Z0-9_]+)', url.strip())
    return match.group(1) if match else fallback


def _order_status_keyboard(order_id: int, current: str) -> InlineKeyboardMarkup:
    rows = []
    for st, label in [
        ('в обработке', '🟡 В обработке'),
        ('оплачена', '🟢 Оплачена'),
        ('выполнена', '✅ Выполнена'),
        ('отменена', '❌ Отменена'),
    ]:
        if st != current:
            rows.append([
                InlineKeyboardButton(text=label, callback_data=f"set_status_{order_id}_{st}")
            ])
    rows.append([InlineKeyboardButton(text="🔙 К списку", callback_data="admin_orders")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(
    F.data == "cancel_add_channel",
    StateFilter(
        AddChannelStates,
        QuickAddStates,
        MassAddStates,
        AddCategoryStates,
        AdminBalanceStates,
        AdminSupportStates,
    ),
)
async def cancel_admin_fsm(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    await state.clear()
    await cb.message.edit_text("👑 Админ‑панель", reply_markup=get_admin_keyboard())
    await cb.answer()


# ================== ЗАЯВКИ ==================
@router.callback_query(F.data == "admin_orders")
async def admin_orders_list(cb: CallbackQuery):
    if not _admin_only(cb):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    ords = await get_orders(20)
    if not ords:
        await cb.message.edit_text("Заказов нет.", reply_markup=get_admin_orders_menu_keyboard())
    else:
        await cb.message.edit_text("📋 Список заявок:", reply_markup=get_admin_orders_keyboard(ords))
    await cb.answer()


@router.callback_query(F.data.startswith("admin_order_"))
async def admin_order_detail(cb: CallbackQuery):
    if not _admin_only(cb):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    oid = int(cb.data.split("_")[2])
    order = await get_order_by_id(oid)
    if not order:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    items = "\n".join(
        f"• {it.get('name', '?')} — {it.get('price', 0)}$"
        + (f" ({it['date']})" if it.get('date') else "")
        for it in (order.get('cart') or [])
    ) or "—"
    text = (
        f"📄 Заявка #{oid}\n"
        f"👤 {order['username']} ({order['user_id']})\n"
        f"💰 {order['total']}$\n"
        f"📌 {order['status']}\n\n"
        f"Состав:\n{items}"
    )
    await cb.message.edit_text(text, reply_markup=_order_status_keyboard(oid, order['status']))
    await cb.answer()


@router.callback_query(F.data == "confirm_clear_failed")
async def confirm_clear_failed(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="exec_clear_failed")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="admin_orders_menu")],
    ])
    await cb.message.edit_text("Удалить все заявки «в обработке» и «отменена»?", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "exec_clear_failed")
async def exec_clear_failed(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    await clear_non_successful_orders()
    admin_logger.info(f"Admin {cb.from_user.id}: cleared non-successful orders")
    await cb.message.edit_text("🧹 Неуспешные заявки удалены.", reply_markup=get_admin_orders_menu_keyboard())
    await cb.answer()


@router.callback_query(F.data == "confirm_clear_all")
async def confirm_clear_all(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить ВСЁ", callback_data="exec_clear_all")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="admin_orders_menu")],
    ])
    await cb.message.edit_text("⚠️ Удалить ВСЕ заявки и связанные транзакции?", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "exec_clear_all")
async def exec_clear_all(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    await clear_all_orders()
    admin_logger.info(f"Admin {cb.from_user.id}: cleared all orders")
    await cb.message.edit_text("🧹 Все заявки удалены.", reply_markup=get_admin_orders_menu_keyboard())
    await cb.answer()


# ================== ЗАЯВКИ ПРОДАВЦОВ ==================
@router.callback_query(F.data == "admin_seller_applications")
async def admin_seller_apps(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    apps = await get_seller_applications('pending')
    if not apps:
        await cb.message.edit_text("Нет заявок продавцов.", reply_markup=get_admin_orders_menu_keyboard())
        await cb.answer()
        return
    kb_rows = []
    for app in apps[:15]:
        kb_rows.append([
            InlineKeyboardButton(
                text=f"{app['channel_name']} ({app['price']}$)",
                callback_data=f"seller_app_{app['id']}",
            )
        ])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_orders_menu")])
    await cb.message.edit_text("📋 Заявки продавцов:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data.startswith("seller_app_"))
async def seller_app_detail(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    app_id = int(cb.data.split("_")[2])
    app = await get_seller_application_by_id(app_id)
    if not app:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    text = (
        f"📢 {app['channel_name']}\n"
        f"🔗 {app['channel_url']}\n"
        f"💰 {app['price']}$\n"
        f"👤 @{app.get('username', '—')} ({app['user_id']})\n"
        f"📝 {app.get('description') or '—'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_seller_{app_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_seller_{app_id}"),
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_seller_applications")],
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("approve_seller_"))
async def approve_seller(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    app_id = int(cb.data.split("_")[2])
    app = await get_seller_application_by_id(app_id)
    if not app:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    if not await approve_seller_application(app_id):
        await cb.answer("Уже обработана", show_alert=True)
        return
    ch_id = _channel_id_from_url(app['channel_url'], str(app_id))
    subs = 0
    try:
        match = re.match(r'(?:https?://)?t(?:elegram)?\.me/([a-zA-Z0-9_]+)', app['channel_url'])
        if match:
            chat = await cb.bot.get_chat(f"@{match.group(1)}")
            subs = await cb.bot.get_chat_member_count(chat.id)
    except Exception:
        pass
    await add_channel(
        ch_id,
        app['channel_name'],
        app['price'],
        subs,
        app['channel_url'],
        app.get('description') or '',
        app.get('category_id'),
    )
    await copy_slots_to_new_channel(str(app_id), ch_id)
    await _load_channels_from_db()
    try:
        await cb.bot.send_message(app['user_id'], f"✅ Канал «{app['channel_name']}» одобрен и добавлен в каталог.")
    except Exception:
        pass
    admin_logger.info(f"Admin {cb.from_user.id}: approved seller app {app_id}")
    await cb.answer("Одобрено", show_alert=True)
    await admin_seller_apps(cb)


@router.callback_query(F.data.startswith("reject_seller_"))
async def reject_seller(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    app_id = int(cb.data.split("_")[2])
    if await reject_seller_application(app_id):
        app = await get_seller_application_by_id(app_id)
        if app:
            try:
                await cb.bot.send_message(app['user_id'], f"❌ Заявка на канал «{app['channel_name']}» отклонена.")
            except Exception:
                pass
    await cb.answer("Отклонено")
    await admin_seller_apps(cb)


# ================== КАНАЛЫ: СПИСОК / УДАЛЕНИЕ ==================
@router.callback_query(F.data == "admin_list")
async def admin_list_channels(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    await _load_channels_from_db()
    ch = await get_all_channels()
    kb, page, total = get_admin_list_keyboard(ch, 0, None)
    await cb.message.edit_text(f"📋 Каналы (стр. 1/{total}):", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "admin_list_back")
async def admin_list_back(cb: CallbackQuery):
    await admin_channels_menu_redirect(cb)


async def admin_channels_menu_redirect(cb: CallbackQuery):
    await cb.message.edit_text("📋 Управление каналами:", reply_markup=get_admin_channels_menu_keyboard())
    await cb.answer()


@router.callback_query(F.data.startswith("admin_list_page_"))
async def admin_list_page(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    parts = cb.data.split("_")
    page = int(parts[3])
    cat_raw = parts[4] if len(parts) > 4 else "None"
    category_id = None if cat_raw in ("None", "all", "none") else int(cat_raw)
    ch = await get_all_channels(category_id if category_id else None)
    kb, cur, total = get_admin_list_keyboard(ch, page, category_id)
    await cb.message.edit_text(f"📋 Каналы (стр. {cur + 1}/{total}):", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_view_"))
async def admin_view_channel(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    cid = cb.data.replace("admin_view_", "")
    info = await get_channel(cid)
    if not info:
        await cb.answer("Канал не найден", show_alert=True)
        return
    active = "🟢" if info.get('active', True) else "🔴"
    text = (
        f"{active} {info['name']}\n"
        f"ID: {cid}\n"
        f"💰 {info['price']}$\n"
        f"👥 {info.get('subscribers', 0)}\n"
        f"🔗 {info.get('url', '')}\n"
        f"📝 {info.get('description', '')}"
    )
    kb = get_edit_channel_keyboard(cid)
    extra = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="👁 Скрыть" if info.get('active', True) else "👁 Показать",
            callback_data=f"toggle_active_{cid}",
        )],
        *kb.inline_keyboard,
    ])
    await cb.message.edit_text(text, reply_markup=extra)
    await cb.answer()


@router.callback_query(F.data.startswith("toggle_active_"))
async def toggle_active(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    from database import toggle_channel_active
    cid = cb.data.replace("toggle_active_", "")
    await toggle_channel_active(cid)
    await admin_view_channel(cb)


@router.callback_query(F.data == "admin_remove")
async def admin_remove_menu(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    ch = await get_all_channels()
    await cb.message.edit_text("Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard(ch))
    await cb.answer()


@router.callback_query(F.data.startswith("admin_del_"))
async def admin_del_channel(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    cid = cb.data.replace("admin_del_", "")
    await delete_channel(cid)
    await _load_channels_from_db()
    admin_logger.info(f"Admin {cb.from_user.id}: deleted channel {cid}")
    await cb.answer("Канал удалён")
    ch = await get_all_channels()
    await cb.message.edit_text("Выберите канал для удаления:", reply_markup=get_admin_remove_keyboard(ch))


# ================== ДОБАВЛЕНИЕ КАНАЛА ==================
@router.callback_query(F.data == "admin_add")
async def admin_add_start(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    kb = await get_admin_categories_keyboard(get_all_categories)
    await cb.message.edit_text("Выберите категорию:", reply_markup=kb)
    await state.set_state(AddChannelStates.waiting_for_category)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_cat_"), StateFilter(AddChannelStates.waiting_for_category))
async def admin_add_category_pick(cb: CallbackQuery, state: FSMContext):
    raw = cb.data.replace("admin_cat_", "")
    if raw == "all":
        await cb.answer("Выберите конкретную категорию", show_alert=True)
        return
    category_id = None if raw == "none" else int(raw)
    await state.update_data(category_id=category_id)
    await cb.message.edit_text("Введите название канала:")
    await state.set_state(AddChannelStates.waiting_for_name)
    await cb.answer()


@router.message(StateFilter(AddChannelStates.waiting_for_name))
async def admin_add_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await m.answer("Введите цену ($):")
    await state.set_state(AddChannelStates.waiting_for_price)


@router.message(StateFilter(AddChannelStates.waiting_for_price))
async def admin_add_price(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        await m.answer("Введите целое число")
        return
    await state.update_data(price=int(m.text.strip()))
    await m.answer("Введите число подписчиков:")
    await state.set_state(AddChannelStates.waiting_for_subscribers)


@router.message(StateFilter(AddChannelStates.waiting_for_subscribers))
async def admin_add_subs(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        await m.answer("Введите целое число")
        return
    await state.update_data(subscribers=int(m.text.strip()))
    await m.answer("Введите ссылку (https://t.me/...):")
    await state.set_state(AddChannelStates.waiting_for_url)


@router.message(StateFilter(AddChannelStates.waiting_for_url))
async def admin_add_url(m: Message, state: FSMContext):
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Ссылка должна начинаться с https://t.me/")
        return
    await state.update_data(url=url)
    await m.answer("Введите описание (или «нет»):")
    await state.set_state(AddChannelStates.waiting_for_description)


@router.message(StateFilter(AddChannelStates.waiting_for_description))
async def admin_add_desc(m: Message, state: FSMContext):
    desc = m.text.strip()
    if desc.lower() == 'нет':
        desc = ''
    data = await state.get_data()
    ch_id = _channel_id_from_url(data['url'], data['name'][:32])
    await add_channel(
        ch_id, data['name'], data['price'], data['subscribers'],
        data['url'], desc, data.get('category_id'),
    )
    await _load_channels_from_db()
    await state.clear()
    await m.answer(f"✅ Канал «{data['name']}» добавлен (ID: {ch_id}).", reply_markup=get_admin_channels_menu_keyboard())


# ================== БЫСТРОЕ ДОБАВЛЕНИЕ ==================
@router.callback_query(F.data == "quick_add")
async def quick_add_start(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    await cb.message.edit_text("Отправьте ссылку на канал:", reply_markup=cancel_keyboard())
    await state.set_state(QuickAddStates.waiting_for_channel_link)
    await cb.answer()


@router.message(StateFilter(QuickAddStates.waiting_for_channel_link))
async def quick_add_link(m: Message, state: FSMContext):
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Нужна ссылка https://t.me/...")
        return
    name = url.rstrip('/').split('/')[-1]
    subs = 0
    try:
        chat = await m.bot.get_chat(url if url.startswith('@') else url)
        name = chat.title or name
        subs = await m.bot.get_chat_member_count(chat.id)
    except Exception:
        pass
    await state.update_data(url=url, name=name, subscribers=subs)
    await m.answer("Введите цену ($):")
    await state.set_state(QuickAddStates.waiting_for_price)


@router.message(StateFilter(QuickAddStates.waiting_for_price))
async def quick_add_price(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        await m.answer("Введите целое число")
        return
    await state.update_data(price=int(m.text.strip()))
    kb = await get_category_selection_keyboard(get_all_categories, "quick_cat")
    await m.answer("Выберите категорию:", reply_markup=kb)
    await state.set_state(QuickAddStates.waiting_for_category)


@router.callback_query(F.data.startswith("quick_cat_"), StateFilter(QuickAddStates.waiting_for_category))
async def quick_add_category(cb: CallbackQuery, state: FSMContext):
    cat_id = None
    if not cb.data.endswith("_skip"):
        try:
            cat_id = int(cb.data.split("_")[2])
        except (IndexError, ValueError):
            pass
    data = await state.get_data()
    ch_id = _channel_id_from_url(data['url'], data['name'][:32])
    await add_channel(
        ch_id, data['name'], data['price'], data['subscribers'],
        data['url'], '', cat_id,
    )
    await _load_channels_from_db()
    await state.clear()
    await cb.message.edit_text(f"✅ Канал «{data['name']}» добавлен.", reply_markup=get_admin_channels_menu_keyboard())
    await cb.answer()


# ================== МАССОВОЕ ДОБАВЛЕНИЕ ==================
@router.callback_query(F.data == "bulk_add")
async def bulk_add_start(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    await cb.message.edit_text(
        "Отправьте JSON-массив каналов:\n"
        '[{"name":"...", "price":100, "subscribers":1000, "url":"https://t.me/...", "description":"", "category_id":1}]',
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(MassAddStates.waiting_for_bulk_json)
    await cb.answer()


@router.message(StateFilter(MassAddStates.waiting_for_bulk_json))
async def bulk_add_process(m: Message, state: FSMContext):
    try:
        items = json.loads(m.text)
        if not isinstance(items, list):
            raise ValueError("Ожидается массив")
    except (json.JSONDecodeError, ValueError) as e:
        await m.answer(f"Ошибка JSON: {e}")
        return
    added = 0
    for item in items:
        url = item.get('url', '')
        ch_id = _channel_id_from_url(url, item.get('name', 'ch')[:32])
        await add_channel(
            ch_id,
            item.get('name', 'Без названия'),
            int(item.get('price', 0)),
            int(item.get('subscribers', 0)),
            url,
            item.get('description', ''),
            item.get('category_id'),
        )
        added += 1
    await _load_channels_from_db()
    await state.clear()
    await m.answer(f"✅ Добавлено каналов: {added}", reply_markup=get_admin_channels_menu_keyboard())


# ================== КАТЕГОРИИ ==================
@router.callback_query(F.data == "admin_categories")
async def admin_categories(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    kb = await get_categories_admin_keyboard(get_all_categories)
    await cb.message.edit_text("🏷 Категории:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_category_"))
async def admin_category_actions(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    cat_id = int(cb.data.split("_")[2])
    cat = await get_category_by_id(cat_id)
    if not cat:
        await cb.answer("Не найдена", show_alert=True)
        return
    await cb.message.edit_text(
        f"Категория: {cat['display_name']}",
        reply_markup=get_category_actions_keyboard(cat_id),
    )
    await cb.answer()


@router.callback_query(F.data == "admin_add_category")
async def admin_add_category_start(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    await cb.message.edit_text("Введите системное имя (латиница, например news):")
    await state.set_state(AddCategoryStates.waiting_for_name)
    await cb.answer()


@router.message(StateFilter(AddCategoryStates.waiting_for_name))
async def admin_add_category_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip().lower())
    await m.answer("Введите отображаемое имя:")
    await state.set_state(AddCategoryStates.waiting_for_display_name)


@router.message(StateFilter(AddCategoryStates.waiting_for_display_name))
async def admin_add_category_display(m: Message, state: FSMContext):
    data = await state.get_data()
    await add_category(data['name'], m.text.strip())
    await state.clear()
    await m.answer("✅ Категория добавлена.", reply_markup=get_admin_channels_menu_keyboard())


@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def confirm_delete_category(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[3])
    await cb.message.edit_text("Удалить категорию?", reply_markup=get_confirm_delete_category_keyboard(cat_id))
    await cb.answer()


@router.callback_query(F.data.startswith("exec_delete_category_"))
async def exec_delete_category(cb: CallbackQuery):
    if not _admin_only(cb):
        return
    cat_id = int(cb.data.split("_")[3])
    await delete_category(cat_id)
    await cb.answer("Удалено")
    await admin_categories(cb)


# ================== БАЛАНС ==================
@router.callback_query(F.data == "admin_balance")
async def admin_balance_start(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    await cb.message.edit_text("Введите ID пользователя:")
    await state.set_state(AdminBalanceStates.waiting_for_user_id)
    await cb.answer()


@router.message(StateFilter(AdminBalanceStates.waiting_for_user_id))
async def admin_balance_user(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        await m.answer("Введите числовой ID")
        return
    await state.update_data(target_user_id=int(m.text.strip()))
    await m.answer("Введите сумму (+ пополнение, − списание):")
    await state.set_state(AdminBalanceStates.waiting_for_amount)


@router.message(StateFilter(AdminBalanceStates.waiting_for_amount))
async def admin_balance_amount(m: Message, state: FSMContext):
    try:
        amount = int(m.text.strip())
    except ValueError:
        await m.answer("Введите целое число")
        return
    data = await state.get_data()
    uid = data['target_user_id']
    if amount >= 0:
        await update_user_balance(uid, amount, f"Корректировка админом ({m.from_user.id})")
    else:
        from database import debit_balance
        ok = await debit_balance(uid, -amount, None, f"Списание админом ({m.from_user.id})")
        if not ok:
            await m.answer("Недостаточно средств на балансе")
            return
    await state.clear()
    admin_logger.info(f"Admin {m.from_user.id}: balance {amount} for user {uid}")
    await m.answer(f"✅ Баланс пользователя {uid} изменён на {amount}$")


# ================== РАССЫЛКА ==================
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    await cb.message.edit_text("Введите текст рассылки:")
    await state.set_state(AdminSupportStates.waiting_for_broadcast_message)
    await cb.answer()


@router.message(StateFilter(AdminSupportStates.waiting_for_broadcast_message))
async def admin_broadcast_confirm(m: Message, state: FSMContext):
    await state.update_data(broadcast_text=m.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")],
    ])
    await m.answer(f"Предпросмотр:\n\n{m.text}", reply_markup=kb)
    await state.set_state(AdminSupportStates.waiting_for_broadcast_confirm)


@router.callback_query(F.data == "broadcast_confirm", StateFilter(AdminSupportStates.waiting_for_broadcast_confirm))
async def admin_broadcast_send(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    data = await state.get_data()
    text = data.get('broadcast_text', '')
    user_ids = await get_all_user_ids()
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await cb.bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
    await state.clear()
    admin_logger.info(f"Admin {cb.from_user.id}: broadcast sent={sent} failed={failed}")
    await cb.message.edit_text(f"📢 Рассылка завершена.\n✅ {sent}\n❌ {failed}", reply_markup=get_admin_keyboard())
    await cb.answer()


# ================== РЕДАКТИРОВАНИЕ КАНАЛА ==================
@router.callback_query(F.data.startswith("edit_"))
async def edit_channel_start(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    parts = cb.data.split("_", 2)
    if len(parts) < 3:
        return
    cid, field = parts[1], parts[2]
    await state.update_data(edit_cid=cid, edit_field=field)
    prompts = {
        'name': 'Введите новое название:',
        'price': 'Введите новую цену:',
        'subscribers': 'Введите число подписчиков:',
        'url': 'Введите новую ссылку:',
        'description': 'Введите описание:',
        'category': None,
    }
    if field == 'category':
        kb = await get_category_selection_keyboard(get_all_categories, f"editcat_{cid}")
        await cb.message.edit_text("Выберите категорию:", reply_markup=kb)
        await state.set_state(EditChannelStates.waiting_for_category)
    else:
        await cb.message.edit_text(prompts.get(field, 'Введите значение:'))
        await state.set_state(getattr(EditChannelStates, f'waiting_for_{field}', EditChannelStates.waiting_for_name))
    await cb.answer()


@router.message(StateFilter(EditChannelStates))
async def edit_channel_value(m: Message, state: FSMContext):
    data = await state.get_data()
    cid = data.get('edit_cid')
    field = data.get('edit_field')
    if not cid or not field:
        await state.clear()
        return
    val = m.text.strip()
    kwargs = {}
    if field == 'name':
        kwargs['name'] = val
    elif field == 'price' and val.isdigit():
        kwargs['price'] = int(val)
    elif field == 'subscribers' and val.isdigit():
        kwargs['subs'] = int(val)
    elif field == 'url':
        kwargs['url'] = val
    elif field == 'description':
        kwargs['desc'] = val
    else:
        await m.answer("Некорректное значение")
        return
    await update_channel(cid, **kwargs)
    await _load_channels_from_db()
    await state.clear()
    await m.answer("✅ Сохранено", reply_markup=get_admin_channels_menu_keyboard())


@router.callback_query(F.data.startswith("editcat_"))
async def edit_channel_category(cb: CallbackQuery, state: FSMContext):
    if not _admin_only(cb):
        return
    parts = cb.data.split("_")
    cid = parts[1]
    cat_id = None
    if not cb.data.endswith("_skip"):
        try:
            cat_id = int(parts[2])
        except (IndexError, ValueError):
            pass
    await update_channel(cid, category_id=cat_id)
    await _load_channels_from_db()
    await state.clear()
    await cb.answer("Категория обновлена")
    info = await get_channel(cid)
    await cb.message.edit_text(f"✅ Категория канала «{info['name'] if info else cid}» обновлена.")
