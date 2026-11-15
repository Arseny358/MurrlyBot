from config import bot_now, get_int
from database import connect

TASKS = {
    "collect": {
        "emoji": "🍯",
        "title": "Собрать мёдик с фермы",
        "goal_key": "task.collect.goal",
        "reward_key": "task.collect.reward",
        "default_goal": 20,
        "default_reward": 5,
    },
    "gift": {
        "emoji": "🎁",
        "title": "Купить подарок",
        "goal_key": "task.gift.goal",
        "reward_key": "task.gift.reward",
        "default_goal": 1,
        "default_reward": 8,
    },
    "trade": {
        "emoji": "📈",
        "title": "Совершить сделку HNY",
        "goal_key": "task.trade.goal",
        "reward_key": "task.trade.reward",
        "default_goal": 1,
        "default_reward": 7,
    },
}

def init_daily_tasks_db():
    with connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS daily_task_progress (
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                task_key TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                claimed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, day, task_key)
            )
        """)

def _day():
    return bot_now().date().isoformat()

def record_task_progress(user_id: int, task_key: str, amount: float = 1.0):
    if task_key not in TASKS or amount <= 0:
        return
    init_daily_tasks_db()
    with connect() as con:
        con.execute("""
            INSERT INTO daily_task_progress(user_id, day, task_key, progress, claimed)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(user_id, day, task_key) DO UPDATE SET
                progress = progress + excluded.progress
        """, (int(user_id), _day(), task_key, float(amount)))

def get_daily_tasks(user_id: int):
    init_daily_tasks_db()
    with connect() as con:
        rows = con.execute(
            "SELECT task_key, progress, claimed FROM daily_task_progress WHERE user_id=? AND day=?",
            (int(user_id), _day()),
        ).fetchall()
    current = {row["task_key"]: row for row in rows}
    result = []
    for key, meta in TASKS.items():
        goal = max(1, get_int(meta["goal_key"], meta["default_goal"]))
        reward = max(0, get_int(meta["reward_key"], meta["default_reward"]))
        row = current.get(key)
        progress = float(row["progress"]) if row else 0.0
        claimed = bool(row["claimed"]) if row else False
        result.append({
            "key": key,
            "emoji": meta["emoji"],
            "title": meta["title"],
            "goal": goal,
            "progress": min(progress, float(goal)),
            "reward": reward,
            "complete": progress >= goal,
            "claimed": claimed,
        })
    return result

def claim_daily_task(user_id: int, task_key: str):
    if task_key not in TASKS:
        return {"status": "missing"}
    init_daily_tasks_db()
    meta = TASKS[task_key]
    goal = max(1, get_int(meta["goal_key"], meta["default_goal"]))
    reward = max(0, get_int(meta["reward_key"], meta["default_reward"]))

    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT progress, claimed FROM daily_task_progress WHERE user_id=? AND day=? AND task_key=?",
            (int(user_id), _day(), task_key),
        ).fetchone()
        if not row or float(row["progress"]) < goal:
            con.rollback()
            return {"status": "not_ready"}
        if bool(row["claimed"]):
            con.rollback()
            return {"status": "claimed"}

        con.execute(
            "UPDATE daily_task_progress SET claimed=1 WHERE user_id=? AND day=? AND task_key=?",
            (int(user_id), _day(), task_key),
        )
        con.execute("""
            INSERT INTO honey_wallets(user_id, balance, total_earned, giveaways_claimed, biggest_claim)
            VALUES (?, ?, ?, 0, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                balance=balance+excluded.balance,
                total_earned=total_earned+excluded.total_earned
        """, (int(user_id), reward, reward))
        wallet = con.execute("SELECT balance FROM honey_wallets WHERE user_id=?", (int(user_id),)).fetchone()
        con.commit()
        return {"status": "ok", "reward": reward, "balance": int(wallet["balance"])}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
