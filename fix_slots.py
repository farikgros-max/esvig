import re

with open('/root/esvig/database.py', 'r') as f:
    content = f.read()

# Новые реализации функций с универсальным преобразованием даты

new_set_slot = '''async def set_slot(channel_id: str, seller_user_id: int, date_str, status: str = "free"):
    from datetime import date as _date
    if isinstance(date_str, str):
        try:
            date_str = _date.fromisoformat(date_str)
        except ValueError:
            parts = date_str.split('-')
            if len(parts) == 3 and len(parts[0]) == 2:
                date_str = _date(int(parts[2]), int(parts[1]), int(parts[0]))
    conn = await get_connection()
    await conn.execute(\'\'\'INSERT INTO slot_bookings (channel_id, seller_user_id, date, status)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (channel_id, date) DO UPDATE SET status = $4\'\'\',
                        channel_id, seller_user_id, date_str, status)'''

new_delete_slot = '''async def delete_slot(channel_id: str, date_str):
    from datetime import date as _date
    if isinstance(date_str, str):
        try:
            date_str = _date.fromisoformat(date_str)
        except ValueError:
            parts = date_str.split('-')
            if len(parts) == 3 and len(parts[0]) == 2:
                date_str = _date(int(parts[2]), int(parts[1]), int(parts[0]))
    conn = await get_connection()
    await conn.execute("DELETE FROM slot_bookings WHERE channel_id = $1 AND date = $2", channel_id, date_str)'''

new_book_slot = '''async def book_slot(channel_id: str, date_str: str, buyer_user_id: int):
    from datetime import date as _date
    if isinstance(date_str, str):
        try:
            date_str = _date.fromisoformat(date_str)
        except ValueError:
            parts = date_str.split('-')
            if len(parts) == 3 and len(parts[0]) == 2:
                date_str = _date(int(parts[2]), int(parts[1]), int(parts[0]))
    conn = await get_connection()
    await conn.execute(\'\'\'UPDATE slot_bookings SET status = \\'booked\\', booked_by = $3
                        WHERE channel_id = $1 AND date = $2 AND status = \\'free\\' \'\'\',
                        channel_id, date_str, buyer_user_id)'''

new_release_slot = '''async def release_slot(channel_id: str, date_str):
    from datetime import date as _date
    if isinstance(date_str, str):
        try:
            date_str = _date.fromisoformat(date_str)
        except ValueError:
            parts = date_str.split('-')
            if len(parts) == 3 and len(parts[0]) == 2:
                date_str = _date(int(parts[2]), int(parts[1]), int(parts[0]))
    conn = await get_connection()
    await conn.execute("UPDATE slot_bookings SET status = 'free', booked_by = NULL WHERE channel_id = $1 AND date = $2", channel_id, date_str)'''

# Заменяем старые функции на новые
for old, new in [
    (r'async def set_slot\(.*?\):.*?(?=\n(?:async )?def |\Z)', new_set_slot),
    (r'async def delete_slot\(.*?\):.*?(?=\n(?:async )?def |\Z)', new_delete_slot),
    (r'async def book_slot\(.*?\):.*?(?=\n(?:async )?def |\Z)', new_book_slot),
    (r'async def release_slot\(.*?\):.*?(?=\n(?:async )?def |\Z)', new_release_slot),
]:
    content = re.sub(old, new, content, flags=re.DOTALL)

with open('/root/esvig/database.py', 'w') as f:
    f.write(content)

print("Функции успешно обновлены.")
