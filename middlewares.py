from datetime import datetime, timedelta
from aiogram import BaseMiddleware
from config import CHANNEL_ID

# ---------- Антифлуд ----------
last_message_time = {}

class AntiFloodMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if hasattr(event, 'from_user') and event.from_user:
            user_id = event.from_user.id
            now = datetime.now()
            if user_id in last_message_time:
                elapsed = now - last_message_time[user_id]
                if elapsed < timedelta(seconds=1):
                    return
            last_message_time[user_id] = now
        return await handler(event, data)

# ---------- Проверка подписки ----------
async def is_subscribed(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Получаем объект бота из data
        bot = data.get("bot")
        if hasattr(event, 'from_user') and event.from_user and bot:
            # Пропускаем команды /start и /export
            if event.text and (event.text.startswith("/start") or event.text.startswith("/export")):
                return await handler(event, data)
            if not await is_subscribed(bot, event.from_user.id):
                await event.answer("⚠️ Подпишитесь на канал, чтобы пользоваться ботом: /start")
                return
        return await handler(event, data)
