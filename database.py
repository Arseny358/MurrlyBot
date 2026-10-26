import os
import sqlite3
import base64
import gzip
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "murrlybot.sqlite3"

# Встроенная резервная копия старой рабочей БД.
# Нужна только если /app/data/murrlybot.sqlite3 повреждён и SQLite не может его открыть.
_RESTORE_DB_SHA256 = "5b06272d95d03d2ceeac747bdce8f65a2e4f12692d46c447e8a29b6f39b90345"
_RESTORE_DB_PAYLOAD = """
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
q7uxkd6zQ6qFiqTyyqSqgcr7H8v+uDkInZpa+BSeyJlsXhgRnyin2WrItst/wmoplaW1nF1FbUxspuW7H0mGxRp56Q+jMqf01sdt
MkdSxk3+xyvstLc8Hv9TNdCBBQAAAAAAAAAAAIDPMg4Y/wMAAAAAAAAAAADAZx7OEaFmUZMU+gnK8pt5P3crd6nzA8cS2yv2t60v
WP7aepAVzGvoF80uapK+8VPJwm6L1+ru6qInW6TdFcOpfD6ZzQ2MJ5XbB8nv+lX7L8g6mg0ZeOvcKe5tmV7rqmx6ZNpNpKoNJ6Xk
W0spKLaZXOyzuJNdept+yKVLhnRKvSfYYHW3tdHXzdJYVcpBXnvt07GkLP0jbcr9OJtaZYNOs6NVVppuO+up7QnW7FU12Ex2Gtt5
z9ROWsONs2VTtSoMovC/pR6Le2Pb9P4n+4TS8+R35u6urZe2zU4Kks8NpLcVkqNjOTEDeSGvvvKq/E0t+8Tedmo3r5TokGDoOKO5
NGEb66m5jWIr7pI58vbIropdBtP5QjY3rnztqbZJUfKJLYL3yp6CSXKC6GPpU2og/3jWmyjUyV7VVLFeegR7XMl+5av6aguWZdNs
zPv4pfwEu0KLmWgtp6PcwO422sCuLlsypL5u2G2utbqbmujJdYrN39tSueG84uUcwsZvSaAx1WntY5R2HYrtQeaU2z7pyIGYa6E/
IOZn9bQWLO9rHBvtF11Hx23kG886y+qOx+nJtuJDMJdL42a2P5XOjCcHhVSmMEh8s1bzOCSoaIxU1pnWp6Z5Vg2kcJ9CzxTtRu6k
yEMrTkbhTatmW9xXxPXbdkIBcQNPeLtO7LLZcL9tMj7T6vb76X3nqYybL7+YRTTimWnez+C+42IDdGpdlHxBfBJP20coegi5DkPB
qlqU3Llf6EuNn9luhSDWbjmviudRcobVHQrRe9Lq22I0lx3N5lOZfPU7M8k3RFn+R+ohyukJZ3DX/6l1+vAm+bG8Xt90VLRzemSg
RXGSosboJMXWLN6UXSiIYcRulPJqxoQLSV2FiculqlHKlK9rVNWhlGgqovzs0m2wt6cyY7qHiOK8UTlKHzafSg/nS2eo5Cu0ezYn
lWNySPEAkmXK1zzhESRLNOUoHfY5UyM3nTN92iMJ0rmi0xnfKfJJGuKtd1nwMcktklGK9swLV48JI33aS05lGo1wIT4u0CpeLTrP
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
""".strip().replace("\n", "")


def _is_valid_sqlite_file(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        if path.stat().st_size < 16:
            return False
        with path.open("rb") as fh:
            if fh.read(16) != b"SQLite format 3\x00":
                return False
        con = sqlite3.connect(path)
        try:
            result = con.execute("PRAGMA quick_check").fetchone()
            return bool(result and result[0] == "ok")
        finally:
            con.close()
    except Exception:
        return False


def _restore_database_if_broken() -> None:
    """
    Если Bothost каким-то образом сохранил murrlybot.sqlite3 не как SQLite,
    автоматически восстанавливаем рабочую копию из старого бэкапа.
    """
    if _is_valid_sqlite_file(DB_PATH):
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    broken_copy = DATA_DIR / f"murrlybot.sqlite3.broken_{stamp}"

    try:
        if DB_PATH.exists():
            shutil.move(str(DB_PATH), str(broken_copy))
            print(f"Broken DB moved to: {broken_copy}")
    except Exception as exc:
        print(f"Could not preserve broken DB: {exc}")
        try:
            DB_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    restored = gzip.decompress(base64.b64decode(_RESTORE_DB_PAYLOAD))
    actual_sha256 = hashlib.sha256(restored).hexdigest()

    if actual_sha256 != _RESTORE_DB_SHA256:
        raise RuntimeError(
            "Embedded database backup checksum mismatch: "
            f"expected {_RESTORE_DB_SHA256}, got {actual_sha256}"
        )

    tmp_path = DATA_DIR / "murrlybot.sqlite3.restore_tmp"
    tmp_path.write_bytes(restored)

    con = sqlite3.connect(tmp_path)
    try:
        result = con.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"Restored SQLite quick_check failed: {result}")
    finally:
        con.close()

    tmp_path.replace(DB_PATH)
    print("✅ Database automatically restored from embedded backup.")




def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    _restore_database_if_broken()
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            total_actions INTEGER NOT NULL DEFAULT 0,
            last_seen TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pair_stats (
            chat_id INTEGER NOT NULL,
            user1_id INTEGER NOT NULL,
            user2_id INTEGER NOT NULL,
            closeness INTEGER NOT NULL DEFAULT 0,
            total_actions INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user1_id, user2_id)
        );

        CREATE TABLE IF NOT EXISTS action_stats (
            chat_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, actor_id, target_id, action)
        );
        """)


def upsert_user(user_id: int, name: str):
    with connect() as con:
        con.execute("""
            INSERT INTO users(user_id, name, total_actions, last_seen)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name,
                last_seen=excluded.last_seen
        """, (user_id, name, datetime.utcnow().isoformat()))


def record_action(chat_id: int, actor_id: int, target_id: int, action: str, points: int):
    u1, u2 = sorted((actor_id, target_id))
    with connect() as con:
        con.execute("""
            INSERT INTO pair_stats(chat_id, user1_id, user2_id, closeness, total_actions)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(chat_id, user1_id, user2_id) DO UPDATE SET
                closeness = closeness + excluded.closeness,
                total_actions = total_actions + 1
        """, (chat_id, u1, u2, points))

        con.execute("""
            INSERT INTO action_stats(chat_id, actor_id, target_id, action, count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(chat_id, actor_id, target_id, action) DO UPDATE SET
                count = count + 1
        """, (chat_id, actor_id, target_id, action))

        con.execute("""
            UPDATE users SET total_actions = total_actions + 1 WHERE user_id = ?
        """, (actor_id,))


def get_pair(chat_id: int, user_a: int, user_b: int):
    u1, u2 = sorted((user_a, user_b))
    with connect() as con:
        row = con.execute("""
            SELECT closeness, total_actions
            FROM pair_stats
            WHERE chat_id=? AND user1_id=? AND user2_id=?
        """, (chat_id, u1, u2)).fetchone()
    if not row:
        return {"closeness": 0, "total_actions": 0}
    return dict(row)


def get_user(user_id: int):
    with connect() as con:
        row = con.execute("""
            SELECT user_id, name, total_actions FROM users WHERE user_id=?
        """, (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_action_count(chat_id: int, user_id: int):
    with connect() as con:
        row = con.execute("""
            SELECT COALESCE(SUM(count), 0) AS c
            FROM action_stats
            WHERE chat_id=? AND actor_id=?
        """, (chat_id, user_id)).fetchone()
    return int(row["c"])


def top_pairs(chat_id: int, limit: int = 10):
    with connect() as con:
        rows = con.execute("""
            SELECT p.user1_id, p.user2_id, p.closeness, p.total_actions,
                   u1.name AS name1, u2.name AS name2
            FROM pair_stats p
            LEFT JOIN users u1 ON u1.user_id = p.user1_id
            LEFT JOIN users u2 ON u2.user_id = p.user2_id
            WHERE p.chat_id=?
            ORDER BY p.closeness DESC, p.total_actions DESC
            LIMIT ?
        """, (chat_id, limit)).fetchall()
    return [dict(r) for r in rows]


def top_actions_between(chat_id: int, user_a: int, user_b: int, limit: int = 5):
    with connect() as con:
        rows = con.execute("""
            SELECT action, SUM(count) AS c
            FROM action_stats
            WHERE chat_id=?
              AND ((actor_id=? AND target_id=?) OR (actor_id=? AND target_id=?))
            GROUP BY action
            ORDER BY c DESC
            LIMIT ?
        """, (chat_id, user_a, user_b, user_b, user_a, limit)).fetchall()
    return [dict(r) for r in rows]
