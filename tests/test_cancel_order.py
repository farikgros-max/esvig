import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime
from aiogram.types import CallbackQuery, Message, User, Chat

@pytest.mark.asyncio
async def test_admin_cancel_releases_slots():
    with patch('handlers.admin.get_order_by_id', new_callable=AsyncMock) as mock_order, \
         patch('handlers.admin.update_order_status', new_callable=AsyncMock), \
         patch('handlers.admin.return_balance', new_callable=AsyncMock), \
         patch('handlers.admin.release_slot', new_callable=AsyncMock) as mock_release, \
         patch('handlers.admin.ADMIN_IDS', [123]), \
         patch('handlers.admin.get_orders', new_callable=AsyncMock) as mock_get_orders, \
         patch.object(CallbackQuery, 'answer', new_callable=AsyncMock) as mock_answer, \
         patch.object(Message, 'edit_text', new_callable=AsyncMock) as mock_edit_text, \
         patch('aiogram.client.bot.Bot.send_message', new_callable=AsyncMock) as mock_send_msg:

        # Мокаем заказ с оплаченным статусом и слотами
        mock_order.return_value = {
            "id": 1,
            "user_id": 999,
            "total": 500,
            "status": "оплачена",
            "cart": [
                {"id": "ch1", "name": "Test", "price": 100, "date": "2026-01-01"},
                {"id": "ch1", "name": "Test", "price": 100, "date": "2026-01-02"}
            ],
            "username": "testuser"
        }
        mock_get_orders.return_value = []

        # Создаём CallbackQuery
        cb = CallbackQuery(
            id="test",
            from_user=User(id=123, is_bot=False, first_name="Admin"),
            message=Message(message_id=1, date=datetime.now(), chat=Chat(id=123, type="private"), from_user=User(id=123, is_bot=False, first_name="Admin")),
            chat_instance="test",
            data="set_status_1_отменена"
        )

        from handlers.admin import set_st
        await set_st(cb)

        # Проверяем, что release_slot вызван дважды
        assert mock_release.call_count == 2
        mock_release.assert_any_call("ch1", "2026-01-01")
        mock_release.assert_any_call("ch1", "2026-01-02")
