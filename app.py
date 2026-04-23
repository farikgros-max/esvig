import asyncio
import json
import sqlite3
import hashlib
import requests
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Update
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask, request, jsonify

# ========== КОНФИГУРАЦИЯ ==========
# Важно: Убедитесь, что на Railway создана переменная окружения BOT_TOKEN
BOT_TOKEN = "8524671546:AAHMk0g59VhU18p0r5gxYg-r9mVzz83JGmU"
ADMIN_IDS = [7787223469, 7345960167, 714447317, 8614748084]
ITEMS_PER_PAGE = 5
SECRET_TOKEN = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()
# ==================================

# ... (ВСЯ ОСТАЛЬНАЯ ЛОГИКА ВАШЕГО БОТА) ...

# ------------------ FLASK АСИНХРОННЫЕ МАРШРУТЫ ------------------
flask_app = Flask(__name__)
app = flask_app

bot_instance = Bot(token=BOT_TOKEN)
dp_instance = Dispatcher(storage=MemoryStorage())

# Инициализация (выполнится при первом запросе)
app.config['_started'] = False

@app.route('/webhook', methods=['POST'])
async def webhook():
    try:
        # Инициализация при первом запросе
        if not app.config['_started']:
            await load_channels()
            await register_handlers(dp_instance)
            app.config['_started'] = True

        # Проверка секретного токена
        if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET_TOKEN:
            return jsonify({'status': 'unauthorized'}), 401

        update = Update(**request.json)
        await dp_instance.feed_update(bot_instance, update)
    except Exception as e:
        # Логируем ошибку
        print(f"❗️❌ Ошибка в вебхуке: {e}")
    finally:
        # ВСЕГДА возвращаем 200 OK, чтобы Telegram не долбился повторно
        return jsonify({'status': 'ok'})

@app.route('/set_webhook', methods=['GET'])
async def set_webhook():
    domain = os.getenv('WEBHOOK_DOMAIN', 'esvig-production.up.railway.app')
    webhook_url = f"https://{domain}/webhook"
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
        json={"url": webhook_url, "secret_token": SECRET_TOKEN}
    )
    print(f"Webhook set result: {r.json()}")
    return jsonify({'status': 'ok', 'result': r.json()})

# Для gunicorn
application = app
