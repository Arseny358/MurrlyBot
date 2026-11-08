import asyncio
import shutil
import sqlite3
import zipfile
from pathlib import Path

from aiogram.types import FSInputFile

from config import bot_now, get_admin_user_ids, get_bool, get_int, get_setting, log_admin_action, set_setting
from database import DB_PATH, DATA_DIR

BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup_backups():
    keep = max(1, get_int("backup.keep_local", 7))
    files = sorted(BACKUP_DIR.glob("murrlybot_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except Exception:
            pass


def create_backup_archive() -> Path:
    """Создаёт консистентный SQLite-снимок через backup API и упаковывает в ZIP."""
    stamp = bot_now().strftime("%Y-%m-%d_%H-%M-%S")
    temp_db = BACKUP_DIR / f"murrlybot_{stamp}.sqlite3"
    zip_path = BACKUP_DIR / f"murrlybot_backup_{stamp}.zip"

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(temp_db)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(temp_db, "murrlybot.sqlite3")
        info = (
            "MurrlyBot database backup\n"
            f"Created: {bot_now().isoformat(timespec='seconds')} (UTC+3)\n"
            "Restore target: /app/data/murrlybot.sqlite3\n"
            "The bot should be stopped before manual restore.\n"
        )
        z.writestr("BACKUP_INFO.txt", info)

    try:
        temp_db.unlink()
    except Exception:
        pass

    _cleanup_backups()
    return zip_path


async def send_backup_to_user(bot, user_id: int, admin_log: bool = True):
    path = create_backup_archive()
    await bot.send_document(
        user_id,
        FSInputFile(path),
        caption=(
            "💾 <b>Бэкап MurrlyBot</b>\n\n"
            "В архиве находится консистентная копия <code>murrlybot.sqlite3</code>.\n"
            "Храни этот файл отдельно от Bothost."
        ),
    )
    if admin_log:
        log_admin_action(user_id, "Создан и отправлен бэкап базы данных", None, path.name)
    return path


async def backup_scheduler(bot):
    """Опциональный ежедневный бэкап в личку всем когда-либо авторизованным админам."""
    while True:
        try:
            if get_bool("backup.auto_enabled", False):
                now = bot_now()
                target = str(get_setting("backup.hour", "04:00"))
                minute_key = now.strftime("%H:%M")
                day_key = now.date().isoformat()
                last_auto_day = get_setting("backup.last_auto_day", "")
                if minute_key == target and last_auto_day != day_key:
                    path = create_backup_archive()
                    for user_id in get_admin_user_ids():
                        try:
                            await bot.send_document(
                                user_id,
                                FSInputFile(path),
                                caption="💾 <b>Автоматический ежедневный бэкап MurrlyBot</b>",
                            )
                        except Exception as exc:
                            print(f"Auto backup send failed for admin {user_id}: {exc}")
                    set_setting("backup.last_auto_day", day_key)
        except Exception as exc:
            print(f"Backup scheduler error: {exc}")

        await asyncio.sleep(20)
