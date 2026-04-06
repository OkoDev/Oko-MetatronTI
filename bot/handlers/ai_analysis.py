from aiogram.types import Message
from aiogram.fsm.context import FSMContext

# Delegate to existing MenuHandler inside TradingAlertBot for now
async def handle_ai_button(message: Message, state: FSMContext):
    # This is an adapter placeholder. Real logic remains in core.menu_handler.MenuHandler
    await message.answer("AI menu adapter is active. Use main menu to navigate.")
