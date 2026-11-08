import html
from datetime import datetime

from aiogram import F
from aiogram.enums import ChatType
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.exceptions import TelegramBadRequest

from backup import send_backup_to_user
from config import (
    authorize_admin,
    bot_now,
    get_admin_stats,
    get_bool,
    get_float,
    get_int,
    get_recent_audit,
    get_setting,
    is_admin_session,
    is_admin_user_allowed,
    logout_admin,
    set_setting,
    verify_admin_password,
)
from farm import sync_all_farms
from gifts import BASE_GIFT_CATALOG, get_gift_catalog
from honey import launch_manual_giveaways, reset_today_schedule


class AdminState(StatesGroup):
    waiting_password = State()
    waiting_value = State()


def _norm(text: str | None) -> str:
    return " ".join((text or "").strip().lower().replace("ё", "е").split())


class AdminAuthFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        return bool(message.text) and _norm(message.text) in {"авторизация", "/admin", "admin"}


def _btn(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def _back(section="home"):
    return [_btn("🔙 Назад", f"admin:{section}")]


async def _safe_edit(message, text: str, reply_markup=None):
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🐝 Ферма", "admin:farm"), _btn("🎉 Раздачи", "admin:honey")],
        [_btn("🎁 Подарки", "admin:gifts"), _btn("👑 VIP", "admin:vip")],
        [_btn("📊 Статистика", "admin:stats"), _btn("📋 Журнал", "admin:audit")],
        [_btn("⚙️ Система и бэкап", "admin:system")],
        [_btn("🚪 Выйти", "admin:logout")],
    ])


def main_menu_text():
    return (
        "🛠 <b>ПАНЕЛЬ УПРАВЛЕНИЯ MURRLYBOT</b>\n\n"
        "Все изменения применяются сразу и сохраняются в SQLite.\n"
        "Перезапуск бота для изменения цен и расписания не нужен."
    )


def farm_text():
    rows = ["🐝 <b>НАСТРОЙКИ ФЕРМЫ</b>", ""]
    for level in range(1, 6):
        prod = get_int(f"farm.production.{level}")
        cap = get_int(f"farm.capacity.{level}")
        rows.append(f"<b>{level} уровень</b> · {prod} 🍯/сутки · вместимость {cap} 🍯")
        if level < 5:
            rows.append(f"↳ улучшение {level}→{level + 1}: <b>{get_int(f'farm.upgrade.{level}')} 🍯</b>")
    rows.append("\nНажми на параметр, чтобы изменить его.")
    return "\n".join(rows)


def farm_keyboard():
    rows = []
    for level in range(1, 6):
        rows.append([
            _btn(f"🍯 L{level}: производство", f"admin:edit:farm.production.{level}"),
            _btn(f"📦 L{level}: вместимость", f"admin:edit:farm.capacity.{level}"),
        ])
        if level < 5:
            rows.append([_btn(
                f"💰 Цена {level}→{level+1}: {get_int(f'farm.upgrade.{level}')} 🍯",
                f"admin:edit:farm.upgrade.{level}",
            )])
    rows.append(_back())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def honey_text():
    enabled = "✅ включены" if get_bool("honey.enabled", True) else "⏸ выключены"
    return (
        "🎉 <b>ВНЕЗАПНАЯ РАЗДАЧА МЁДИКА</b>\n\n"
        f"Статус: <b>{enabled}</b>\n\n"
        f"🌅 Первая: <b>{get_setting('honey.morning_start')}–{get_setting('honey.morning_end')}</b>\n"
        f"🌆 Вторая: <b>{get_setting('honey.evening_start')}–{get_setting('honey.evening_end')}</b>\n"
        f"🍯 Фонд: <b>{get_int('honey.total')} 🍯</b>\n"
        f"🎁 Порция: <b>{get_int('honey.min')}–{get_int('honey.max')} 🍯</b>\n"
        f"⏱ Длительность: <b>{get_int('honey.duration_minutes')} мин.</b>\n\n"
        "Одноразовая демо-раздача после обновления отключена."
    )


def honey_keyboard():
    toggle = "⏸ Выключить" if get_bool("honey.enabled", True) else "▶️ Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🌅 Начало 1", "admin:edit:honey.morning_start"), _btn("🌅 Конец 1", "admin:edit:honey.morning_end")],
        [_btn("🌆 Начало 2", "admin:edit:honey.evening_start"), _btn("🌆 Конец 2", "admin:edit:honey.evening_end")],
        [_btn("🍯 Фонд", "admin:edit:honey.total"), _btn("⏱ Длительность", "admin:edit:honey.duration_minutes")],
        [_btn("🎁 Минимум", "admin:edit:honey.min"), _btn("🎁 Максимум", "admin:edit:honey.max")],
        [_btn(toggle, "admin:honey_toggle"), _btn("🚀 Запустить сейчас", "admin:honey_launch")],
        _back(),
    ])


def gifts_text():
    catalog = get_gift_catalog()
    lines = ["🎁 <b>НАСТРОЙКИ ПОДАРКОВ</b>", ""]
    for key, item in catalog.items():
        lines.append(
            f"{item['emoji']} {html.escape(item['name'])}: <b>{item['price']} 🍯</b> · здоровье +{item['health_bonus']:g}%"
        )
    lines.append("\nВыбери подарок для редактирования.")
    return "\n".join(lines)


def gifts_keyboard():
    rows = []
    catalog = get_gift_catalog()
    for key, item in catalog.items():
        rows.append([_btn(f"{item['emoji']} {item['name']}", f"admin:gift:{key}")])
    rows.append(_back())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def gift_detail_text(key: str):
    item = get_gift_catalog()[key]
    return (
        f"{item['emoji']} <b>{html.escape(item['name'])}</b>\n\n"
        f"💰 Цена: <b>{item['price']} 🍯</b>\n"
        f"❤️ Бонус здоровью брака: <b>+{item['health_bonus']:g}%</b>"
    )


def gift_detail_keyboard(key: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💰 Изменить цену", f"admin:edit:gift.{key}.price")],
        [_btn("❤️ Изменить бонус", f"admin:edit:gift.{key}.health_bonus")],
        [_btn("🔙 К подаркам", "admin:gifts")],
    ])


def vip_text():
    enabled = "✅ включён" if get_bool("vip.enabled", True) else "⏸ выключен"
    return (
        "👑 <b>VIP-СИСТЕМА</b>\n\n"
        f"Статус: <b>{enabled}</b>\n"
        f"План 1: <b>{get_int('vip.days.7', 7)} дней</b> · {get_int('vip.price.7')} 🍯\n"
        f"План 2: <b>{get_int('vip.days.30', 30)} дней</b> · {get_int('vip.price.30')} 🍯\n\n"
        f"🐝 Производство фермы: <b>+{get_int('vip.farm_production_bonus_pct')}%</b>\n"
        f"📦 Вместимость фермы: <b>+{get_int('vip.farm_capacity_bonus_pct')}%</b>\n"
        f"🎉 Порция в раздаче: <b>+{get_int('vip.giveaway_bonus_pct')}%</b>"
    )


def vip_keyboard():
    toggle = "⏸ Выключить VIP" if get_bool("vip.enabled", True) else "▶️ Включить VIP"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⏱ Срок плана 1", "admin:edit:vip.days.7"), _btn("💰 Цена плана 1", "admin:edit:vip.price.7")],
        [_btn("⏱ Срок плана 2", "admin:edit:vip.days.30"), _btn("💎 Цена плана 2", "admin:edit:vip.price.30")],
        [_btn("🐝 Бонус производства", "admin:edit:vip.farm_production_bonus_pct")],
        [_btn("📦 Бонус вместимости", "admin:edit:vip.farm_capacity_bonus_pct")],
        [_btn("🎉 Бонус раздачи", "admin:edit:vip.giveaway_bonus_pct")],
        [_btn(toggle, "admin:vip_toggle")],
        _back(),
    ])


def system_text():
    auto = "✅ включён" if get_bool("backup.auto_enabled", False) else "⏸ выключен"
    return (
        "⚙️ <b>СИСТЕМА И БЭКАП</b>\n\n"
        "Бэкап создаётся штатным SQLite backup API и отправляется в ЛС.\n"
        "Это не зависит от функции бэкапов Bothost.\n\n"
        f"🤖 Автобэкап: <b>{auto}</b>\n"
        f"🕓 Время автобэкапа: <b>{get_setting('backup.hour', '04:00')}</b> (UTC+3)\n"
        f"🗂 Локально хранить: <b>{get_int('backup.keep_local', 7)}</b> архивов"
    )


def system_keyboard():
    toggle = "⏸ Выключить автобэкап" if get_bool("backup.auto_enabled", False) else "▶️ Включить автобэкап"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💾 Создать бэкап сейчас", "admin:backup_now")],
        [_btn(toggle, "admin:backup_toggle")],
        [_btn("🕓 Время автобэкапа", "admin:edit:backup.hour")],
        [_btn("🗂 Количество локальных копий", "admin:edit:backup.keep_local")],
        _back(),
    ])


EDITABLE = {
    **{f"farm.production.{i}": ("integer", 1, 100000, f"Производство фермы L{i}", "farm") for i in range(1, 6)},
    **{f"farm.capacity.{i}": ("integer", 1, 100000, f"Вместимость фермы L{i}", "farm") for i in range(1, 6)},
    **{f"farm.upgrade.{i}": ("integer", 0, 10000000, f"Цена фермы {i}→{i+1}", "farm") for i in range(1, 5)},
    "honey.total": ("integer", 1, 10000000, "Фонд раздачи", "honey"),
    "honey.min": ("integer", 1, 1000000, "Минимальная порция", "honey"),
    "honey.max": ("integer", 1, 1000000, "Максимальная порция", "honey"),
    "honey.duration_minutes": ("integer", 1, 1440, "Длительность раздачи", "honey"),
    "honey.morning_start": ("time", None, None, "Начало первой раздачи", "honey"),
    "honey.morning_end": ("time", None, None, "Конец первой раздачи", "honey"),
    "honey.evening_start": ("time", None, None, "Начало второй раздачи", "honey"),
    "honey.evening_end": ("time", None, None, "Конец второй раздачи", "honey"),
    "vip.days.7": ("integer", 1, 3650, "Срок VIP-плана 1", "vip"),
    "vip.days.30": ("integer", 1, 3650, "Срок VIP-плана 2", "vip"),
    "vip.price.7": ("integer", 0, 10000000, "Цена VIP-плана 1", "vip"),
    "vip.price.30": ("integer", 0, 10000000, "Цена VIP-плана 2", "vip"),
    "vip.farm_production_bonus_pct": ("integer", 0, 500, "VIP-бонус производства", "vip"),
    "vip.farm_capacity_bonus_pct": ("integer", 0, 500, "VIP-бонус вместимости", "vip"),
    "vip.giveaway_bonus_pct": ("integer", 0, 500, "VIP-бонус раздачи", "vip"),
    "backup.hour": ("time", None, None, "Время автобэкапа", "system"),
    "backup.keep_local": ("integer", 1, 100, "Количество локальных бэкапов", "system"),
}
for gift_key, item in BASE_GIFT_CATALOG.items():
    EDITABLE[f"gift.{gift_key}.price"] = ("integer", 0, 10000000, f"Цена: {item['name']}", f"gift:{gift_key}")
    EDITABLE[f"gift.{gift_key}.health_bonus"] = ("float", 0, 100, f"Бонус браку: {item['name']}", f"gift:{gift_key}")


def _parse_time(value: str):
    try:
        parsed = datetime.strptime(value.strip(), "%H:%M")
        return parsed.strftime("%H:%M")
    except ValueError:
        return None


def _time_minutes(value: str):
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def _section_payload(section: str):
    if section == "farm":
        return farm_text(), farm_keyboard()
    if section == "honey":
        return honey_text(), honey_keyboard()
    if section == "gifts":
        return gifts_text(), gifts_keyboard()
    if section == "vip":
        return vip_text(), vip_keyboard()
    if section == "system":
        return system_text(), system_keyboard()
    if section.startswith("gift:"):
        key = section.split(":", 1)[1]
        return gift_detail_text(key), gift_detail_keyboard(key)
    return main_menu_text(), main_menu_keyboard()


async def auth_command_handler(message: Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    if is_admin_session(message.from_user.id):
        await state.clear()
        await message.answer(main_menu_text(), reply_markup=main_menu_keyboard())
        return
    await state.set_state(AdminState.waiting_password)
    await message.answer(
        "🔐 <b>АВТОРИЗАЦИЯ</b>\n\nОтправь пароль администратора.\n"
        "Сообщение с паролем бот постарается удалить сразу после проверки."
    )


async def admin_password_handler(message: Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE or not message.from_user:
        return
    password = (message.text or "").strip()
    if not is_admin_user_allowed(message.from_user.id):
        try:
            await message.delete()
        except Exception:
            pass
        await state.clear()
        await message.answer("⛔ Этот Telegram-аккаунт не входит в список администраторов.")
        return
    ok, error = verify_admin_password(password)
    try:
        await message.delete()
    except Exception:
        pass
    if error:
        await state.clear()
        await message.answer(f"⚠️ {html.escape(error)}")
        return
    if not ok:
        await message.answer("❌ Неверный пароль. Попробуй ещё раз или отправь <code>Авторизация</code> заново.")
        return
    expires = authorize_admin(message.from_user.id, message.from_user.full_name)
    await state.clear()
    exp = datetime.fromisoformat(expires).strftime("%d.%m.%Y %H:%M")
    await message.answer(
        f"✅ Авторизация успешна. Сессия действует до <b>{exp}</b>.\n\n" + main_menu_text(),
        reply_markup=main_menu_keyboard(),
    )


async def admin_value_handler(message: Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE or not message.from_user:
        return
    if not is_admin_session(message.from_user.id):
        await state.clear()
        await message.answer("🔒 Сессия администратора закончилась. Отправь <code>Авторизация</code>.")
        return

    data = await state.get_data()
    key = data.get("admin_key")
    if key not in EDITABLE:
        await state.clear()
        return
    value_type, min_v, max_v, label, section = EDITABLE[key]
    raw = (message.text or "").strip().replace(",", ".")

    try:
        if value_type == "integer":
            value = int(raw)
        elif value_type == "float":
            value = float(raw)
        elif value_type == "time":
            value = _parse_time(raw)
            if value is None:
                raise ValueError
        else:
            raise ValueError
    except ValueError:
        await message.answer("❌ Некорректное значение. Для времени используй формат <code>HH:MM</code>.")
        return

    if value_type in {"integer", "float"}:
        if min_v is not None and value < min_v or max_v is not None and value > max_v:
            await message.answer(f"❌ Допустимый диапазон: {min_v}–{max_v}.")
            return

    # Связанные проверки раздачи.
    if key == "honey.min" and int(value) > get_int("honey.max", 40):
        await message.answer("❌ Минимальная порция не может быть больше максимальной.")
        return
    if key == "honey.max" and int(value) < get_int("honey.min", 30):
        await message.answer("❌ Максимальная порция не может быть меньше минимальной.")
        return
    if key.startswith("honey.") and key.endswith(("_start", "_end")):
        values = {
            "honey.morning_start": get_setting("honey.morning_start"),
            "honey.morning_end": get_setting("honey.morning_end"),
            "honey.evening_start": get_setting("honey.evening_start"),
            "honey.evening_end": get_setting("honey.evening_end"),
        }
        values[key] = value
        if _time_minutes(values["honey.morning_start"]) > _time_minutes(values["honey.morning_end"]):
            await message.answer("❌ Начало первой раздачи должно быть не позже её конца.")
            return
        if _time_minutes(values["honey.evening_start"]) > _time_minutes(values["honey.evening_end"]):
            await message.answer("❌ Начало второй раздачи должно быть не позже её конца.")
            return

    if (
        key.startswith("farm.production.")
        or key.startswith("farm.capacity.")
        or key in {"vip.farm_production_bonus_pct", "vip.farm_capacity_bonus_pct"}
    ):
        sync_all_farms()

    old, new = set_setting(key, value, message.from_user.id, label)
    if key.startswith("honey.") and key in {
        "honey.morning_start", "honey.morning_end", "honey.evening_start", "honey.evening_end"
    }:
        reset_today_schedule()

    await state.clear()
    text, kb = _section_payload(section)
    await message.answer(
        f"✅ <b>{html.escape(label)}</b> изменено: <code>{html.escape(str(old))}</code> → <code>{html.escape(str(new))}</code>\n\n{text}",
        reply_markup=kb,
    )


async def admin_callback_handler(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.data:
        return
    if callback.message and callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("Админ-панель работает только в личных сообщениях.", show_alert=True)
        return
    if not is_admin_session(callback.from_user.id):
        await callback.answer("Сессия администратора закончилась.", show_alert=True)
        if callback.message:
            await callback.message.answer("🔒 Отправь <code>Авторизация</code>, чтобы войти снова.")
        return

    action = callback.data[len("admin:"):]
    await state.clear()

    if action == "home":
        await callback.answer()
        await _safe_edit(callback.message, main_menu_text(), main_menu_keyboard())
        return
    if action == "farm":
        await callback.answer()
        await _safe_edit(callback.message, farm_text(), farm_keyboard())
        return
    if action == "honey":
        await callback.answer()
        await _safe_edit(callback.message, honey_text(), honey_keyboard())
        return
    if action == "gifts":
        await callback.answer()
        await _safe_edit(callback.message, gifts_text(), gifts_keyboard())
        return
    if action == "vip":
        await callback.answer()
        await _safe_edit(callback.message, vip_text(), vip_keyboard())
        return
    if action == "system":
        await callback.answer()
        await _safe_edit(callback.message, system_text(), system_keyboard())
        return
    if action.startswith("gift:"):
        key = action.split(":", 1)[1]
        if key not in BASE_GIFT_CATALOG:
            await callback.answer("Неизвестный подарок.", show_alert=True)
            return
        await callback.answer()
        await _safe_edit(callback.message, gift_detail_text(key), gift_detail_keyboard(key))
        return

    if action.startswith("edit:"):
        key = action.split(":", 1)[1]
        meta = EDITABLE.get(key)
        if not meta:
            await callback.answer("Эта настройка недоступна.", show_alert=True)
            return
        value_type, min_v, max_v, label, section = meta
        await state.set_state(AdminState.waiting_value)
        await state.update_data(admin_key=key)
        hint = "HH:MM" if value_type == "time" else "число"
        await callback.answer()
        await callback.message.answer(
            f"✏️ <b>{html.escape(label)}</b>\n\n"
            f"Сейчас: <code>{html.escape(str(get_setting(key)))}</code>\n"
            f"Отправь новое значение ({hint})."
        )
        return

    if action == "honey_toggle":
        new = not get_bool("honey.enabled", True)
        set_setting("honey.enabled", "1" if new else "0", callback.from_user.id, "Статус автоматических раздач")
        await callback.answer("Раздачи включены." if new else "Раздачи выключены.")
        await _safe_edit(callback.message, honey_text(), honey_keyboard())
        return

    if action == "honey_launch":
        await callback.answer("Запускаю раздачу…")
        sent = await launch_manual_giveaways(callback.bot)
        await callback.message.answer(f"🚀 Ручная раздача отправлена в <b>{sent}</b> групповых чатов.")
        return

    if action == "vip_toggle":
        # Фиксируем накопление фермы по старым условиям до смены статуса VIP.
        sync_all_farms()
        new = not get_bool("vip.enabled", True)
        set_setting("vip.enabled", "1" if new else "0", callback.from_user.id, "Статус VIP-системы")
        await callback.answer("VIP включён." if new else "VIP выключен.")
        await _safe_edit(callback.message, vip_text(), vip_keyboard())
        return

    if action == "backup_toggle":
        new = not get_bool("backup.auto_enabled", False)
        set_setting("backup.auto_enabled", "1" if new else "0", callback.from_user.id, "Автоматический бэкап")
        await callback.answer("Автобэкап включён." if new else "Автобэкап выключен.")
        await _safe_edit(callback.message, system_text(), system_keyboard())
        return

    if action == "backup_now":
        await callback.answer("Создаю бэкап…")
        try:
            path = await send_backup_to_user(callback.bot, callback.from_user.id)
            await callback.message.answer(f"✅ Бэкап создан: <code>{html.escape(path.name)}</code>")
        except Exception as exc:
            await callback.message.answer(f"❌ Не удалось создать бэкап: <code>{html.escape(str(exc))}</code>")
        return

    if action == "stats":
        stats = get_admin_stats()
        text = (
            "📊 <b>СТАТИСТИКА MURRLYBOT</b>\n\n"
            f"👥 Пользователей: <b>{stats['users']}</b>\n"
            f"💬 Групповых чатов: <b>{stats['chats']}</b>\n"
            f"🍯 Кошельков: <b>{stats['wallets']}</b>\n"
            f"🍯 Мёдика на балансах: <b>{stats['honey_total']}</b>\n"
            f"🐝 Ферм: <b>{stats['farms']}</b>\n"
            f"👤 Анкет: <b>{stats['profiles']}</b>\n"
            f"💍 Активных браков: <b>{stats['active_marriages']}</b>\n"
            f"👑 Активных VIP: <b>{stats['active_vips']}</b>"
        )
        await callback.answer()
        await _safe_edit(callback.message, text, InlineKeyboardMarkup(inline_keyboard=[_back()]))
        return

    if action == "audit":
        rows = get_recent_audit(12)
        lines = ["📋 <b>ЖУРНАЛ АДМИНИСТРАТОРА</b>", ""]
        if not rows:
            lines.append("Пока пусто.")
        for row in rows:
            try:
                when = datetime.fromisoformat(row["created_at"]).strftime("%d.%m %H:%M")
            except Exception:
                when = row["created_at"]
            admin_name = html.escape(row.get("admin_name") or str(row["user_id"]))
            line = f"<b>{when}</b> · {admin_name}\n{html.escape(row['action'])}"
            if row.get("old_value") is not None or row.get("new_value") is not None:
                line += f"\n<code>{html.escape(str(row.get('old_value')))}</code> → <code>{html.escape(str(row.get('new_value')))}</code>"
            lines.append(line)
        await callback.answer()
        await _safe_edit(callback.message, "\n\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[_back()]))
        return

    if action == "logout":
        logout_admin(callback.from_user.id)
        await callback.answer("Сессия завершена.")
        await _safe_edit(callback.message, "🔒 Ты вышел из панели администратора.\n\nДля входа отправь <code>Авторизация</code>.", None)
        return

    await callback.answer("Неизвестное действие.", show_alert=True)


def register_admin_handlers(dp):
    # Регистрируем до общего текстового handler main.py, чтобы FSM админки имел приоритет.
    dp.message.register(
        auth_command_handler,
        AdminAuthFilter(),
    )
    dp.message.register(admin_password_handler, StateFilter(AdminState.waiting_password), F.text)
    dp.message.register(admin_value_handler, StateFilter(AdminState.waiting_value), F.text)
    dp.callback_query.register(admin_callback_handler, F.data.startswith("admin:"))
