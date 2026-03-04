from aiogram.fsm.state import State, StatesGroup


class PivotStates(StatesGroup):
    waiting_for_pivots = State()
    waiting_for_check = State()


class SubscriptionStates(StatesGroup):
    waiting_for_payment = State()


class AIAnalysisStates(StatesGroup):
    waiting_for_symbol = State()
    waiting_for_symbol_search = State()
