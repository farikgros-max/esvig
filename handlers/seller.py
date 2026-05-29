import logging, traceback, asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

from database import (create_seller_application, get_seller_channels,
                      get_approved_seller_channels, get_all_categories,
                      set_slot, get_channel_slots, get_free_slots,
                      get_seller_channel_stats, get_calendar_fill_rate,
                      delete_slot, release_slot, get_catalog_channel_id_by_url,
                      _load_channels_from_db)
from keyboards import (get_seller_main_keyboard, get_seller_analytics_keyboard,
                       get_seller_channel_keyboard, cancel_keyboard, get_main_keyboard,
                       get_category_selection_keyboard)
from states import SellerStates, SellerCalendarStates

router = Router()
logger = logging.getLogger(__name__)

# дополнительные состояния для массового добавления
class SlotRangeStates(StatesGroup):
    waiting_for_range = State()
    waiting_for_days_count = State()

async def resolve_slot_channel_id(app):
    if app['status'] != 'approved':
        return str(app['id'])
    catalog_id = await get_catalog_channel_id_by_url(app['channel_url'])
    return catalog_id or str(app['id'])

async def is_channel_in_catalog(app):
    if app['status'] != 'approved':
        return True
    return await get_catalog_channel_id_by_url(app['channel_url']) is not None

# ─── клавиатура календаря (главный вид) ───
def get_calendar_view_kb(channel_id: int, slots: list, page: int = 0):
    per_page = 10  # 5 рядов по 2 кнопки
    total = max(1, (len(slots) + per_page - 1) // per_page)
    start = page * per_page
    end = start + per_page
    page_slots = slots[start:end]
    page_slots.sort(key=lambda s: s['date'])

    kb_rows = []
    row = []
    for i, slot in enumerate(page_slots):
        date = slot.get("date", "")
        status = slot.get("status", "")
        if status == "free":
            btn_text = f"🟢 {date}"
        else:
            btn_text = f"🔴 {date}"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"seller_slot_info_{channel_id}_{date}_{page}"))
        if len(row) == 2 or i == len(page_slots) - 1:
            kb_rows.append(row)
            row = []

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"seller_calendar_view_{channel_id}_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="none"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"seller_calendar_view_{channel_id}_{page+1}"))
    if nav:
        kb_rows.append(nav)

    kb_rows.append([InlineKeyboardButton(text="➕ Добавить слот", callback_data=f"seller_add_slot_{channel_id}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"seller_channel_{channel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

async def seller_start(m: Message):
    approved = await get_approved_seller_channels(m.from_user.id)
    if not approved:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Подать заявку", callback_data="seller_apply")],
            [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main_menu")]
        ])
        await m.answer("💰 Продать рекламу\n\nУ вас ещё нет одобренных каналов. Подайте заявку, чтобы начать продавать рекламу.", reply_markup=kb)
    else:
        await m.answer("💰 Продать рекламу\n\nВыберите действие:", reply_markup=get_seller_main_keyboard())

@router.message(F.text == "💰 Продать рекламу")
async def exchange_menu(m: Message):
    await seller_start(m)

@router.callback_query(F.data == "seller_back")
async def seller_back(cb: CallbackQuery):
    from handlers.start import send_welcome
    await send_welcome(cb.bot, cb.from_user.id, cb.from_user.id, cb.from_user.first_name, cb.from_user.username)
    await cb.answer()

@router.callback_query(F.data == "back_to_main_menu")
async def back_main_menu(cb: CallbackQuery):
    from handlers.start import send_welcome
    await send_welcome(cb.bot, cb.from_user.id, cb.from_user.id, cb.from_user.first_name, cb.from_user.username)
    await cb.answer()

@router.callback_query(F.data == "cancel_add_channel")
async def cancel_seller_application(cb: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    if not current or not str(current).startswith("Seller"):
        return
    await state.clear()
    await seller_start(cb.message)
    await cb.answer()

# Подача заявки
@router.callback_query(F.data == "seller_apply")
async def seller_apply_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите название канала:", reply_markup=cancel_keyboard())
    await state.set_state(SellerStates.waiting_for_channel_name)
    await cb.answer()

@router.message(SellerStates.waiting_for_channel_name)
async def seller_channel_name(m: Message, state: FSMContext):
    await state.update_data(channel_name=m.text.strip())
    await m.answer("Введите ссылку на канал (https://t.me/...):")
    await state.set_state(SellerStates.waiting_for_channel_url)

@router.message(SellerStates.waiting_for_channel_url)
async def seller_channel_url(m: Message, state: FSMContext):
    url = m.text.strip()
    if not url.startswith("https://t.me/"):
        await m.answer("Ссылка должна начинаться с https://t.me/")
        return
    await state.update_data(channel_url=url)
    await m.answer("Введите цену размещения (в $ за пост):")
    await state.set_state(SellerStates.waiting_for_price)

@router.message(SellerStates.waiting_for_price)
async def seller_price(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите целое число (например, 50)")
        return
    await state.update_data(price=int(m.text))
    cats = await get_all_categories()
    if not cats:
        await state.update_data(category_id=None)
        await m.answer("Введите описание канала (или отправьте 'нет'):")
        await state.set_state(SellerStates.waiting_for_description)
    else:
        kb = await get_category_selection_keyboard(get_all_categories, "seller_cat")
        await m.answer("Выберите категорию канала:", reply_markup=kb)
        await state.set_state(SellerStates.waiting_for_category)

@router.callback_query(F.data.startswith("seller_cat_"))
async def seller_category(cb: CallbackQuery, state: FSMContext):
    if await state.get_state() != SellerStates.waiting_for_category:
        await cb.answer("Сейчас не ожидается выбор категории", show_alert=True)
        return
    try:
        cat_id = int(cb.data.split("_")[2])
    except (IndexError, ValueError):
        cat_id = None
    await state.update_data(category_id=cat_id)
    await cb.message.edit_text("Введите описание канала (или отправьте 'нет'):")
    await state.set_state(SellerStates.waiting_for_description)
    await cb.answer()

@router.message(SellerStates.waiting_for_description)
async def seller_description(m: Message, state: FSMContext):
    desc = m.text.strip()
    if desc.lower() == 'нет':
        desc = ''
    data = await state.get_data()
    try:
        await create_seller_application(
            m.from_user.id,
            m.from_user.username or "",
            data['channel_url'],
            data['channel_name'],
            data['price'],
            desc,
            data.get('category_id')
        )
        await m.answer("✅ Заявка отправлена! Ожидайте одобрения администратором.", reply_markup=get_main_keyboard(m.from_user.id))
    except Exception as e:
        await m.answer(f"❌ Ошибка при подаче заявки: {e}")
    await state.clear()

# Мои каналы
@router.callback_query(F.data == "seller_my_channels")
async def seller_my_channels(cb: CallbackQuery):
    await _load_channels_from_db()
    channels = await get_seller_channels(cb.from_user.id)
    if not channels:
        await cb.message.edit_text("У вас нет каналов, отправленных на биржу.", reply_markup=get_seller_main_keyboard())
        await cb.answer()
        return
    text = "📢 Ваши каналы:\n\n"
    kb_rows = []
    visible_count = 0
    for ch in channels[:10]:
        status_emoji = "🟢" if ch['status'] == 'approved' else "🟡" if ch['status'] == 'pending' else "🔴"
        if ch['status'] == 'approved' and not await is_channel_in_catalog(ch):
            continue
        text += f"{status_emoji} {ch['channel_name']} ({ch['price']}$)\n"
        kb_rows.append([InlineKeyboardButton(text=ch['channel_name'], callback_data=f"seller_channel_{ch['id']}")])
        visible_count += 1
    if visible_count == 0:
        await cb.message.edit_text("У вас нет активных каналов.", reply_markup=get_seller_main_keyboard())
        await cb.answer()
        return
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="seller_back")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

# Детали канала
@router.callback_query(F.data.startswith("seller_channel_"))
async def seller_channel_detail(cb: CallbackQuery):
    app_id = int(cb.data.split("_")[2])
    channels = await get_seller_channels(cb.from_user.id)
    app = next((c for c in channels if c['id'] == app_id), None)
    if not app:
        await cb.answer("Канал не найден", show_alert=True)
        return
    text = f"📢 {app['channel_name']}\n{app.get('channel_url','')}\n💰 Цена: {app['price']}$\n📝 Описание: {app.get('description','Нет описания')}\nСтатус: {app['status']}"
    kb = get_seller_channel_keyboard(app_id)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("seller_edit_"))
async def seller_edit(cb: CallbackQuery):
    await cb.answer("Функция редактирования появится в ближайшем обновлении.", show_alert=True)

# ─── Календарь (главный вид) ───
@router.callback_query(F.data.startswith("seller_calendar_"))
@router.callback_query(F.data.startswith("seller_calendar_view_"))
async def seller_calendar_view(cb: CallbackQuery):
    try:
        parts = cb.data.split("_")
        if len(parts) == 3:
            app_id = int(parts[2])
            page = 0
        else:
            app_id = int(parts[3])
            page = int(parts[4])

        channels = await get_seller_channels(cb.from_user.id)
        app = next((c for c in channels if c['id'] == app_id), None)
        if not app:
            await cb.answer("Канал не найден", show_alert=True)
            return

        slot_ch_id = await resolve_slot_channel_id(app)
        slots = await get_channel_slots(slot_ch_id)
        free = await get_free_slots(slot_ch_id)
        total = len(slots)
        booked = total - len(free)

        text = f"📅 Календарь канала\n\n📋 Всего слотов: {total}\n🟢 Свободных: {len(free)}\n🔴 Занятых: {booked}"

        if total == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить слот", callback_data=f"seller_add_slot_{app_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"seller_channel_{app_id}")]
            ])
            await cb.message.edit_text(text + "\n\nНет слотов для отображения.", reply_markup=kb)
            await cb.answer()
            return

        kb = get_calendar_view_kb(app_id, slots, page)
        await cb.message.edit_text(text, reply_markup=kb)
        await cb.answer()
    except Exception:
        print("!!! ОШИБКА в seller_calendar_view !!!")
        traceback.print_exc()
        await cb.answer("⚠️ Ошибка календаря", show_alert=True)

# Детали слота
@router.callback_query(F.data.startswith("seller_slot_info_"))
async def seller_slot_detail(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 5:
        await cb.answer("Некорректные данные", show_alert=True)
        return
    app_id = int(parts[3])
    date_str = parts[4]
    page = int(parts[5]) if len(parts) > 5 else 0
    channels = await get_seller_channels(cb.from_user.id)
    app = next((c for c in channels if c['id'] == app_id), None)
    if not app:
        await cb.answer("Канал не найден", show_alert=True)
        return
    slot_ch_id = await resolve_slot_channel_id(app)
    slots = await get_channel_slots(slot_ch_id)
    slot_info = next((s for s in slots if s['date'] == date_str), None)
    if not slot_info:
        await cb.answer("Слот не найден", show_alert=True)
        return
    status = slot_info['status']
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить слот", callback_data=f"delete_slot_{app_id}_{date_str}_{page}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"seller_calendar_view_{app_id}_{page}")]
    ])
    if status == 'free':
        text = f"📅 Слот {date_str}\nСтатус: свободен"
    elif status == 'booked':
        text = f"📅 Слот {date_str}\nСтатус: занят (забронирован покупателем)"
    else:
        text = f"📅 Слот {date_str}\nСтатус: {status}"
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        if "message is not modified" in str(e):
            await cb.answer("Нет изменений", show_alert=True)
        else:
            raise
    await cb.answer()

# Удаление слота
@router.callback_query(F.data.startswith("delete_slot_"))
async def seller_delete_slot(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 4:
        await cb.answer("Некорректные данные", show_alert=True)
        return
    app_id = int(parts[2])
    date_str = parts[3]
    page = int(parts[4]) if len(parts) > 4 else 0
    channels = await get_seller_channels(cb.from_user.id)
    app = next((c for c in channels if c['id'] == app_id), None)
    if not app:
        await cb.answer("Канал не найден", show_alert=True)
        return
    slot_ch_id = await resolve_slot_channel_id(app)
    await delete_slot(slot_ch_id, date_str)
    await cb.answer(f"Слот {date_str} удалён", show_alert=False)
    await seller_calendar_view(cb)

# Добавление слота (подменю)
@router.callback_query(F.data.startswith("seller_add_slot_"))
async def seller_add_slot_menu(cb: CallbackQuery):
    app_id = int(cb.data.split("_")[3])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Выборочно", callback_data=f"seller_single_{app_id}")],
        [InlineKeyboardButton(text="📅 Диапазон", callback_data=f"seller_range_add_{app_id}")],
        [InlineKeyboardButton(text="📅 +N дней", callback_data=f"seller_days_add_{app_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"seller_calendar_{app_id}")]
    ])
    await cb.message.edit_text("Выберите способ добавления:", reply_markup=kb)
    await cb.answer()

# Выборочное добавление
@router.callback_query(F.data.startswith("seller_single_"))
async def seller_single_start(cb: CallbackQuery, state: FSMContext):
    app_id = int(cb.data.split("_")[2])
    channels = await get_seller_channels(cb.from_user.id)
    app = next((c for c in channels if c['id'] == app_id), None)
    if not app:
        await cb.answer("Канал не найден", show_alert=True)
        return
    slot_ch_id = await resolve_slot_channel_id(app)
    await state.update_data(channel_id=slot_ch_id, app_id=app_id)
    await cb.message.edit_text("Введите дату в формате ДД-ММ-ГГГГ (например, 01-01-2026):", reply_markup=cancel_keyboard())
    await state.set_state(SellerCalendarStates.waiting_for_date)
    await cb.answer()

@router.message(StateFilter(SellerCalendarStates.waiting_for_date))
async def seller_add_slot_date(m: Message, state: FSMContext):
    date_str = m.text.strip()
    try:
        if '-' in date_str and len(date_str) == 10:
            parts = date_str.split('-')
            if len(parts[0]) == 4:
                slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            elif len(parts[2]) == 4:
                slot_date = datetime.strptime(date_str, "%d-%m-%Y").date()
            else:
                raise ValueError
        else:
            raise ValueError
    except ValueError:
        await m.answer("Неверный формат даты. Введите ДД-ММ-ГГГГ (например, 01-01-2026).")
        return
    data = await state.get_data()
    ch_id = data.get('channel_id')
    app_id = data.get('app_id')
    if not ch_id:
        await m.answer("Ошибка: потерян ID канала.")
        await state.clear()
        return
    try:
        await set_slot(str(ch_id), m.from_user.id, slot_date, "free")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить ещё слот", callback_data=f"seller_single_{app_id}")],
            [InlineKeyboardButton(text="🔙 В календарь", callback_data=f"seller_calendar_{app_id}")]
        ])
        await m.answer(f"✅ Слот {slot_date.strftime('%d-%m-%Y')} добавлен как свободный.", reply_markup=kb)
    except Exception as e:
        await m.answer(f"❌ Не удалось добавить слот: {e}")
    finally:
        await state.clear()

# Диапазон
@router.callback_query(F.data.startswith("seller_range_add_"))
async def seller_range_start(cb: CallbackQuery, state: FSMContext):
    app_id = int(cb.data.split("_")[3])
    channels = await get_seller_channels(cb.from_user.id)
    app = next((c for c in channels if c['id'] == app_id), None)
    if not app:
        await cb.answer("Канал не найден", show_alert=True)
        return
    slot_ch_id = await resolve_slot_channel_id(app)
    await state.update_data(channel_id=slot_ch_id)
    await cb.message.edit_text("📅 Введите начальную и конечную дату через тире (напр. 01-01-2026 – 31-01-2026):", reply_markup=cancel_keyboard())
    await state.set_state(SlotRangeStates.waiting_for_range)
    await cb.answer()

@router.message(StateFilter(SlotRangeStates.waiting_for_range))
async def seller_range_process(m: Message, state: FSMContext):
    text = m.text.strip()
    sep = '–' if '–' in text else '-'
    parts = text.split(sep)
    if len(parts) != 2:
        await m.answer("Нужно две даты, разделённые тире.")
        return
    try:
        start_date = datetime.strptime(parts[0].strip(), "%d-%m-%Y").date()
        end_date = datetime.strptime(parts[1].strip(), "%d-%m-%Y").date()
    except ValueError:
        try:
            start_date = datetime.strptime(parts[0].strip(), "%Y-%m-%d").date()
            end_date = datetime.strptime(parts[1].strip(), "%Y-%m-%d").date()
        except ValueError:
            await m.answer("Неверный формат даты.")
            return
    if start_date > end_date:
        await m.answer("Начальная дата должна быть раньше конечной.")
        return
    data = await state.get_data()
    ch_id = data.get('channel_id')
    if not ch_id:
        await m.answer("Ошибка: потерян ID канала.")
        await state.clear()
        return
    added, skipped = 0, 0
    current = start_date
    while current <= end_date:
        exists = any(s['date'] == current.isoformat() for s in await get_channel_slots(str(ch_id)))
        if exists:
            skipped += 1
        else:
            try:
                await set_slot(str(ch_id), m.from_user.id, current, "free")
                added += 1
            except Exception:
                skipped += 1
        current += timedelta(days=1)
    await state.clear()
    await m.answer(f"✅ Готово! Добавлено {added} слотов, пропущено {skipped} (уже существуют).")

# +N дней
@router.callback_query(F.data.startswith("seller_days_add_"))
async def seller_days_start(cb: CallbackQuery, state: FSMContext):
    app_id = int(cb.data.split("_")[3])
    channels = await get_seller_channels(cb.from_user.id)
    app = next((c for c in channels if c['id'] == app_id), None)
    if not app:
        await cb.answer("Канал не найден", show_alert=True)
        return
    slot_ch_id = await resolve_slot_channel_id(app)
    await state.update_data(channel_id=slot_ch_id)
    await cb.message.edit_text("📅 Введите количество дней (напр. 30):", reply_markup=cancel_keyboard())
    await state.set_state(SlotRangeStates.waiting_for_days_count)
    await cb.answer()

@router.message(StateFilter(SlotRangeStates.waiting_for_days_count))
async def seller_days_process(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Введите целое число дней.")
        return
    days = int(m.text)
    if days <= 0 or days > 365:
        await m.answer("Введите число от 1 до 365.")
        return
    data = await state.get_data()
    ch_id = data.get('channel_id')
    if not ch_id:
        await m.answer("Ошибка: потерян ID канала.")
        await state.clear()
        return
    start_date = datetime.now().date() + timedelta(days=1)
    added, skipped = 0, 0
    for i in range(days):
        current = start_date + timedelta(days=i)
        exists = any(s['date'] == current.isoformat() for s in await get_channel_slots(str(ch_id)))
        if exists:
            skipped += 1
        else:
            try:
                await set_slot(str(ch_id), m.from_user.id, current, "free")
                added += 1
            except Exception:
                skipped += 1
    await state.clear()
    await m.answer(f"✅ Готово! Добавлено {added} слотов, пропущено {skipped} (уже существуют).")


@router.callback_query(F.data.startswith("seller_analytics_"))
async def seller_analytics(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) == 3:
        days = 7
        app_id = int(parts[2])
    elif len(parts) >= 4:
        days = int(parts[2])
        app_id = int(parts[3])
    else:
        await cb.answer("Некорректные данные", show_alert=True)
        return
    channels = await get_seller_channels(cb.from_user.id)
    app = next((c for c in channels if c['id'] == app_id), None)
    if not app:
        await cb.answer("Канал не найден", show_alert=True)
        return
    try:
        if app['status'] == 'approved':
            await _load_channels_from_db()
            catalog_id = await get_catalog_channel_id_by_url(app['channel_url'])
            if not catalog_id:
                await cb.answer("Канал не найден в каталоге.", show_alert=True)
                return
            stats_channel_id = catalog_id
        else:
            stats_channel_id = str(app['id'])
        stats = await get_seller_channel_stats(stats_channel_id, cb.from_user.id, days=days)
        text = f"📊 Аналитика канала\n\nДоход по дням (за {days} дн.):\n"
        if stats:
            for day in stats:
                text += f"{day['day']}: {day['orders']} зак., {day['revenue']}$\n"
        else:
            text += "Нет данных за выбранный период."
        kb = get_seller_analytics_keyboard(app_id)
        try:
            await cb.message.edit_text(text, reply_markup=kb)
        except Exception as e:
            if "message is not modified" in str(e):
                await cb.answer("Данные не изменились.", show_alert=True)
            else:
                raise
        await cb.answer()
    except Exception as e:
        import traceback
        traceback.print_exc()
        await cb.answer("Не удалось загрузить аналитику.", show_alert=True)
