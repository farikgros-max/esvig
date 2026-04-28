import logging
import os
from aiogram.types import Message, CallbackQuery
from config import ADMIN_IDS

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id in ADMIN_IDS

async def admin_only_message(m: Message) -> bool:
    """Отвечает пользователю, если он не админ."""
    if not is_admin(m.from_user.id):
        await m.answer("Нет прав")
        return False
    return True

async def admin_only_callback(cb: CallbackQuery, show_alert: bool = True) -> bool:
    """Обрабатывает callback, если пользователь не админ."""
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет прав", show_alert=show_alert)
        return False
    return True

def safe_get(data: dict, key: str, default=None):
    """Безопасно извлекает значение из словаря."""
    return data.get(key, default) or default

def log_admin_action(user_id: int, action: str):
    """Логирует действие администратора."""
    logging.getLogger('admin_actions').info(f"Admin {user_id}: {action}")

def trim_admin_log():
    """Оставляет последние 200 строк в лог-файле администратора."""
    log_file = 'admin_actions.log'
    if not os.path.exists(log_file):
        return
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        if len(lines) > 200:
            with open(log_file, 'w', encoding='utf-8') as f:
                f.writelines(lines[-200:])
    except Exception as e:
        print(f"Ошибка при обрезке логов: {e}")
