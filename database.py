import os
import sqlite3
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "murrlybot.sqlite3"


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
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
