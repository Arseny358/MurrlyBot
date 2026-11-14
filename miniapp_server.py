import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backup import create_backup_archive
from config import (
    DEFAULT_CONFIG,
    bot_now,
    get_admin_stats,
    get_bool,
    get_int,
    get_recent_audit,
    get_setting,
    log_admin_action,
    set_setting,
    verify_admin_password,
)
from database import connect, upsert_user
from farm import collect_farm, get_farm, sync_all_farms, upgrade_farm
from gifts import get_gift_catalog, get_gift_collection, purchase_gift
from honey import get_wallet, launch_manual_giveaways, reset_today_schedule
from marriage import format_marriage_age, get_active_marriage, marriage_state
from profiles import get_profile
from vip import get_vip_status, purchase_vip

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
STATIC_DIR = Path(__file__).with_name("miniapp_static")
INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60
ADMIN_SESSION_HOURS = 24

app = FastAPI(
    title="MurrlyBot Mini App",
    docs_url=None,
    redoc_url=None,
)

_bot_instance = None


def set_bot_instance(bot):
    global _bot_instance
    _bot_instance = bot


def _init_miniapp_db():
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS miniapp_admin_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )


_init_miniapp_db()


def _admin_ids() -> set[int]:
    raw = (os.getenv("ADMIN_USER_IDS") or os.getenv("ADMIN_USER_ID") or "").strip()
    result = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            pass
    return result


def _is_admin_eligible(user_id: int) -> bool:
    # В Mini App работаем fail-closed:
    # если ADMIN_USER_IDS не задан, веб-админка недоступна вообще.
    allowed = _admin_ids()
    return bool(allowed) and int(user_id) in allowed


def _validate_init_data(raw: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(503, "BOT_TOKEN не настроен.")
    if not raw:
        raise HTTPException(401, "Открой Mini App через Telegram.")

    try:
        data = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=False))
    except Exception:
        raise HTTPException(401, "Некорректные данные Telegram.")

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Telegram hash отсутствует.")

    # Официальная схема Telegram Mini Apps:
    # secret_key = HMAC_SHA256(bot_token, key="WebAppData")
    # calculated = HMAC_SHA256(data_check_string, key=secret_key)
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calculated = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        raise HTTPException(401, "Подпись Telegram не прошла проверку.")

    try:
        auth_date = int(data.get("auth_date", "0"))
        now_ts = int(datetime.utcnow().timestamp())
        if auth_date <= 0 or abs(now_ts - auth_date) > INIT_DATA_MAX_AGE_SECONDS:
            raise HTTPException(401, "Сессия Telegram устарела. Переоткрой Mini App.")
    except ValueError:
        raise HTTPException(401, "Некорректная дата авторизации.")

    try:
        user = json.loads(data.get("user") or "{}")
        user_id = int(user["id"])
    except Exception:
        raise HTTPException(401, "Telegram не передал пользователя.")

    return {
        "id": user_id,
        "first_name": user.get("first_name") or "",
        "last_name": user.get("last_name") or "",
        "username": user.get("username"),
        "photo_url": user.get("photo_url"),
        "language_code": user.get("language_code"),
    }


def current_user(
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
):
    user = _validate_init_data(x_telegram_init_data)
    full_name = " ".join(
        p for p in [user.get("first_name"), user.get("last_name")] if p
    ).strip() or user.get("username") or "Пользователь"
    try:
        upsert_user(user["id"], full_name)
    except Exception:
        # Таблица users создаётся при старте основного бота.
        pass
    return user


def _hash_session(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_admin_session(user_id: int) -> str:
    token = secrets.token_urlsafe(36)
    now = bot_now()
    expires = now + timedelta(hours=ADMIN_SESSION_HOURS)
    with connect() as con:
        con.execute(
            "DELETE FROM miniapp_admin_sessions WHERE expires_at<=?",
            (now.isoformat(timespec="seconds"),),
        )
        con.execute(
            """
            INSERT INTO miniapp_admin_sessions(token_hash, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                _hash_session(token),
                int(user_id),
                now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
            ),
        )
    return token


def require_admin(
    user=Depends(current_user),
    x_admin_session: str = Header(default="", alias="X-Admin-Session"),
):
    if not _is_admin_eligible(user["id"]):
        raise HTTPException(403, "Доступ запрещён.")

    if not x_admin_session:
        raise HTTPException(401, "Нужна авторизация администратора.")

    now = bot_now()
    token_hash = _hash_session(x_admin_session)
    with connect() as con:
        row = con.execute(
            """
            SELECT user_id, expires_at
            FROM miniapp_admin_sessions
            WHERE token_hash=?
            """,
            (token_hash,),
        ).fetchone()

        if not row or int(row["user_id"]) != int(user["id"]):
            raise HTTPException(401, "Админ-сессия недействительна.")

        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except Exception:
            expires = now

        if expires <= now:
            con.execute(
                "DELETE FROM miniapp_admin_sessions WHERE token_hash=?",
                (token_hash,),
            )
            raise HTTPException(401, "Админ-сессия закончилась.")

    return user


def _marriage_view(user_id: int):
    marriage = get_active_marriage(user_id)
    if not marriage:
        return None
    partner_id = (
        marriage["user2_id"]
        if int(marriage["user1_id"]) == int(user_id)
        else marriage["user1_id"]
    )
    partner_name = (
        marriage["user2_name"]
        if int(marriage["user1_id"]) == int(user_id)
        else marriage["user1_name"]
    )
    return {
        "id": marriage["id"],
        "partner_id": partner_id,
        "partner_name": partner_name or "Пользователь",
        "health": int(round(float(marriage["health"]))),
        "state": marriage_state(float(marriage["health"])),
        "age": format_marriage_age(marriage["started_at"]),
    }


def _bootstrap_payload(user: dict):
    user_id = int(user["id"])
    wallet = get_wallet(user_id)
    farm = get_farm(user_id)
    vip = get_vip_status(user_id)
    profile = get_profile(user_id)
    gifts = get_gift_collection(user_id)

    return {
        "user": user,
        "wallet": wallet,
        "farm": farm,
        "vip": vip,
        "profile": profile,
        "gifts_total": gifts["total"],
        "marriage": _marriage_view(user_id),
        "rules": get_setting("rules.text", "Правила пока не опубликованы."),
        "admin_eligible": _is_admin_eligible(user_id),
    }


@app.get("/health")
def health():
    return {"ok": True, "service": "murrlybot-miniapp"}


@app.get("/api/bootstrap")
def api_bootstrap(user=Depends(current_user)):
    return _bootstrap_payload(user)


@app.post("/api/farm/collect")
def api_farm_collect(user=Depends(current_user)):
    result = collect_farm(int(user["id"]))
    return {
        "result": result,
        "wallet": get_wallet(int(user["id"])),
    }


@app.post("/api/farm/upgrade")
def api_farm_upgrade(user=Depends(current_user)):
    result = upgrade_farm(int(user["id"]))
    return {
        "result": result,
        "wallet": get_wallet(int(user["id"])),
    }


@app.get("/api/shop")
def api_shop(user=Depends(current_user)):
    user_id = int(user["id"])
    return {
        "catalog": get_gift_catalog(),
        "inventory": get_gift_collection(user_id),
        "wallet": get_wallet(user_id),
    }


@app.post("/api/shop/buy/{gift_key}")
def api_shop_buy(gift_key: str, user=Depends(current_user)):
    if gift_key not in get_gift_catalog():
        raise HTTPException(404, "Подарок не найден.")
    result = purchase_gift(int(user["id"]), gift_key)
    return {
        "result": result,
        "inventory": get_gift_collection(int(user["id"])),
        "wallet": get_wallet(int(user["id"])),
    }


@app.get("/api/vip")
def api_vip(user=Depends(current_user)):
    user_id = int(user["id"])
    return {
        "status": get_vip_status(user_id),
        "plans": {
            "7": {
                "days": get_int("vip.days.7", 7),
                "price": get_int("vip.price.7", 250),
            },
            "30": {
                "days": get_int("vip.days.30", 30),
                "price": get_int("vip.price.30", 750),
            },
        },
        "bonuses": {
            "farm_production_pct": get_int("vip.farm_production_bonus_pct", 20),
            "farm_capacity_pct": get_int("vip.farm_capacity_bonus_pct", 25),
            "giveaway_pct": get_int("vip.giveaway_bonus_pct", 10),
        },
        "enabled": get_bool("vip.enabled", True),
        "wallet": get_wallet(user_id),
    }


@app.post("/api/vip/buy/{plan}")
def api_vip_buy(plan: int, user=Depends(current_user)):
    if plan not in {7, 30}:
        raise HTTPException(400, "Неизвестный VIP-план.")
    result = purchase_vip(int(user["id"]), plan)
    return {
        "result": result,
        "status": get_vip_status(int(user["id"])),
        "wallet": get_wallet(int(user["id"])),
    }


@app.get("/api/rules")
def api_rules(user=Depends(current_user)):
    return {"text": get_setting("rules.text", "Правила пока не опубликованы.")}


# -------------------- ADMIN --------------------

@app.post("/api/admin/login")
def api_admin_login(
    payload: dict = Body(...),
    user=Depends(current_user),
):
    if not _is_admin_eligible(user["id"]):
        # Не раскрываем обычному пользователю детали админки.
        raise HTTPException(404, "Не найдено.")

    password = str(payload.get("password") or "")
    ok, error = verify_admin_password(password)
    if error:
        raise HTTPException(503, error)
    if not ok:
        raise HTTPException(401, "Неверный пароль.")

    token = _create_admin_session(int(user["id"]))
    log_admin_action(int(user["id"]), "Вход в Mini App админ-панель")
    return {
        "ok": True,
        "session": token,
        "expires_hours": ADMIN_SESSION_HOURS,
    }


@app.post("/api/admin/logout")
def api_admin_logout(
    user=Depends(require_admin),
    x_admin_session: str = Header(default="", alias="X-Admin-Session"),
):
    with connect() as con:
        con.execute(
            "DELETE FROM miniapp_admin_sessions WHERE token_hash=?",
            (_hash_session(x_admin_session),),
        )
    log_admin_action(int(user["id"]), "Выход из Mini App админ-панели")
    return {"ok": True}


ADMIN_LABELS = {
    "farm.production.1": "Ферма L1 — производство",
    "farm.production.2": "Ферма L2 — производство",
    "farm.production.3": "Ферма L3 — производство",
    "farm.production.4": "Ферма L4 — производство",
    "farm.production.5": "Ферма L5 — производство",
    "farm.capacity.1": "Ферма L1 — вместимость",
    "farm.capacity.2": "Ферма L2 — вместимость",
    "farm.capacity.3": "Ферма L3 — вместимость",
    "farm.capacity.4": "Ферма L4 — вместимость",
    "farm.capacity.5": "Ферма L5 — вместимость",
    "farm.upgrade.1": "Цена улучшения 1→2",
    "farm.upgrade.2": "Цена улучшения 2→3",
    "farm.upgrade.3": "Цена улучшения 3→4",
    "farm.upgrade.4": "Цена улучшения 4→5",
    "honey.enabled": "Автоматические раздачи",
    "honey.total": "Фонд раздачи",
    "honey.min": "Минимальная порция",
    "honey.max": "Максимальная порция",
    "honey.duration_minutes": "Длительность раздачи, мин.",
    "honey.morning_start": "Первая раздача — начало",
    "honey.morning_end": "Первая раздача — конец",
    "honey.evening_start": "Вторая раздача — начало",
    "honey.evening_end": "Вторая раздача — конец",
    "gift.rose.price": "Роза — цена",
    "gift.rose.health_bonus": "Роза — бонус браку",
    "gift.chocolate.price": "Шоколадка — цена",
    "gift.chocolate.health_bonus": "Шоколадка — бонус браку",
    "gift.teddy.price": "Мишка — цена",
    "gift.teddy.health_bonus": "Мишка — бонус браку",
    "gift.bouquet.price": "Букет — цена",
    "gift.bouquet.health_bonus": "Букет — бонус браку",
    "gift.crystal.price": "Кристалл — цена",
    "gift.crystal.health_bonus": "Кристалл — бонус браку",
    "gift.crown.price": "Корона — цена",
    "gift.crown.health_bonus": "Корона — бонус браку",
    "vip.enabled": "VIP-система",
    "vip.days.7": "VIP план 1 — дней",
    "vip.price.7": "VIP план 1 — цена",
    "vip.days.30": "VIP план 2 — дней",
    "vip.price.30": "VIP план 2 — цена",
    "vip.farm_production_bonus_pct": "VIP — производство, %",
    "vip.farm_capacity_bonus_pct": "VIP — вместимость, %",
    "vip.giveaway_bonus_pct": "VIP — раздача, %",
    "backup.auto_enabled": "Автоматический бэкап",
    "backup.hour": "Время автобэкапа",
    "backup.keep_local": "Хранить локальных копий",
    "rules.text": "Правила",
}

ADMIN_GROUPS = {
    "farm": [
        *(f"farm.production.{i}" for i in range(1, 6)),
        *(f"farm.capacity.{i}" for i in range(1, 6)),
        *(f"farm.upgrade.{i}" for i in range(1, 5)),
    ],
    "honey": [
        "honey.enabled", "honey.total", "honey.min", "honey.max",
        "honey.duration_minutes", "honey.morning_start", "honey.morning_end",
        "honey.evening_start", "honey.evening_end",
    ],
    "gifts": [
        "gift.rose.price", "gift.rose.health_bonus",
        "gift.chocolate.price", "gift.chocolate.health_bonus",
        "gift.teddy.price", "gift.teddy.health_bonus",
        "gift.bouquet.price", "gift.bouquet.health_bonus",
        "gift.crystal.price", "gift.crystal.health_bonus",
        "gift.crown.price", "gift.crown.health_bonus",
    ],
    "vip": [
        "vip.enabled", "vip.days.7", "vip.price.7",
        "vip.days.30", "vip.price.30",
        "vip.farm_production_bonus_pct",
        "vip.farm_capacity_bonus_pct",
        "vip.giveaway_bonus_pct",
    ],
    "backup": ["backup.auto_enabled", "backup.hour", "backup.keep_local"],
    "rules": ["rules.text"],
}


def _setting_kind(key: str) -> str:
    if key == "rules.text":
        return "text"
    if key.endswith("_start") or key.endswith("_end") or key == "backup.hour":
        return "time"
    if key in {"honey.enabled", "vip.enabled", "backup.auto_enabled"}:
        return "bool"
    if key.endswith(".health_bonus"):
        return "float"
    return "int"


def _parse_setting_value(key: str, raw):
    kind = _setting_kind(key)

    if kind == "text":
        value = str(raw or "").strip()
        if not value:
            raise HTTPException(400, "Текст не может быть пустым.")
        if len(value) > 4000:
            raise HTTPException(400, "Максимум 4000 символов.")
        return value

    if kind == "bool":
        if isinstance(raw, bool):
            return "1" if raw else "0"
        value = str(raw).strip().lower()
        if value in {"1", "true", "on", "yes", "да"}:
            return "1"
        if value in {"0", "false", "off", "no", "нет"}:
            return "0"
        raise HTTPException(400, "Нужно значение да/нет.")

    if kind == "time":
        value = str(raw or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise HTTPException(400, "Время должно быть в формате HH:MM.")
        return value

    try:
        number = float(str(raw).replace(",", "."))
    except Exception:
        raise HTTPException(400, "Нужно число.")

    if kind == "int":
        if not number.is_integer():
            raise HTTPException(400, "Нужно целое число.")
        number = int(number)

    minimum = 0
    maximum = 10_000_000

    if key.startswith("farm.production.") or key.startswith("farm.capacity."):
        minimum = 1
    elif key.startswith("vip.days."):
        minimum, maximum = 1, 3650
    elif key.startswith("vip.") and key.endswith("_pct"):
        minimum, maximum = 0, 500
    elif key.startswith("honey.") and key not in {"honey.enabled"}:
        minimum = 1
        if key == "honey.duration_minutes":
            maximum = 1440
    elif key == "backup.keep_local":
        minimum, maximum = 1, 100
    elif key.endswith(".health_bonus"):
        minimum, maximum = 0, 100

    if number < minimum or number > maximum:
        raise HTTPException(400, f"Допустимый диапазон: {minimum}–{maximum}.")

    return number


def _admin_settings_payload():
    groups = {}
    for group, keys in ADMIN_GROUPS.items():
        rows = []
        for key in keys:
            if key not in DEFAULT_CONFIG:
                continue
            rows.append(
                {
                    "key": key,
                    "label": ADMIN_LABELS.get(key, key),
                    "value": get_setting(key),
                    "kind": _setting_kind(key),
                }
            )
        groups[group] = rows
    return groups


@app.get("/api/admin/dashboard")
def api_admin_dashboard(user=Depends(require_admin)):
    return {
        "stats": get_admin_stats(),
        "settings": _admin_settings_payload(),
        "audit": get_recent_audit(20),
    }


@app.put("/api/admin/settings/{key:path}")
def api_admin_setting(
    key: str,
    payload: dict = Body(...),
    user=Depends(require_admin),
):
    if key not in DEFAULT_CONFIG or key not in ADMIN_LABELS:
        raise HTTPException(404, "Настройка недоступна.")

    value = _parse_setting_value(key, payload.get("value"))

    # Связанные проверки раздачи.
    if key == "honey.min" and int(value) > get_int("honey.max", 40):
        raise HTTPException(400, "Минимум не может быть больше максимума.")
    if key == "honey.max" and int(value) < get_int("honey.min", 30):
        raise HTTPException(400, "Максимум не может быть меньше минимума.")

    # Перед изменением параметров фермы фиксируем уже накопившийся мёдик
    # по старым условиям.
    if (
        key.startswith("farm.production.")
        or key.startswith("farm.capacity.")
        or key in {
            "vip.farm_production_bonus_pct",
            "vip.farm_capacity_bonus_pct",
        }
    ):
        sync_all_farms()

    old, new = set_setting(
        key,
        value,
        int(user["id"]),
        ADMIN_LABELS.get(key, key),
    )

    if key in {
        "honey.morning_start", "honey.morning_end",
        "honey.evening_start", "honey.evening_end",
    }:
        reset_today_schedule()

    return {"ok": True, "old": old, "new": new}


@app.post("/api/admin/honey/launch")
async def api_admin_honey_launch(user=Depends(require_admin)):
    if _bot_instance is None:
        raise HTTPException(503, "Объект бота ещё не готов.")
    sent = await launch_manual_giveaways(_bot_instance)
    log_admin_action(
        int(user["id"]),
        f"Ручная раздача запущена из Mini App ({sent} чатов)",
    )
    return {"ok": True, "sent": sent}


@app.get("/api/admin/backup")
def api_admin_backup(user=Depends(require_admin)):
    path = create_backup_archive()
    log_admin_action(
        int(user["id"]),
        "Скачан бэкап через Mini App",
        None,
        path.name,
    )
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
    )


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="miniapp-static")
