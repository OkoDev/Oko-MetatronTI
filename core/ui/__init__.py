"""
UI Layer — форматирование и вывод сообщений.

Модули:
  message_builder       — TV-ссылки, форматирование символов, anomaly/wt сообщения
  message_composer      — composer паттерн для сборки сообщений
  intelligence_formatter — форматирование TradingRecommendation → HTML
  chart_builder         — построение ASCII/image чартов

Использование:
  from core.ui import intelligence_formatter
  from core.ui.message_builder import tv_link, anomaly_message
  from core.ui.intelligence_formatter import format_recommendation
"""
__all__ = ["message_builder", "message_composer", "intelligence_formatter", "chart_builder"]
