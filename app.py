import os
import asyncio
import logging
import hashlib
import hmac
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import (BOT_TOKEN, ADMIN_IDS, CRYPTO_BOT_TOKEN, XROCKET_API_KEY,
                    WEBHOOK_URL, SECRET_TOKEN, CHANNEL_ID, ORDER_CHANNEL_ID)
from database import init_db, update_user_balance
from middlewares import SubscriptionMiddleware, AntiFloodMiddleware

# Импорт роутеров
from handlers.start import router as start_router
from handlers.catalog import router as catalog_router
from handlers.cart import router as cart_router
from handlers.profile import router as profile_router
from handlers.admin import router as admin_router
from handlers.info import router as info_router
from handlers.referral import router as referral_router  # новый

logging.basicConfig(
    filename='bot_errors.log',
    level=logging.ERROR,
    format='%(asctime)s %(levelname)s:%(message)s'
)

# Инициализация бота
bot_instance = Bot(token=BOT_TOKEN)
dp_instance = Dispatcher(storage=MemoryStorage())

async def startup():
    await init_db()
    # Подключаем роутеры
    dp_instance.include_router(start_router)
    dp_instance.include_router(catalog_router)
    dp_instance.include_router(cart_router)
    dp_instance.include_router(profile_router)
    dp_instance.include_router(admin_router)
    dp_instance.include_router(info_router)
    dp_instance.include_router(referral_router)   # подключаем реферальный
    # Middleware
    dp_instance.message.middleware(SubscriptionMiddleware())
    dp_instance.message.middleware(AntiFloodMiddleware())
    dp_instance.callback_query.middleware(AntiFloodMiddleware())
    # Удаляем вебхук и очищаем очередь
    await bot_instance.delete_webhook(drop_pending_updates=True)
    try:
        updates = await bot_instance.get_updates(offset=-1, limit=100, timeout=1)
        if updates:
            max_update_id = max(u.update_id for u in updates)
            await bot_instance.get_updates(offset=max_update_id + 1)
    except Exception:
        pass
    print("Бот готов (Long Polling)")

# Платёжные вебхуки (если нужны)
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

async def main():
    await startup()
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
