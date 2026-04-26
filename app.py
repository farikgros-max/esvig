import os
import asyncio
import logging
import hashlib
import hmac
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import (
    BOT_TOKEN, ADMIN_IDS,
    CRYPTO_BOT_TOKEN,
    XROCKET_API_KEY
)

from database import init_db

# handlers
from handlers.start import router as start_router
from handlers.catalog import router as catalog_router
from handlers.cart import router as cart_router
from handlers.profile import router as profile_router
from handlers.admin import router as admin_router
from handlers.info import router as info_router

# middlewares
from middlewares import SubscriptionMiddleware, AntiFloodMiddleware


# ================= LOGGING =================
logging.basicConfig(
    filename="bot_errors.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s:%(message)s"
)


# ================= BOT =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ================= STARTUP =================
async def startup():
    await init_db()

    dp.include_router(start_router)
    dp.include_router(catalog_router)
    dp.include_router(cart_router)
    dp.include_router(profile_router)
    dp.include_router(admin_router)
    dp.include_router(info_router)

    dp.message.middleware(SubscriptionMiddleware())
    dp.message.middleware(AntiFloodMiddleware())
    dp.callback_query.middleware(AntiFloodMiddleware())

    await bot.delete_webhook(drop_pending_updates=True)

    print("✅ Бот запущен (Long Polling)")


# ================= CRYPTOBOT =================
async def cryptobot_handler(request):
    if not CRYPTO_BOT_TOKEN:
        return web.json_response({"status": "disabled"}, status=403)

    body = await request.read()

    secret = hashlib.sha256(CRYPTO_BOT_TOKEN.encode()).digest()
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()

    if request.headers.get("Crypto-Pay-Api-Signature") != signature:
        return web.json_response({"status": "unauthorized"}, status=401)

    try:
        data = await request.json()

        if data.get("update_type") == "invoice_paid":
            invoice = data["payload"]["invoice"]
            desc = invoice.get("description", "")

            user_id = None
            if "user_id:" in desc:
                user_id = int(desc.split("user_id:")[1])

            if user_id:
                amount = int(float(invoice["amount"]))

                from database import update_balance
                await update_balance(user_id, amount)

                try:
                    await bot.send_message(user_id, f"✅ Баланс пополнен на {amount}$")
                except Exception:
                    pass

                for admin in ADMIN_IDS:
                    try:
                        await bot.send_message(admin, f"💰 Пополнение {amount}$ от {user_id}")
                    except Exception:
                        pass

    except Exception as e:
        logging.error(f"CryptoBot error: {e}")

    return web.json_response({"status": "ok"})


# ================= XROCKET =================
async def xrocket_handler(request):
    if not XROCKET_API_KEY:
        return web.json_response({"status": "disabled"}, status=403)

    if request.headers.get("X-API-Key") != XROCKET_API_KEY:
        return web.json_response({"status": "unauthorized"}, status=401)

    try:
        data = await request.json()

        if data.get("status") == "paid":
            invoice = data.get("invoice", {})
            desc = invoice.get("description", "")

            user_id = None
            if "user_id:" in desc:
                user_id = int(desc.split("user_id:")[1])

            if user_id:
                amount = int(float(invoice.get("amount", 0)))

                from database import update_balance
                await update_balance(user_id, amount)

                try:
                    await bot.send_message(user_id, f"✅ Баланс пополнен на {amount}$")
                except Exception:
                    pass

                for admin in ADMIN_IDS:
                    try:
                        await bot.send_message(admin, f"💰 Пополнение {amount}$ от {user_id}")
                    except Exception:
                        pass

    except Exception as e:
        logging.error(f"XRocket error: {e}")

    return web.json_response({"status": "ok"})


# ================= MAIN =================
async def main():
    await startup()

    app = web.Application()
    app.router.add_post("/cryptobot", cryptobot_handler)
    app.router.add_post("/xrocket", xrocket_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 8080))

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"🌐 Webhook сервер запущен на порту {port}")

    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
