"""
DB Layer — работа с SQLite.

Модули:
  subscription_manager — пользователи, подписки, simulated_trades, user_settings
  watchlist_manager    — watchlist пар пользователя (max 20/user)

Использование:
  from core.db import SubscriptionManager, WatchlistManager
  from core.db.subscription_manager import SubscriptionManager
"""
from core.db.subscription_manager import SubscriptionManager
from core.db.watchlist_manager import WatchlistManager

__all__ = ["SubscriptionManager", "WatchlistManager"]
