# -*- coding: utf-8 -*-
"""08.10: `_publish_and_confirm` на уровне модуля звал `_mark`, которая живёт только внутри scan_one —
NameError на КАЖДОМ WT-кроссе и событии комбинатора, скан пары обрывался (~1000 раз в сутки, 3 дня молча)."""


def test_publish_and_confirm_runs_without_scan_one_scope():
    from bot.loops.scan_loop import _publish_and_confirm
    bot = type("B", (), {})()                     # ни шины, ни агрегатора — функция обязана просто вернуться
    _publish_and_confirm(bot, "X/USDT:USDT", "wt_cross_1h", priority=2, data={"direction": "LONG"},
                         conf_source="wt_cross_same_dir", side="LONG", tf="1h")
