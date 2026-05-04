from aiogram.fsm.state import State, StatesGroup

class OrderForm(StatesGroup):
    waiting_for_budget = State()
    waiting_for_contact = State()
    waiting_for_deposit_amount = State()
    processing_deposit = State()

class AddChannelStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_subscribers = State()
    waiting_for_url = State()
    waiting_for_description = State()

class EditChannelStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_subscribers = State()
    waiting_for_url = State()
    waiting_for_description = State()
    waiting_for_category = State()

class AddCategoryStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_display_name = State()

class AdminBalanceStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

class MassAddStates(StatesGroup):
    waiting_for_bulk_json = State()

class QuickAddStates(StatesGroup):
    waiting_for_channel_link = State()
    waiting_for_price = State()
    waiting_for_category = State()

class WithdrawStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_method = State()

class SellerStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_channel_url = State()
    waiting_for_price = State()
    waiting_for_description = State()

class SellerCalendarStates(StatesGroup):
    waiting_for_date = State()

class SellerAnalyticsStates(StatesGroup):
    waiting_for_period = State()
