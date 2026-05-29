import logging
import time

from aiogram import BaseMiddleware

from config import CHANNEL_ID

logger = logging.getLogger(__name__)

class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self):
        self.channel_id = CHANNEL_ID
        self.cache = {}
        super().__init__()

    async def __call__(self, handler, event, data):
        if not self.channel_id:
            # Если канал не задан, пропускаем проверку
            return await handler(event, data)

        user_id = data["event_from_user"].id
        bot = data["bot"]

        now = time.time()
        if user_id in self.cache and self.cache[user_id][0] > now:
            is_subscribed = self.cache[user_id][1]
        else:
            try:
                member = await bot.get_chat_member(chat_id=self.channel_id, user_id=user_id)
                is_subscribed = member.status not in ('left', 'kicked')
            except Exception:
                is_subscribed = False
            self.cache[user_id] = (now + 300, is_subscribed)

        if not is_subscribed:
            try:
                await bot.send_message(user_id, "❕ Чтобы пользоваться ботом, подпишитесь на канал: https://t.me/esvig_service")
            except Exception:
                pass
            return  # блокируем дальнейшую обработку
        return await handler(event, data)

class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, limit_seconds: float = 1.0):
        self.last_time = {}
        self.limit = limit_seconds
        super().__init__()

    async def __call__(self, handler, event, data):
        user_id = data["event_from_user"].id
        now = time.time()
        if user_id in self.last_time and (now - self.last_time[user_id]) < self.limit:
            return
        self.last_time[user_id] = now
        return await handler(event, data)

# Функция-заглушка для совместимости, если где-то импортируется
async def is_subscribed(bot, user_id, channel_id=None):
    if channel_id is None:
        channel_id = CHANNEL_ID
    if not channel_id:
        return True
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status not in ('left', 'kicked')
    except Exception:
        return False
