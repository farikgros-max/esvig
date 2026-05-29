import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()] if ADMIN_IDS_STR else []
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN", "")
XROCKET_API_KEY = os.getenv("XROCKET_API_KEY", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "0")
ORDER_CHANNEL_ID = os.getenv("ORDER_CHANNEL_ID", "0")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
MIN_DEPOSIT = 5
PAID_BTN_URL = "https://t.me/your_bot"
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "")
ITEMS_PER_PAGE = 5
