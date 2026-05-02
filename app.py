import os
import asyncio
import logging
import hashlib
import hmac
from aiohttp import web
from logging.handlers import RotatingFileHandler
from datetime import datetime

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

from config import (BOT_TOKEN, ADMIN_IDS, CRYPTO_BOT_TOKEN, XROCKET_API_KEY,
                    WEBHOOK_URL, SECRET_TOKEN, CHANNEL_ID, ORDER_CHANNEL_ID)
from database import init_db, update_user_balance, auto_process_orders, get_connection, close_db, backup_database
from middlewares import SubscriptionMiddleware, AntiFloodMiddleware
from utils import trim_admin_log

# Ротация логов
logging.basicConfig(
    handlers=[RotatingFileHandler('bot_errors.log', maxBytes=1_000_000, backupCount=3)],
    level=logging.ERROR,
    format='%(asctime)s %(levelname)s %(name)s:%(message)s'
)

bot_instance = Bot(token=BOT_TOKEN, proxy="http://127.0.0.1:3128")
dp_instance = Dispatcher(storage=MemoryStorage())

# ---------- Глобальный перехватчик ошибок ----------
class ErrorMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as e:
            logging.error(f"Unhandled error: {e}", exc_info=True)
            if hasattr(event, 'answer'):
                await event.answer("⚠️ Произошла ошибка. Попробуйте позже.")
            elif hasattr(event, 'message') and hasattr(event.message, 'answer'):
                await event.message.answer("⚠️ Произошла ошибка. Попробуйте позже.")

async def startup():
    await init_db()
    # Роутеры
    from handlers.start import router as start_router
    from handlers.catalog import router as catalog_router
    from handlers.cart import router as cart_router
    from handlers.profile import router as profile_router
    from handlers.admin import router as admin_router
    from handlers.info import router as info_router
    from handlers.seller import router as seller_router

    dp_instance.include_router(start_router)
    dp_instance.include_router(catalog_router)
    dp_instance.include_router(cart_router)
    dp_instance.include_router(profile_router)
    dp_instance.include_router(admin_router)
    dp_instance.include_router(info_router)
    dp_instance.include_router(seller_router)

    # Middleware
    dp_instance.message.middleware(ErrorMiddleware())
    dp_instance.callback_query.middleware(ErrorMiddleware())
    dp_instance.message.middleware(SubscriptionMiddleware())
    dp_instance.message.middleware(AntiFloodMiddleware())
    dp_instance.callback_query.middleware(AntiFloodMiddleware())

    await bot_instance.delete_webhook(drop_pending_updates=True)
    try:
        updates = await bot_instance.get_updates(offset=-1, limit=100, timeout=1)
        if updates:
            max_update_id = max(u.update_id for u in updates)
            await bot_instance.get_updates(offset=max_update_id + 1)
    except Exception:
        pass
    print("Бот готов (Long Polling)")

# ---------- Фоновая проверка здоровья и очистка логов ----------
async def db_health_check():
    last_trim = 0
    while True:
        try:
            conn = await get_connection()
            await asyncio.wait_for(conn.execute('SELECT 1'), timeout=5)
        except (asyncio.TimeoutError, Exception) as e:
            print(f"[HEALTH] Проблема с БД: {e}")
            await close_db()

        now = asyncio.get_event_loop().time()
        if now - last_trim > 3600:
            trim_admin_log()
            last_trim = now

        await asyncio.sleep(300)

# Пинг-команда
from aiogram.filters import Command
@dp_instance.message(Command("ping"))
async def ping(m):
    try:
        conn = await get_connection()
        await conn.execute('SELECT 1')
        await m.answer("🟢 Бот работает, БД доступна")
    except Exception:
        await m.answer("🔴 Проблема с базой данных")

# Вебхуки (без изменений)
async def cryptobot_handler(request):
    if not CRYPTO_BOT_TOKEN:
        return web.json_response({'status': 'error'}, status=403)
    body = await request.read()
    secret = hashlib.sha256(CRYPTO_BOT_TOKEN.encode()).digest()
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if request.headers.get('Crypto-Pay-Api-Signature') != signature:
        return web.json_response({'status': 'unauthorized'}, status=401)
    try:
        data = await request.json()
        if data.get('update_type') == 'invoice_paid':
            payload = data['payload']
            invoice = payload['invoice']
            desc = invoice.get('description', '')
            user_id = int(desc.split("user_id:")[1]) if "user_id:" in desc else None
            if user_id:
                amount = int(float(invoice['amount']))
                await update_user_balance(user_id, amount, f"Пополнение CryptoBot {amount}$")
                try:
                    await bot_instance.send_message(user_id, f"✅ Ваш баланс пополнен на {amount}$. Спасибо!")
                except: pass
                for aid in ADMIN_IDS:
                    try:
                        await bot_instance.send_message(aid, f"💰 Пользователь {user_id} пополнил баланс на {amount}$ через CryptoBot")
                    except: pass
    except Exception as e:
        print(f"CryptoBot webhook error: {e}")
    return web.json_response({'status': 'ok'})

async def xrocket_handler(request):
    if not XROCKET_API_KEY:
        return web.json_response({'status': 'error'}, status=403)
    if request.headers.get('X-API-Key') != XROCKET_API_KEY:
        return web.json_response({'status': 'unauthorized'}, status=401)
    try:
        data = await request.json()
        if data.get('status') == 'paid':
            invoice = data.get('invoice', {})
            desc = invoice.get('description', '')
            user_id = int(desc.split("user_id:")[1]) if "user_id:" in desc else None
            if user_id:
                amount = int(float(invoice.get('amount', 0)))
                await update_user_balance(user_id, amount, f"Пополнение XRocket {amount}$")
                try:
                    await bot_instance.send_message(user_id, f"✅ Ваш баланс пополнен на {amount}$. Спасибо!")
                except: pass
                for aid in ADMIN_IDS:
                    try:
                        await bot_instance.send_message(aid, f"💰 Пользователь {user_id} пополнил баланс на {amount}$ через XRocket")
                    except: pass
    except Exception as e:
        print(f"XRocket webhook error: {e}")
    return web.json_response({'status': 'ok'})

async def daily_backup_task(bot: Bot):
    """Ежедневный бэкап базы данных. Хранит 7 последних копий."""
    backup_dir = "/opt/esvig/backups"
    os.makedirs(backup_dir, exist_ok=True)
    while True:
        await asyncio.sleep(86400)  # раз в сутки
        try:
            filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(backup_dir, filename)
            await backup_database(filepath)
            print(f"[BACKUP] Создан бэкап: {filepath}")
            for aid in ADMIN_IDS:
                try:
                    await bot.send_message(aid, f"📦 Ежедневный бэкап базы данных создан ({filename})")
                except:
                    pass
            # Удаляем старые бэкапы (оставляем 7 последних)
            files = sorted(
                [f for f in os.listdir(backup_dir) if f.endswith('.json')],
                key=lambda x: os.path.getmtime(os.path.join(backup_dir, x))
            )
            while len(files) > 7:
                old_file = files.pop(0)
                os.remove(os.path.join(backup_dir, old_file))
                print(f"[BACKUP] Удалён старый бэкап: {old_file}")
        except Exception as e:
            logging.error(f"Ошибка ежедневного бэкапа: {e}")

async def main():
    await startup()
    asyncio.create_task(auto_process_orders(bot_instance))
    asyncio.create_task(db_health_check())

    # Импортируем и запускаем ежедневное обновление подписчиков
    from handlers.admin import daily_subscriber_update
    asyncio.create_task(daily_subscriber_update(bot_instance))

    # Запуск ежедневного бэкапа
    asyncio.create_task(daily_backup_task(bot_instance))

    aio_app = web.Application()
    aio_app.router.add_post('/cryptobot', cryptobot_handler)
    aio_app.router.add_post('/xrocket', xrocket_handler)
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await site.start()
    print(f"Платёжный HTTP-сервер запущен на порту {os.environ.get('PORT', 8080)}")
    await dp_instance.start_polling(bot_instance, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
