import pytest
from unittest.mock import AsyncMock, patch
from handlers.cart import get_cart, save_cart

@pytest.mark.asyncio
async def test_save_and_load_cart():
    # Мокаем функции базы данных
    with patch('handlers.cart.save_cart_db', new_callable=AsyncMock) as mock_save, \
         patch('handlers.cart.load_cart_db', new_callable=AsyncMock) as mock_load:

        # Настраиваем мок для загрузки
        mock_load.return_value = [{"id": "chan1", "name": "Test", "price": 100}]

        # Сохраняем корзину
        await save_cart(123, [{"id": "chan1", "name": "Test", "price": 100}])
        mock_save.assert_called_once_with(123, [{"id": "chan1", "name": "Test", "price": 100}])

        # Загружаем корзину
        cart = await get_cart(123)
        assert len(cart) == 1
        assert cart[0]["price"] == 100
