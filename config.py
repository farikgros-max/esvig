import os
import hashlib

# ---------- Токены и ключи ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан в переменных окружения!")

SECRET_TOKEN = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()

ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
if ADMIN_IDS_STR:
    ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()]
else:
    ADMIN_IDS = [7787223469, 7345960167, 714447317, 8614748084, 8702300149, 8472548724]

CRYPTO_BOT_TOKEN = os.environ.get("CRYPTO_BOT_TOKEN", "")
XROCKET_API_KEY = os.environ.get("XROCKET_API_KEY", "")

# ---------- Настройки бота ----------
ITEMS_PER_PAGE = 5
MIN_DEPOSIT = 0.1
DAILY_ORDER_LIMIT = 3
PAID_BTN_URL = "https://t.me/esvig_bot"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://esvig-production-4961.up.railway.app/webhook")

# ID канала для обязательной подписки
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@esvig_service")

# ID канала для уведомлений о новых заказах (необязательно)
ORDER_CHANNEL_ID = os.environ.get("ORDER_CHANNEL_ID", "")

# База данных
DATABASE_URL = os.environ.get("DATABASE_URL")
