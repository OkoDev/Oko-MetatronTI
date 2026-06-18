"""
Notification Engine — TG-меню управления уведомлениями.

Команды:  /notif
Callback: notif:rules | notif:pause | notif:resume | notif:stats | notif:reload
          notif_toggle:<rule_name>
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from core.notifications.notif_config import notif_config

logger = logging.getLogger(__name__)

_TIER_EMOJI = {1: "🔥", 2: "📍"}
_DIR_MAP = {"LONG": "🟢", "SHORT": "🔴"}


def _rules_keyboard() -> InlineKeyboardMarkup:
    """Inline-клавиатура: список правил с кнопкой toggle для каждого."""
    rows = []
    for rule in notif_config.rules_summary():
        name = rule["name"]
        on = rule["enabled"]
        label_parts = [
            "✅" if on else "⬜",
            _TIER_EMOJI.get(rule["tier"], "•"),
            name,
        ]
        if rule["symbols"]:
            label_parts.append(f"[{','.join(rule['symbols'])}]")
        if rule["directions"]:
            label_parts.append(" ".join(_DIR_MAP.get(d, d) for d in rule["directions"]))
        if rule["tf"]:
            label_parts.append("/".join(rule["tf"]))
        rows.append([InlineKeyboardButton(
            text=" ".join(label_parts),
            callback_data=f"notif_toggle:{name}",
        )])
    rows.append([
        InlineKeyboardButton(text="🔄 Reload YAML", callback_data="notif:reload"),
        InlineKeyboardButton(text="« Назад", callback_data="notif:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _main_keyboard() -> InlineKeyboardMarkup:
    paused = notif_config.is_paused()
    pause_btn = InlineKeyboardButton(
        text="▶️ Резюме" if paused else "⏸ Пауза",
        callback_data="notif:resume" if paused else "notif:pause",
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Мои правила", callback_data="notif:rules"),
            InlineKeyboardButton(text="📊 Статистика",  callback_data="notif:stats"),
        ],
        [pause_btn],
    ])


def _main_text() -> str:
    paused = notif_config.is_paused()
    fired = notif_config.fired_count()
    status = "⏸ <b>ПАУЗА</b>" if paused else "✅ <b>Активны</b>"
    total = sum(1 for r in notif_config.rules_summary() if r["enabled"])
    return (
        f"🔔 <b>Уведомления</b>\n\n"
        f"Статус: {status}\n"
        f"Активных правил: {total}\n"
        f"За последний час: {fired}"
    )


def get_router(bot) -> Router:
    router = Router()

    # ── /notif ────────────────────────────────────────────────────────────
    @router.message(Command("notif"))
    async def cmd_notif(message: Message):
        await message.answer(_main_text(), reply_markup=_main_keyboard(), parse_mode="HTML")

    # ── callbacks ─────────────────────────────────────────────────────────
    @router.callback_query(F.data == "notif:main")
    async def cb_main(cb: CallbackQuery):
        await cb.message.edit_text(_main_text(), reply_markup=_main_keyboard(), parse_mode="HTML")
        await cb.answer()

    @router.callback_query(F.data == "notif:rules")
    async def cb_rules(cb: CallbackQuery):
        await cb.message.edit_text(
            "📋 <b>Правила уведомлений</b>\n"
            "Нажми на правило чтобы включить/выключить:",
            reply_markup=_rules_keyboard(),
            parse_mode="HTML",
        )
        await cb.answer()

    @router.callback_query(F.data == "notif:pause")
    async def cb_pause(cb: CallbackQuery):
        notif_config.set_paused(True)
        await cb.message.edit_text(_main_text(), reply_markup=_main_keyboard(), parse_mode="HTML")
        await cb.answer("⏸ Уведомления на паузе")

    @router.callback_query(F.data == "notif:resume")
    async def cb_resume(cb: CallbackQuery):
        notif_config.set_paused(False)
        await cb.message.edit_text(_main_text(), reply_markup=_main_keyboard(), parse_mode="HTML")
        await cb.answer("▶️ Уведомления возобновлены")

    @router.callback_query(F.data == "notif:stats")
    async def cb_stats(cb: CallbackQuery):
        fired = notif_config.fired_count()
        rules = notif_config.rules_summary()
        on = [r["name"] for r in rules if r["enabled"]]
        off = [r["name"] for r in rules if not r["enabled"]]
        text = (
            f"📊 <b>Статистика уведомлений</b>\n\n"
            f"За последний час: <b>{fired}</b>\n\n"
            f"Включено ({len(on)}):\n" +
            ("\n".join(f"  ✅ {n}" for n in on) or "  —") +
            f"\n\nВыключено ({len(off)}):\n" +
            ("\n".join(f"  ⬜ {n}" for n in off) or "  —")
        )
        await cb.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="« Назад", callback_data="notif:main")
            ]]),
            parse_mode="HTML",
        )
        await cb.answer()

    @router.callback_query(F.data == "notif:reload")
    async def cb_reload(cb: CallbackQuery):
        notif_config.reload()
        await cb.message.edit_text(
            "🔄 <b>notifications.yaml перезагружен</b>\nIn-memory toggles сброшены.",
            reply_markup=_rules_keyboard(),
            parse_mode="HTML",
        )
        await cb.answer("✅ Reload OK")

    @router.callback_query(F.data.startswith("notif_toggle:"))
    async def cb_toggle(cb: CallbackQuery):
        rule_name = cb.data.split(":", 1)[1]
        new_val = notif_config.toggle_rule(rule_name)
        if new_val is None:
            await cb.answer(f"❌ Правило {rule_name} не найдено")
            return
        state = "✅ включено" if new_val else "⬜ выключено"
        await cb.message.edit_reply_markup(reply_markup=_rules_keyboard())
        await cb.answer(f"{rule_name}: {state}")

    return router
