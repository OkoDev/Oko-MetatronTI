"""
Confluence Layer — детекторы совпадения сигналов.

Модули:
  confluence_scanner       — поиск confluence паттернов по парам
  confluence_state_machine — state machine для отслеживания confluence

Использование:
  from core.confluence import confluence_scanner
  from core.confluence.confluence_scanner import ConfluenceScanner
"""
__all__ = ["confluence_scanner", "confluence_state_machine"]
