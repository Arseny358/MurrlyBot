import os
import random
import asyncio
import html
import time
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.enums import ParseMode, ChatType
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, CallbackQuery

from rp_actions import ACTIONS, ALIASES
from database import (
    init_db,
    upsert_user,
    record_action,
    get_pair,
    get_user,
    get_user_action_count,
    top_pairs,
    top_actions_between,
)
from honey import (
    init_honey_db,
    register_chat,
    get_wallet,
    get_giveaway,
    claim_honey,
    honey_keyboard,
    giveaway_text,
    finished_text,
    expired_text,
    maybe_launch_demo_once,
    honey_scheduler,
    honey_expiration_scheduler,
    refresh_active_giveaway_messages,
)
from farm import (
    init_farm_db,
    get_farm,
    collect_farm,
    upgrade_farm,
    farm_keyboard,
)
from gifts import (
    init_gifts_db,
    GIFT_CATALOG,
    shop_keyboard,
    gift_inventory_keyboard,
    purchase_gift,
    transfer_gift,
    get_gift_collection,
)
from mass_event import (
    init_mass_event_db,
    get_event as get_mass_event,
    join_event as join_mass_event,
    event_keyboard as mass_event_keyboard,
    event_text as mass_event_text,
    finished_event_text as mass_event_finished_text,
    mass_event_scheduler,
    mass_event_expiration_scheduler,
)
from marriage import (
    init_marriage_db,
    proposal_keyboard,
    divorce_keyboard,
    create_proposal,
    get_proposal,
    accept_proposal,
    reject_proposal,
    get_active_marriage,
    get_marriage_by_id,
    marriage_state,
    format_marriage_age,
    apply_rp_health,
    apply_bonus_health,
    divorce_marriage,
    marriage_decay_scheduler,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не найдена.")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Короткий антиспам только для RP-действий.
COOLDOWN_SECONDS = 2.0
last_action_time = {}


def normalize(text: str) -> str:
    return " ".join(
        (text or "")
        .strip()
        .lower()
        .replace("ё", "е")
        .split()
    )


# Дополнительно нормализуем алиасы с ё/е.
NORMALIZED_ALIASES = {normalize(alias): key for alias, key in ALIASES.items()}


def mention(user) -> str:
    name = html.escape(user.full_name or "Пользователь")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def mention_by_id(user_id: int, name: str | None) -> str:
    safe = html.escape(name or "Пользователь")
    return f'<a href="tg://user?id={user_id}">{safe}</a>'


def relationship_level(points: int) -> str:
    if points < 10:
        return "🌱 Незнакомцы"
    if points < 30:
        return "🙂 Знакомые"
    if points < 80:
        return "🤝 Друзья"
    if points < 150:
        return "💛 Близкие"
    if points < 300:
        return "💞 Очень близкие"
    if points < 600:
        return "💖 Неразлучные"
    return "✨ Особая связь"


def action_list_text() -> str:
    rows = []
    for data in ACTIONS.values():
        rows.append(f"• <code>{html.escape(data['aliases'][0])}</code> — {data['title']}")
    return "\n".join(rows)


def farm_card_text(user_link: str, farm: dict) -> str:
    stored = int(float(farm["stored"]))
    level = int(farm["level"])

    lines = [
        f"🐝 <b>Медовая ферма {user_link}</b>",
        "",
        f"Уровень: <b>{level}</b>",
        f"🍯 Производство: <b>{farm['production']} мёдика в сутки</b>",
        f"📦 В сотах: <b>{stored} / {farm['capacity']} 🍯</b>",
    ]

    if stored >= int(farm["capacity"]):
        lines.append("⚠️ <b>Соты заполнены — производство остановлено.</b>")

    if farm["upgrade_cost"] is None:
        lines.extend(["", "👑 <b>Максимальный уровень фермы.</b>"])
    else:
        next_level = level + 1
        lines.extend([
            "",
            f"⬆️ Следующий уровень: <b>{next_level}</b>",
            f"💰 Улучшение: <b>{farm['upgrade_cost']} 🍯</b>",
        ])

    return "\n".join(lines)


def gift_shop_text(balance: int) -> str:
    return (
        "🎁 <b>Магазин подарков</b>\n\n"
        f"Твой баланс: <b>{balance} 🍯</b>\n\n"
        "Покупай подарки в свою коллекцию. "
        "Потом их можно подарить другому участнику командой "
        "<code>подарить</code> ответом на его сообщение.\n\n"
        "Выбери подарок:"
    )


def gift_send_text(recipient_link: str, collection: dict) -> str:
    if not collection["items"]:
        return (
            "🎁 <b>Подарить</b>\n\n"
            f"Получатель: {recipient_link}\n\n"
            "У тебя пока нет подарков. Купи их командой <code>магазин</code>."
        )

    return (
        "🎁 <b>Подарить</b>\n\n"
        f"Получатель: {recipient_link}\n"
        f"Подарков у тебя: <b>{collection['total']}</b>\n\n"
        "Выбери, что хочешь подарить:"
    )


def gift_collection_text(user_link: str, collection: dict) -> str:
    if not collection["items"]:
        return (
            f"🎁 <b>Подарки {user_link}</b>\n\n"
            "Пока подарков нет."
        )

    rows = [
        f"{item['emoji']} {item['name']} ×<b>{item['count']}</b>"
        for item in collection["items"]
    ]
    return (
        f"🎁 <b>Подарки {user_link}</b>\n\n"
        + "\n".join(rows)
        + f"\n\nВсего подарков: <b>{collection['total']}</b>"
    )


async def remember_group_chat(message: Message):
    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        chat_type = (
            message.chat.type.value
            if hasattr(message.chat.type, "value")
            else str(message.chat.type)
        )
        register_chat(
            message.chat.id,
            chat_type,
            message.chat.title or "",
        )
        # Если после обновления бот ещё не успел найти знакомый чат,
        # первая новая активность в группе запустит одноразовые демонстрации.
        await maybe_launch_demo_once(bot, message.chat.id)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    upsert_user(message.from_user.id, message.from_user.full_name)
    await remember_group_chat(message)
    await message.answer(
        "🐝 <b>MurrlyBot работает!</b>\n\n"
        "Это RP-бот для групповых чатов.\n"
        "Чтобы выполнить действие, <b>ответь на сообщение участника</b> "
        "и напиши действие обычным сообщением.\n\n"
        "Например: <code>обнять</code>, <code>поцеловать</code>, "
        "<code>погладить</code>.\n\n"
        "📖 <code>рп команды</code> — все действия\n"
        "💕 <code>отношения</code> — ответом на сообщение человека\n"
        "👤 <code>рп профиль</code> — твоя статистика\n"
        "🏆 <code>рп топ</code> — пары чата\n"
        "💍 <code>заключить брак</code> — ответом на сообщение\n"
        "❤️ <code>брак</code> — состояние твоего брака\n"
        "💔 <code>развестись</code> — расторгнуть брак\n"
        "🍯 <code>копилка</code> — твой запас мёдика\n"
        "🐝 <code>ферма</code> — медовая ферма\n"
        "🎁 <code>магазин</code> — купить подарки себе\n"
        "🎀 <code>подарки</code> — твоя коллекция подарков\n"
        "💝 <code>подарить</code> — ответом на сообщение получателя"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await cmd_start(message)


@dp.callback_query(F.data.startswith("massorgy:"))
async def mass_orgy_callback_handler(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return

    parts = callback.data.split(":")
    if len(parts) != 3 or parts[1] != "join":
        await callback.answer("Некорректное событие.", show_alert=True)
        return

    try:
        event_id = int(parts[2])
    except ValueError:
        await callback.answer("Некорректное событие.", show_alert=True)
        return

    upsert_user(callback.from_user.id, callback.from_user.full_name)
    result = join_mass_event(event_id, callback.from_user.id)

    if result["status"] == "already":
        await callback.answer(
            "🔥 Ты уже участвуешь в этом событии.",
            show_alert=True,
        )
        return

    if result["status"] == "ended":
        await callback.answer(
            "⏰ Событие уже завершено.",
            show_alert=True,
        )

        event = get_mass_event(event_id)
        if callback.message and event:
            try:
                await callback.message.edit_text(
                    mass_event_finished_text(event["participants"]),
                    reply_markup=None,
                )
            except Exception as exc:
                print(f"Mass orgy expired edit failed: {exc}")
        return

    await callback.answer("🔥 Ты присоединился к событию!")

    event = get_mass_event(event_id)
    if callback.message and event:
        closes_at = None
        try:
            closes_at = datetime.fromisoformat(
                event["expires_at"]
            ).strftime("%H:%M")
        except Exception:
            pass

        try:
            await callback.message.edit_text(
                mass_event_text(
                    participants=result["participants"],
                    closes_at=closes_at,
                ),
                reply_markup=mass_event_keyboard(event_id),
            )
        except Exception as exc:
            print(f"Mass orgy participant edit failed: {exc}")


@dp.callback_query(F.data.startswith("honey:"))
async def honey_claim_handler(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return

    try:
        giveaway_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная раздача.", show_alert=True)
        return

    upsert_user(callback.from_user.id, callback.from_user.full_name)
    result = claim_honey(giveaway_id, callback.from_user.id)

    if result["status"] == "already":
        await callback.answer(
            "Ты уже забрал мёдик из этой раздачи 🐝",
            show_alert=True,
        )
        return

    if result["status"] == "ended":
        await callback.answer("Мёдик уже разобрали 🍯", show_alert=True)
        return

    if result["status"] == "expired":
        await callback.answer("⏰ Раздача уже закончилась.", show_alert=True)
        giveaway = get_giveaway(giveaway_id)
        if callback.message and giveaway:
            try:
                await callback.message.edit_text(
                    expired_text(
                        giveaway["remaining"],
                        giveaway["participants"],
                    ),
                    reply_markup=None,
                )
            except Exception as exc:
                print(f"Honey expired message edit failed: {exc}")
        return

    await callback.answer(f"+{result['amount']} 🍯 в твою копилку!")

    if callback.message:
        user_link = mention(callback.from_user)
        await callback.message.answer(
            f"🍯 {user_link} забрал <b>{result['amount']} мёдика!</b>\n\n"
            f"В копилке: <b>{result['balance']} 🍯</b>\n"
            f"В улье осталось: <b>{result['remaining']} 🍯</b>"
        )

        try:
            if result["active"]:
                giveaway = get_giveaway(giveaway_id)
                closes_at = None
                if giveaway and giveaway.get("expires_at"):
                    try:
                        closes_at = datetime.fromisoformat(
                            giveaway["expires_at"]
                        ).strftime("%H:%M")
                    except Exception:
                        closes_at = None

                await callback.message.edit_text(
                    giveaway_text(
                        result["remaining"],
                        demo=(giveaway and giveaway.get("kind") == "demo"),
                        closes_at=closes_at,
                    ),
                    reply_markup=honey_keyboard(giveaway_id),
                )
            else:
                await callback.message.edit_text(
                    finished_text(result["participants"]),
                    reply_markup=None,
                )
        except Exception as exc:
            print(f"Honey message edit failed: {exc}")



@dp.callback_query(F.data.startswith("farm:"))
async def farm_callback_handler(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректное действие.", show_alert=True)
        return

    action = parts[1]
    try:
        owner_id = int(parts[2])
    except ValueError:
        await callback.answer("Некорректная ферма.", show_alert=True)
        return

    if callback.from_user.id != owner_id:
        await callback.answer("🐝 Это не твоя ферма.", show_alert=True)
        return

    if action == "collect":
        result = collect_farm(owner_id)

        if result["status"] == "empty":
            await callback.answer(
                "🍯 В сотах пока меньше 1 мёдика.",
                show_alert=True,
            )
        else:
            await callback.answer(f"+{result['amount']} 🍯 в копилку!")
            if callback.message:
                await callback.message.answer(
                    f"🍯 {mention(callback.from_user)} собрал "
                    f"<b>{result['amount']} мёдика</b> с фермы.\n"
                    f"В копилке: <b>{result['balance']} 🍯</b>"
                )

        farm = result["farm"]
        if callback.message:
            await callback.message.edit_text(
                farm_card_text(mention(callback.from_user), farm),
                reply_markup=farm_keyboard(owner_id, farm),
            )
        return

    if action == "upgrade":
        result = upgrade_farm(owner_id)

        if result["status"] == "max":
            await callback.answer("👑 Ферма уже максимального уровня.", show_alert=True)
        elif result["status"] == "insufficient":
            await callback.answer(
                f"Не хватает {result['need']} 🍯.",
                show_alert=True,
            )
        else:
            await callback.answer(
                f"🐝 Ферма улучшена до {result['farm']['level']} уровня!"
            )
            if callback.message:
                await callback.message.answer(
                    f"⬆️ {mention(callback.from_user)} улучшил медовую ферму "
                    f"до <b>{result['farm']['level']} уровня</b> за "
                    f"<b>{result['cost']} 🍯</b>."
                )

        farm = result["farm"]
        if callback.message:
            await callback.message.edit_text(
                farm_card_text(mention(callback.from_user), farm),
                reply_markup=farm_keyboard(owner_id, farm),
            )
        return

    await callback.answer("Неизвестное действие.", show_alert=True)


@dp.callback_query(F.data.startswith("gift:"))
async def gift_callback_handler(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Некорректный подарок.", show_alert=True)
        return

    action = parts[1]
    gift_key = parts[2]

    # Покупка подарка в собственную коллекцию.
    if action == "buy":
        if len(parts) != 4:
            # Старые кнопки магазина из предыдущей версии больше не используем.
            await callback.answer(
                "Этот магазин устарел. Напиши «магазин» ещё раз.",
                show_alert=True,
            )
            return

        try:
            buyer_id = int(parts[3])
        except ValueError:
            await callback.answer("Некорректный магазин.", show_alert=True)
            return

        if callback.from_user.id != buyer_id:
            await callback.answer("🐝 Этот магазин открыт не тобой.", show_alert=True)
            return

        result = purchase_gift(buyer_id, gift_key)

        if result["status"] == "insufficient":
            await callback.answer(
                f"Не хватает {result['need']} 🍯.",
                show_alert=True,
            )
            return
        if result["status"] != "ok":
            await callback.answer("Не удалось купить подарок.", show_alert=True)
            return

        gift = result["gift"]
        await callback.answer(
            f"{gift['emoji']} Куплено! Теперь у тебя {result['count']} шт."
        )

        if callback.message:
            await callback.message.answer(
                f"🛍 {mention(callback.from_user)} купил "
                f"<b>{gift['name']}</b> {gift['emoji']} за "
                f"<b>{gift['price']} 🍯</b>.\n\n"
                f"Теперь в коллекции: <b>{result['count']} шт.</b>\n"
                f"В копилке осталось: <b>{result['balance']} 🍯</b>"
            )

            # Магазин остаётся открыт для следующих покупок.
            await callback.message.edit_text(
                gift_shop_text(result["balance"]),
                reply_markup=shop_keyboard(buyer_id),
            )
        return

    # Передача уже купленного подарка другому участнику.
    if action == "send":
        if len(parts) != 5:
            await callback.answer("Некорректная передача.", show_alert=True)
            return

        try:
            recipient_id = int(parts[3])
            giver_id = int(parts[4])
        except ValueError:
            await callback.answer("Некорректная передача.", show_alert=True)
            return

        if callback.from_user.id != giver_id:
            await callback.answer(
                "🐝 Этот список подарков открыт не тобой.",
                show_alert=True,
            )
            return

        result = transfer_gift(giver_id, recipient_id, gift_key)

        if result["status"] == "not_owned":
            await callback.answer(
                "У тебя больше нет такого подарка.",
                show_alert=True,
            )
            return
        if result["status"] != "ok":
            await callback.answer("Не удалось подарить подарок.", show_alert=True)
            return

        gift = result["gift"]
        recipient = get_user(recipient_id)
        recipient_link = mention_by_id(
            recipient_id,
            recipient["name"] if recipient else None,
        )

        marriage_health = apply_bonus_health(
            giver_id,
            recipient_id,
            float(gift["health_bonus"]),
        )

        await callback.answer(f"{gift['emoji']} Подарок отправлен!")

        if callback.message:
            result_text = (
                f"🎁 {mention(callback.from_user)} подарил {recipient_link} "
                f"<b>{gift['name']}</b> {gift['emoji']}\n\n"
                f"У получателя теперь: <b>{result['recipient_count']} шт.</b>"
            )

            if marriage_health and marriage_health["gain"] > 0:
                gain = marriage_health["gain"]
                gain_text = f"{gain:.1f}".rstrip("0").rstrip(".")
                current = int(round(marriage_health["new_health"]))
                result_text += (
                    f"\n❤️ Здоровье брака: <b>+{gain_text}%</b> · "
                    f"Сейчас: <b>{current}%</b>"
                )

            await callback.message.answer(result_text)

            # Обновляем список оставшихся подарков дарителя.
            collection = get_gift_collection(giver_id)
            keyboard = gift_inventory_keyboard(giver_id, recipient_id)
            await callback.message.edit_text(
                gift_send_text(recipient_link, collection),
                reply_markup=keyboard,
            )
        return

    await callback.answer("Неизвестное действие.", show_alert=True)


@dp.callback_query(F.data.startswith("marriage:"))
async def marriage_callback_handler(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return

    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Некорректное действие.", show_alert=True)
        return

    action = parts[1]

    if action in {"accept", "reject"}:
        try:
            proposal_id = int(parts[2])
        except ValueError:
            await callback.answer("Некорректное предложение.", show_alert=True)
            return

        proposal = get_proposal(proposal_id)
        if not proposal:
            await callback.answer("Предложение не найдено.", show_alert=True)
            return

        if callback.from_user.id != proposal["target_id"]:
            await callback.answer(
                "🐝 Это предложение предназначено не тебе.",
                show_alert=True,
            )
            return

        proposer = get_user(proposal["proposer_id"])
        target = get_user(proposal["target_id"])
        proposer_link = mention_by_id(
            proposal["proposer_id"],
            proposer["name"] if proposer else None,
        )
        target_link = mention_by_id(
            proposal["target_id"],
            target["name"] if target else callback.from_user.full_name,
        )

        if action == "reject":
            result = reject_proposal(proposal_id, callback.from_user.id)
            if result["status"] == "closed":
                await callback.answer("Это предложение уже закрыто.", show_alert=True)
                return
            if result["status"] != "ok":
                await callback.answer("Не удалось обработать предложение.", show_alert=True)
                return

            await callback.answer("Предложение отклонено.")
            if callback.message:
                await callback.message.edit_text(
                    f"💔 {target_link} отказался от предложения {proposer_link}.",
                    reply_markup=None,
                )
            return

        result = accept_proposal(proposal_id, callback.from_user.id)
        if result["status"] == "closed":
            await callback.answer("Это предложение уже закрыто.", show_alert=True)
            return
        if result["status"] == "someone_married":
            await callback.answer(
                "Один из участников уже состоит в браке.",
                show_alert=True,
            )
            if callback.message:
                await callback.message.edit_text(
                    "💔 Предложение больше неактуально: один из участников уже состоит в браке.",
                    reply_markup=None,
                )
            return
        if result["status"] != "ok":
            await callback.answer("Не удалось заключить брак.", show_alert=True)
            return

        await callback.answer("💍 Брак заключён!")
        if callback.message:
            await callback.message.edit_text(
                "💖 <b>БРАК ЗАКЛЮЧЁН!</b>\n\n"
                f"{proposer_link} ❤️ {target_link}\n\n"
                "❤️ Здоровье брака: <b>100%</b>\n"
                "🕒 Вместе: <b>только что</b>",
                reply_markup=None,
            )
        return

    if action in {"divorce", "cancel_divorce"}:
        if len(parts) < 4:
            await callback.answer("Некорректное действие.", show_alert=True)
            return
        try:
            marriage_id = int(parts[2])
            requester_id = int(parts[3])
        except ValueError:
            await callback.answer("Некорректное действие.", show_alert=True)
            return

        if callback.from_user.id != requester_id:
            await callback.answer(
                "🐝 Это подтверждение предназначено не тебе.",
                show_alert=True,
            )
            return

        marriage = get_marriage_by_id(marriage_id)
        if not marriage or not marriage["active"]:
            await callback.answer("Этот брак уже завершён.", show_alert=True)
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
            return

        if requester_id not in {marriage["user1_id"], marriage["user2_id"]}:
            await callback.answer("Ты не состоишь в этом браке.", show_alert=True)
            return

        user1 = mention_by_id(marriage["user1_id"], marriage["user1_name"])
        user2 = mention_by_id(marriage["user2_id"], marriage["user2_name"])

        if action == "cancel_divorce":
            await callback.answer("Развод отменён.")
            if callback.message:
                await callback.message.edit_text(
                    f"💍 Развод отменён.\n\n{user1} ❤️ {user2}",
                    reply_markup=None,
                )
            return

        result = divorce_marriage(marriage_id, requester_id)
        if result["status"] != "ok":
            await callback.answer("Не удалось расторгнуть брак.", show_alert=True)
            return

        await callback.answer("Брак расторгнут.")
        if callback.message:
            await callback.message.edit_text(
                "💔 <b>БРАК РАСТОРГНУТ</b>\n\n"
                f"{user1} и {user2} больше не состоят в браке.",
                reply_markup=None,
            )
        return

    await callback.answer("Неизвестное действие.", show_alert=True)


@dp.message(F.text)
async def text_handler(message: Message):
    if not message.from_user:
        return

    raw = message.text or ""
    text = normalize(raw)

    # Второй формат RP-команд:
    # 1-я строка — сама RP-команда.
    # 2-я и последующие строки — дополнительная реплика/описание.
    raw_lines = [line.strip() for line in raw.splitlines() if line.strip()]
    rp_command_text = normalize(raw_lines[0]) if raw_lines else ""
    rp_extra_text = "\n".join(raw_lines[1:]).strip() if len(raw_lines) > 1 else ""

    if text.startswith("/"):
        return

    upsert_user(message.from_user.id, message.from_user.full_name)
    await remember_group_chat(message)

    # Копилка мёдика
    if text in {"копилка", "мой медик", "мой мёдик", "медик", "мёдик"}:
        wallet = get_wallet(message.from_user.id)
        await message.answer(
            f"🍯 <b>Копилка {mention(message.from_user)}</b>\n\n"
            f"Баланс: <b>{wallet['balance']} 🍯</b>\n"
            f"Всего собрано: <b>{wallet['total_earned']} 🍯</b>\n"
            f"Раздач поймано: <b>{wallet['giveaways_claimed']}</b>\n"
            f"Самый большой улов: <b>{wallet['biggest_claim']} 🍯</b>"
        )
        return

    # Медовая ферма
    if text in {"ферма", "моя ферма", "медовая ферма"}:
        farm = get_farm(message.from_user.id)
        await message.answer(
            farm_card_text(mention(message.from_user), farm),
            reply_markup=farm_keyboard(message.from_user.id, farm),
        )
        return

    # Магазин подарков — открывается обычной командой без reply.
    if text in {"магазин", "магазин подарков"}:
        wallet = get_wallet(message.from_user.id)

        await message.answer(
            gift_shop_text(wallet["balance"]),
            reply_markup=shop_keyboard(message.from_user.id),
        )
        return

    # Передача подарка — ответом на сообщение получателя.
    if text in {"подарить", "подарить подарок"}:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply(
                "🎁 Отправь <code>подарить</code> ответом на сообщение человека, "
                "которому хочешь передать подарок."
            )
            return

        target = message.reply_to_message.from_user
        if target.id == message.from_user.id:
            await message.reply("🎁 Нельзя подарить подарок самому себе.")
            return
        if target.is_bot:
            await message.reply("🐝 Ботам подарки пока дарить нельзя.")
            return

        upsert_user(target.id, target.full_name)
        collection = get_gift_collection(message.from_user.id)

        await message.answer(
            gift_send_text(mention(target), collection),
            reply_markup=gift_inventory_keyboard(
                message.from_user.id,
                target.id,
            ),
        )
        return

    # Коллекция подарков. Ответом на сообщение можно посмотреть чужую.
    if text in {"подарки", "мои подарки", "коллекция подарков"}:
        target = (
            message.reply_to_message.from_user
            if message.reply_to_message and message.reply_to_message.from_user
            else message.from_user
        )

        collection = get_gift_collection(target.id)
        await message.answer(
            gift_collection_text(mention(target), collection)
        )
        return

    # Предложение вступить в брак — ответом на сообщение участника.
    if text in {"заключить брак", "предложить брак", "вступить в брак"}:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply(
                "💍 Отправь <code>заключить брак</code> ответом на сообщение нужного человека."
            )
            return

        actor = message.from_user
        target = message.reply_to_message.from_user

        if actor.id == target.id:
            await message.reply("🐝 Нельзя заключить брак с самим собой :3")
            return
        if target.is_bot:
            await message.reply("🐝 С ботами заключать брак нельзя.")
            return

        upsert_user(target.id, target.full_name)
        proposal = create_proposal(message.chat.id, actor.id, target.id)

        if proposal["status"] == "proposer_married":
            await message.reply("💍 Ты уже состоишь в браке.")
            return
        if proposal["status"] == "target_married":
            await message.reply("💍 Этот участник уже состоит в браке.")
            return
        if proposal["status"] == "already_pending":
            await message.reply("💍 Между вами уже есть активное предложение брака.")
            return
        if proposal["status"] != "ok":
            await message.reply("💍 Не удалось создать предложение брака.")
            return

        await message.answer(
            "💍 <b>Предложение руки и сердца!</b>\n\n"
            f"{mention(actor)} предлагает {mention(target)} вступить в брак.\n\n"
            "❤️ Здоровье будущего брака: <b>100%</b>",
            reply_markup=proposal_keyboard(proposal["proposal_id"]),
        )
        return

    # Карточка текущего брака.
    if text in {"брак", "мой брак", "наш брак"}:
        marriage = get_active_marriage(message.from_user.id)
        if not marriage:
            await message.answer("💍 Ты пока не состоишь в браке.")
            return

        user1 = mention_by_id(marriage["user1_id"], marriage["user1_name"])
        user2 = mention_by_id(marriage["user2_id"], marriage["user2_name"])
        health = int(round(float(marriage["health"])))
        age = format_marriage_age(marriage["started_at"])

        await message.answer(
            "💍 <b>Брак</b>\n\n"
            f"{user1} ❤️ {user2}\n\n"
            f"❤️ Здоровье брака: <b>{health}%</b>\n"
            f"💕 Состояние: <b>{marriage_state(float(marriage['health']))}</b>\n"
            f"🕒 Вместе: <b>{age}</b>"
        )
        return

    # Ручной развод с подтверждением.
    if text in {"развестись", "развод"}:
        marriage = get_active_marriage(message.from_user.id)
        if not marriage:
            await message.answer("💍 Ты не состоишь в браке.")
            return

        partner_id = (
            marriage["user2_id"]
            if marriage["user1_id"] == message.from_user.id
            else marriage["user1_id"]
        )
        partner_name = (
            marriage["user2_name"]
            if marriage["user1_id"] == message.from_user.id
            else marriage["user1_name"]
        )

        await message.answer(
            "💔 <b>Расторгнуть брак?</b>\n\n"
            f"Ты действительно хочешь развестись с {mention_by_id(partner_id, partner_name)}?\n\n"
            "Это действие потребует подтверждения.",
            reply_markup=divorce_keyboard(marriage["id"], message.from_user.id),
        )
        return

    # Список команд
    if text in {"рп", "рп команды", "rp", "rp команды", "рп помощь"}:
        await message.answer(
            "🐝 <b>RP-команды MurrlyBot</b>\n\n"
            + action_list_text()
            + "\n\n"
            "💡 Любое действие отправляется <b>ответом на сообщение</b> участника.\n"
            "💕 <code>отношения</code> — статистика конкретной пары.\n"
            "👤 <code>рп профиль</code> — личная статистика.\n"
            "🏆 <code>рп топ</code> — самые близкие пары чата."
        )
        return

    # Профиль
    if text in {"рп профиль", "rp профиль", "рп профиль мой", "профиль рп"}:
        user = get_user(message.from_user.id)
        chat_actions = get_user_action_count(message.chat.id, message.from_user.id)
        total = user["total_actions"] if user else 0
        await message.answer(
            f"👤 <b>RP-профиль {mention(message.from_user)}</b>\n\n"
            f"🎭 Действий в этом чате: <b>{chat_actions}</b>\n"
            f"🌍 Всего действий: <b>{total}</b>"
        )
        return

    # Отношения пары
    if text in {"отношения", "наши отношения", "рп отношения"}:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply("💕 Отправь <code>отношения</code> ответом на сообщение нужного человека.")
            return

        target = message.reply_to_message.from_user
        if target.id == message.from_user.id:
            await message.reply("🐝 Для отношений нужен другой участник :3")
            return

        upsert_user(target.id, target.full_name)
        pair = get_pair(message.chat.id, message.from_user.id, target.id)
        top = top_actions_between(message.chat.id, message.from_user.id, target.id)

        details = ""
        if top:
            names = {key: data["title"] for key, data in ACTIONS.items()}
            details = "\n\n<b>Чаще всего:</b>\n" + "\n".join(
                f"• {names.get(row['action'], row['action'])}: <b>{row['c']}</b>"
                for row in top
            )

        await message.answer(
            f"💕 <b>{mention(message.from_user)} × {mention(target)}</b>\n\n"
            f"✨ Близость: <b>{pair['closeness']}</b>\n"
            f"🎭 Взаимодействий: <b>{pair['total_actions']}</b>\n"
            f"📈 Уровень: <b>{relationship_level(pair['closeness'])}</b>"
            + details
        )
        return

    # Топ пар чата
    if text in {"рп топ", "rp топ", "топ отношений", "топ пар"}:
        rows = top_pairs(message.chat.id)
        if not rows:
            await message.answer("🏆 В этом чате пока нет RP-статистики.")
            return

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows, 1):
            icon = medals[i - 1] if i <= 3 else f"{i}."
            a = mention_by_id(row["user1_id"], row["name1"])
            b = mention_by_id(row["user2_id"], row["name2"])
            lines.append(
                f"{icon} {a} × {b} — <b>{row['closeness']}</b> ✨"
            )

        await message.answer(
            "🏆 <b>Самые близкие пары чата</b>\n\n" + "\n".join(lines)
        )
        return

    # RP-действия
    # Для двухстрочного формата командой считается только первая строка.
    action_key = NORMALIZED_ALIASES.get(rp_command_text)
    if not action_key:
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply(
            "🐝 Ответь этой RP-командой на сообщение нужного участника."
        )
        return

    actor = message.from_user
    target = message.reply_to_message.from_user

    if actor.id == target.id:
        await message.reply("🐝 Мря?.. С самим собой это действие выполнить нельзя :3")
        return

    if target.is_bot:
        await message.reply("🐝 С ботами RP-взаимодействия пока не работают.")
        return

    now = time.monotonic()
    last = last_action_time.get(actor.id, 0)
    if now - last < COOLDOWN_SECONDS:
        remain = COOLDOWN_SECONDS - (now - last)
        await message.reply(f"⏳ Не так быстро! Подожди ещё {remain:.1f} сек.")
        return
    last_action_time[actor.id] = now

    upsert_user(target.id, target.full_name)

    data = ACTIONS[action_key]
    points = random.randint(*data["points"])
    phrase = random.choice(data["phrases"]).format(
        actor=mention(actor),
        target=mention(target),
    )

    record_action(
        chat_id=message.chat.id,
        actor_id=actor.id,
        target_id=target.id,
        action=action_key,
        points=points,
    )

    # Обычные RP-действия между супругами поддерживают здоровье брака.
    # 18+ команды отсутствуют в RP_HEALTH_GAINS и поэтому сюда не влияют.
    marriage_health = apply_rp_health(actor.id, target.id, action_key)

    pair = get_pair(message.chat.id, actor.id, target.id)

    result_text = phrase

    # Если после команды была вторая строка — выводим её как реплику.
    if rp_extra_text:
        safe_extra = html.escape(rp_extra_text)
        result_text += f'\n💬 С репликой: «{safe_extra}»'

    result_text += (
        f"\n\n<blockquote>✨ +{points} близости · "
        f"Всего: {pair['closeness']}</blockquote>"
    )

    if marriage_health and marriage_health["gain"] > 0:
        gain = marriage_health["gain"]
        gain_text = f"{gain:.1f}".rstrip("0").rstrip(".")
        current_health = int(round(marriage_health["new_health"]))
        result_text += (
            f"\n❤️ Здоровье брака: <b>+{gain_text}%</b> · "
            f"Сейчас: <b>{current_health}%</b>"
        )

    if rp_extra_text:
        # В двухстрочном формате отвечаем на сообщение с командой.
        # Поэтому Telegram сверху показывает цитату команды и второй строки,
        # как в Iris.
        await message.reply(result_text)
    else:
        # Старый однострочный формат оставляем как был.
        await message.answer(result_text)


async def main():
    init_db()
    init_honey_db()
    init_marriage_db()
    init_farm_db()
    init_gifts_db()
    init_mass_event_db()

    # Демонстрационная раздача запускается только один раз после обновления.
    asyncio.create_task(maybe_launch_demo_once(bot))

    # Дальше бот работает штатно: одна случайная раздача 09:00–15:00
    # и одна случайная раздача 16:00–23:00 каждый день.
    asyncio.create_task(honey_scheduler(bot))

    # Уже активные раздачи после обновления получают строку
    # с точным временем закрытия. Новая демо-раздача не создаётся.
    asyncio.create_task(refresh_active_giveaway_messages(bot))

    # Каждая раздача автоматически закрывается через 1 час.
    asyncio.create_task(honey_expiration_scheduler(bot))

    # Раз в час пересчитываем очень медленный естественный спад здоровья браков.
    asyncio.create_task(marriage_decay_scheduler())

    # RP-событие запускается только штатно: каждый день в 23:00.
    asyncio.create_task(mass_event_scheduler(bot))

    # Событие закрывается через час после запуска.
    asyncio.create_task(mass_event_expiration_scheduler(bot))

    print("MurrlyBot mass RP event update starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
