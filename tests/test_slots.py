import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
from aiogram.types import CallbackQuery, Message, User, Chat
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from handlers.cart import confirm_order

@pytest.mark.asyncio
async def test_confirm_order_books_slots():
    user = User(id=123, is_bot=False, first_name="Test")
    chat = Chat(id=123, type="private")
    message = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user)

    # Мокаем edit_text на классе Message, чтобы не требовался bot
    with patch.object(Message, 'edit_text', new_callable=AsyncMock) as mock_edit:
        callback = CallbackQuery(
            id="test",
            from_user=user,
            message=message,
            chat_instance="test",
            data="confirm_order"
        )

        with patch('handlers.cart.get_cart', new_callable=AsyncMock) as mock_get_cart, \
             patch('handlers.cart.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('handlers.cart.debit_balance', new_callable=AsyncMock) as mock_debit, \
             patch('handlers.cart.save_order', new_callable=AsyncMock) as mock_save_order, \
             patch('handlers.cart.clear_cart_db', new_callable=AsyncMock), \
             patch('handlers.cart.increment_daily_orders', new_callable=AsyncMock), \
             patch('handlers.cart.book_slot', new_callable=AsyncMock) as mock_book_slot:

            mock_get_cart.return_value = [
                {"id": "ch1", "name": "Channel", "price": 100, "date": "2026-01-01"},
                {"id": "ch1", "name": "Channel", "price": 100, "date": "2026-01-02"}
            ]
            mock_get_user.return_value = {"user_id": 123, "username": "testuser"}
            mock_debit.return_value = True
            mock_save_order.return_value = 42

            storage = MemoryStorage()
            state = FSMContext(storage=storage, key="test")
            await state.set_state(None)

            await confirm_order(callback, state)

            assert mock_book_slot.call_count == 2
            mock_book_slot.assert_any_call("ch1", "2026-01-01", 123)
            mock_book_slot.assert_any_call("ch1", "2026-01-02", 123)
