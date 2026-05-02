from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import aiohttp
import asyncio

from database import (get_or_create_user, get_user_daily_info, get_orders_by_user,
                      get_user_balance, update_user_balance, debit_balance,
                      get_order_by_id, update_order_status, return_balance,
                      get_user_transactions, process_pending_orders,
                      get_referral_stats, save_order)
from states import OrderForm, WithdrawStates
from texts import (PROFILE_TEMPLATE, DEPOSIT_PROMPT, MIN_DEPOSIT_ERROR,
                   CHECK_PAYMENT_MESSAGE, WITHDRAW_MIN)
from keyboards import (get_profile_keyboard, get_main_keyboard, cancel_keyboard)
from config import MIN_DEPOSIT, PAID_BTN_URL, CRYPTO_BOT_TOKEN, XROCKET_API_KEY, ADMIN_IDS, ORDER_CHANNEL_ID

router = Router()

# ---------- Профиль ----------
@router.message(F.text == "👤 Мой профиль")
async def profile(m: Message):
    try:
        user = await get_or_create_user(m.from_user.id, m.from_user.username or "")
        daily_limit, daily_used = 0, 0
        try:
            daily_limit, daily_used = await get_user_daily_info(m.from_user.id)
        except Exception:
            pass
        left_orders = max(daily_limit - daily_used, 0) if daily_limit > 0 else "∞"

        total_spent = 0
        total_orders = 0
        try:
            completed_orders = await get_orders_by_user(m.from_user.id, limit=1000, only_completed=True)
            total_spent = sum(o['total'] for o in completed_orders)
            total_orders = len(completed_orders)
        except Exception:
            pass

        ref_stats = await get_referral_stats(m.from_user.id)

        txt = PROFILE_TEMPLATE.format(
            user_id=m.from_user.id,
            username=m.from_user.username or 'не указан',
            total_orders=total_orders,
            total_spent=total_spent,
            balance=user.get('balance', 0),
            left_orders=left_orders,
            daily_limit=daily_limit if daily_limit > 0 else '∞',
            invited=ref_stats['invited'],
            referral_bonuses=ref_stats['bonuses']
        )
        await m.answer(txt, reply_markup=get_profile_keyboard())
    except Exception as e:
        await m.answer(f"❌ Ошибка загрузки профиля: {e}", reply_markup=get_main_keyboard(m.from_user.id))

# ---------- Реферальная программа ----------
@router.callback_query(F.data == "referral_program")
async def referral_program(cb: CallbackQuery):
    user = await get_or_create_user(cb.from_user.id)
    code = user.get('referral_code')
    if not code:
        code = f"REF{cb.from_user.id}"
        try:
            from database import update_user_referral_code
            await update_user_referral_code(cb.from_user.id, code)
            user['referral_code'] = code
        except Exception as e:
            print(f"Не удалось обновить referral_code: {e}")
    stats = await get_referral_stats(cb.from_user.id)
    bot = await cb.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{code}"
    text = (
        f"👥 Реферальная программа\n\n"
        f"🔗 Ваша ссылка:\n{link}\n\n"
        f"👥 Приглашено всего: {stats['invited']}\n"
        f"   ├ 1-10 чел. → 1%\n"
        f"   ├ 11-50 чел. → 2%\n"
        f"   └ 51+ чел. → 3.5%\n\n"
        f"💰 Заработано за всё время: {stats['bonuses']}$\n"
        f"💳 Доступно к выводу: {user['balance']}$\n\n"
        "Приглашайте друзей и получайте до 3.5% от их заказов!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw_start")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(cb: CallbackQuery):
    await profile(cb.message)
    await cb.answer()

# ---------- Вывод средств ----------
@router.callback_query(F.data == "withdraw_start")
async def withdraw_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        f"{WITHDRAW_MIN}\nВведите сумму:",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(WithdrawStates.waiting_for_amount)
    await cb.answer()

@router.message(WithdrawStates.waiting_for_amount)
async def withdraw_amount(m: Message, state: FSMContext):
    text = m.text.strip()
    try:
        amount = float(text)
    except ValueError:
        await m.answer("Введите число (например, 5, 10, 25.5).")
        return
    if amount < 5:
        await m.answer(WITHDRAW_MIN)
        return
    balance = await get_user_balance(m.from_user.id)
    if amount > balance:
        await m.answer(f"Недостаточно средств. Ваш баланс: {balance}$")
        return
    await state.update_data(amount=amount)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 На счёт бота", callback_data="withdraw_to_balance")],
        [InlineKeyboardButton(text="💵 На криптокошелёк", callback_data="withdraw_crypto")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_profile")]
    ])
    await m.answer("Выберите способ вывода:", reply_markup=kb)
    await state.set_state(WithdrawStates.waiting_for_method)

@router.callback_query(F.data == "withdraw_to_balance", WithdrawStates.waiting_for_method)
async def withdraw_to_balance(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    amount = data['amount']
    await cb.message.edit_text(
        f"✅ {amount}$ зачислено на ваш баланс.",
        reply_markup=get_profile_keyboard()
    )
    await state.clear()
    await cb.answer()

@router.callback_query(F.data == "withdraw_crypto", WithdrawStates.waiting_for_method)
async def withdraw_crypto(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    amount = data['amount']
    user = await get_or_create_user(cb.from_user.id)
    username = user.get('username', '')
    if not username:
        await cb.message.edit_text(
            "❌ Для вывода на криптокошелёк необходимо установить @username в Telegram.\n"
            "Установите его в настройках и попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
            ])
        )
        await state.clear()
        await cb.answer()
        return
    # Создаём заявку на вывод
    order_id = await save_order(
        cb.from_user.id,
        username,
        [],
        amount,
        amount,
        f"Вывод реферальных бонусов на криптокошелёк. Связь: @{username}",
        status='вывод'
    )
    await debit_balance(cb.from_user.id, amount, order_id, f"Вывод реферальных бонусов #{order_id}")
    # Уведомление админам
    for aid in ADMIN_IDS:
        try:
            await cb.bot.send_message(
                aid,
                f"💰 Заявка на вывод #{order_id}\n"
                f"Пользователь: @{username} ({cb.from_user.id})\n"
                f"Сумма: {amount}$\n"
                f"Контакт: @{username}"
            )
        except:
            pass
    # Уведомление в канал заказов
    if ORDER_CHANNEL_ID:
        try:
            await cb.bot.send_message(
                ORDER_CHANNEL_ID,
                f"💰 Новая заявка на вывод #{order_id}\n"
                f"Пользователь: @{username}\n"
                f"Сумма: {amount}$"
            )
        except:
            pass
    await cb.message.edit_text(
        f"✅ Заявка на вывод {amount}$ создана. Ожидайте выплаты.",
        reply_markup=get_profile_keyboard()
    )
    await state.clear()
    await cb.answer()

# ---------- История транзакций ----------
@router.callback_query(F.data == "transaction_history")
async def transaction_history(cb: CallbackQuery):
    transactions = await get_user_transactions(cb.from_user.id, limit=10)
    if not transactions:
        await cb.message.edit_text(
            "📜 История пуста.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
            ])
        )
        await cb.answer()
        return
    text = "📜 Последние операции:\n\n"
    for t in transactions:
        emoji = "🟢" if t['type'] in ('пополнение', 'реферальный бонус') else "🔴"
        text += f"{emoji} {t['amount']}$ — {t['description']}\n   {t['created_at']}\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

# ---------- Пополнение баланса (с повторами и таймаутами) ----------
@router.callback_query(F.data == "deposit")
async def deposit_menu(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 CryptoBot", callback_data="deposit_crypto")],
        [InlineKeyboardButton(text="💎 XRocket", callback_data="deposit_xrocket")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")]
    ])
    await cb.message.edit_text("Выберите способ пополнения:", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "deposit_crypto")
async def deposit_crypto_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        DEPOSIT_PROMPT.format(min_deposit=MIN_DEPOSIT),
        reply_markup=cancel_keyboard()
    )
    await state.set_state(OrderForm.waiting_for_deposit_amount)
    await state.update_data(payment_method='crypto')
    await cb.answer()

@router.callback_query(F.data == "deposit_xrocket")
async def deposit_xrocket_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        DEPOSIT_PROMPT.format(min_deposit=MIN_DEPOSIT),
        reply_markup=cancel_keyboard()
    )
    await state.set_state(OrderForm.waiting_for_deposit_amount)
    await state.update_data(payment_method='xrocket')
    await cb.answer()

@router.callback_query(F.data == "cancel_add_channel", OrderForm.waiting_for_deposit_amount)
@router.callback_query(F.data == "cancel_add_channel", WithdrawStates.waiting_for_amount)
async def cancel_deposit(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("👤 Мой профиль", reply_markup=get_profile_keyboard())
    await cb.answer()

@router.message(OrderForm.waiting_for_deposit_amount)
async def process_deposit_amount(m: Message, state: FSMContext):
    text = m.text.strip()
    try:
        amount = float(text)
    except ValueError:
        await m.answer("Пожалуйста, введите число (например, 0.5 или 10).")
        return

    if amount < MIN_DEPOSIT:
        await m.answer(MIN_DEPOSIT_ERROR.format(min_deposit=MIN_DEPOSIT))
        return

    current_state = await state.get_state()
    if current_state == OrderForm.processing_deposit:
        return
    await state.set_state(OrderForm.processing_deposit)

    data = await state.get_data()
    method = data.get('payment_method', 'crypto')

    if method == 'crypto':
        if not CRYPTO_BOT_TOKEN:
            await m.answer("Платёжная система временно недоступна.")
            await state.clear()
            return
        url = "https://pay.crypt.bot/api/createInvoice"
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        payload = {
            "asset": "USDT",
            "amount": str(amount),
            "description": f"Пополнение баланса user_id:{m.from_user.id}",
            "paid_btn_name": "callback",
            "paid_btn_url": PAID_BTN_URL,
            "hidden_message": f"Спасибо за пополнение, {m.from_user.first_name}!"
        }
    else:  # xrocket
        if not XROCKET_API_KEY:
            await m.answer("Платёжная система временно недоступна.")
            await state.clear()
            return
        url = "https://pay.xrocket.tg/tg-invoices"
        headers = {
            "Rocket-Pay-Key": XROCKET_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "amount": amount,
            "currency": "USDT",
            "description": f"Пополнение баланса user_id:{m.from_user.id}",
            "numPayments": 1,
            "expiredIn": 3600
        }

    # Повторяем запрос до 3 раз при сетевых ошибках
    attempts = 3
    last_error = ""
    async with aiohttp.ClientSession() as session:
        for attempt in range(1, attempts + 1):
            try:
                async with session.post(url, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    data_resp = await resp.json()
                if method == 'crypto':
                    if data_resp.get("ok"):
                        invoice_url = data_resp["result"]["pay_url"]
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="💳 Перейти к оплате", url=invoice_url)],
                            [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
                        ])
                        await m.answer(f"Счёт на {amount}$ создан. Нажмите кнопку для оплаты:", reply_markup=kb)
                        await state.clear()
                        return
                    else:
                        last_error = "Ошибка создания счёта. Попробуйте позже."
                        break
                else:  # xrocket
                    if data_resp.get("success"):
                        invoice_url = data_resp["data"]["link"]
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="💳 Перейти к оплате", url=invoice_url)],
                            [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
                        ])
                        await m.answer(f"Счёт на {amount}$ создан. Нажмите кнопку для оплаты:", reply_markup=kb)
                        await state.clear()
                        return
                    else:
                        last_error = data_resp.get("message", "Неизвестная ошибка")
                        break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = f"Сетевая ошибка (попытка {attempt}/{attempts})"
                if attempt == attempts:
                    await m.answer("❌ Не удалось связаться с платёжной системой. Попробуйте позже или выберите другой способ.",
                                   reply_markup=get_profile_keyboard())
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                last_error = str(e)
                break
        else:
            await m.answer(f"❌ {last_error}", reply_markup=get_profile_keyboard())
    await state.clear()

@router.callback_query(F.data == "check_payment")
async def check_payment_handler(cb: CallbackQuery):
    await process_pending_orders(cb.from_user.id)
    orders = await get_orders_by_user(cb.from_user.id, limit=5)
    pending = [o for o in orders if o['status'] == 'ожидает оплаты']
    if pending:
        await cb.message.edit_text(
            "У вас есть неоплаченные заказы. Пополните баланс и попробуйте снова.",
            reply_markup=get_profile_keyboard()
        )
    else:
        await cb.message.edit_text(
            CHECK_PAYMENT_MESSAGE,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")]
            ])
        )
    await cb.answer()

# ---------- Заявки пользователя ----------
@router.callback_query(F.data == "my_orders")
async def my_ords(cb: CallbackQuery):
    ords = await get_orders_by_user(cb.from_user.id, 10, only_completed=False)
    if not ords:
        await cb.message.edit_text(
            "📭 У вас пока нет заявок.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
            ])
        )
        await cb.answer()
        return
    txt = "📊 Ваши заявки:\n\n"
    btns = []
    em = {'в обработке':'🟡','оплачена':'🟢','выполнена':'✅','отменена':'❌', 'ожидает оплаты':'🕒', 'вывод':'💰'}
    for o in ords:
        txt += f"🆔 №{o['id']}\n💰 Сумма: {o['total']}$\n📦 Товаров: {len(o['cart'])}\n📌 Статус: {em.get(o['status'],'⚪')} {o['status']}\n🕒 {o['created_at']}\n➖➖➖➖➖\n"
        row = [InlineKeyboardButton(text="📄 Подробнее", callback_data=f"order_details_{o['id']}")]
        if o['status'] in ('в обработке', 'оплачена', 'ожидает оплаты'):
            row.append(InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_order_{o['id']}"))
        btns.append(row)
    btns.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")])
    await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
    await cb.answer()

@router.callback_query(F.data.startswith("order_details_"))
async def order_details(cb: CallbackQuery):
    oid = int(cb.data.split("_")[2])
    ordd = await get_order_by_id(oid)
    if not ordd or ordd['user_id'] != cb.from_user.id:
        await cb.answer("Заявка не найдена", True)
        return
    items = "\n".join(f"• {it['name']} — {it['price']}$" for it in ordd['cart']) if ordd['cart'] else "Заявка на вывод"
    await cb.message.edit_text(
        f"📄 Заявка #{oid}\n📌 Статус: {ordd['status']}\n💰 Сумма: {ordd['total']}$\n\n📦 Состав:\n{items}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="my_orders")]])
    )
    await cb.answer()

@router.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order(cb: CallbackQuery):
    order_id = int(cb.data.split("_")[2])
    ordd = await get_order_by_id(order_id)
    if not ordd or ordd['user_id'] != cb.from_user.id:
        await cb.answer("Заявка не найдена или недоступна", True)
        return
    if ordd['status'] not in ('в обработке', 'оплачена', 'ожидает оплаты'):
        await cb.answer("Эту заявку уже нельзя отменить", True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"confirm_cancel_{order_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="my_orders")]
    ])
    await cb.message.edit_text(
        f"⚠️ Вы уверены, что хотите отменить заявку #{order_id} на сумму {ordd['total']}$?\nДеньги будут возвращены на баланс.",
        reply_markup=kb
    )
    await cb.answer()

@router.callback_query(F.data.startswith("confirm_cancel_"))
async def confirm_cancel(cb: CallbackQuery):
    order_id = int(cb.data.split("_")[2])
    ordd = await get_order_by_id(order_id)
    if not ordd or ordd['user_id'] != cb.from_user.id:
        await cb.answer("Заявка не найдена", True)
        return
    if ordd['status'] not in ('в обработке', 'оплачена', 'ожидает оплаты'):
        await cb.answer("Статус изменился, отмена невозможна", True)
        return
    await update_order_status(order_id, 'отменена')
    if ordd['status'] == 'оплачена':
        await return_balance(ordd['user_id'], ordd['total'], order_id, f"Возврат за отмену заказа #{order_id}")
    await cb.answer("Заявка отменена, деньги возвращены на баланс", False)
    for aid in ADMIN_IDS:
        try:
            await cb.bot.send_message(aid, f"❌ Заявка #{order_id} отменена пользователем @{ordd['username']} (сумма {ordd['total']}$). Деньги возвращены.")
        except: pass
    await my_ords(cb)
