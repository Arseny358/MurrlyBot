from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import connect


GIFT_CATALOG = {
    "rose": {
        "emoji": "🌹",
        "name": "Роза",
        "price": 20,
        "health_bonus": 0.1,
    },
    "chocolate": {
        "emoji": "🍫",
        "name": "Шоколадка",
        "price": 35,
        "health_bonus": 0.2,
    },
    "teddy": {
        "emoji": "🧸",
        "name": "Плюшевый мишка",
        "price": 75,
        "health_bonus": 0.3,
    },
    "bouquet": {
        "emoji": "💐",
        "name": "Букет цветов",
        "price": 120,
        "health_bonus": 0.5,
    },
    "crystal": {
        "emoji": "💎",
        "name": "Кристалл",
        "price": 250,
        "health_bonus": 0.7,
    },
    "crown": {
        "emoji": "👑",
        "name": "Золотая корона",
        "price": 500,
        "health_bonus": 1.0,
    },
}


def init_gifts_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS gift_inventory (
            user_id INTEGER NOT NULL,
            gift_key TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, gift_key)
        );

        CREATE TABLE IF NOT EXISTS gift_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giver_id INTEGER NOT NULL,
            recipient_id INTEGER NOT NULL,
            gift_key TEXT NOT NULL,
            price INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """)


def shop_keyboard(giver_id: int, recipient_id: int):
    rows = []
    items = list(GIFT_CATALOG.items())

    for i in range(0, len(items), 2):
        row = []
        for key, gift in items[i:i + 2]:
            row.append(InlineKeyboardButton(
                text=f"{gift['emoji']} {gift['name']} · {gift['price']} 🍯",
                callback_data=f"gift:buy:{key}:{recipient_id}:{giver_id}",
            ))
        rows.append(row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def purchase_gift(giver_id: int, recipient_id: int, gift_key: str):
    gift = GIFT_CATALOG.get(gift_key)
    if not gift:
        return {"status": "missing"}

    if giver_id == recipient_id:
        return {"status": "self"}

    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")

        wallet = con.execute(
            "SELECT balance FROM honey_wallets WHERE user_id=?",
            (giver_id,),
        ).fetchone()
        balance = int(wallet["balance"]) if wallet else 0
        price = int(gift["price"])

        if balance < price:
            con.rollback()
            return {
                "status": "insufficient",
                "balance": balance,
                "need": price - balance,
                "gift": gift,
            }

        con.execute(
            "UPDATE honey_wallets SET balance=balance-? WHERE user_id=?",
            (price, giver_id),
        )

        con.execute("""
            INSERT INTO gift_inventory(user_id, gift_key, count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, gift_key) DO UPDATE SET
                count = count + 1
        """, (recipient_id, gift_key))

        con.execute("""
            INSERT INTO gift_history(
                giver_id, recipient_id, gift_key, price, created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            giver_id,
            recipient_id,
            gift_key,
            price,
            datetime.utcnow().isoformat(timespec="seconds"),
        ))

        row = con.execute("""
            SELECT count FROM gift_inventory
            WHERE user_id=? AND gift_key=?
        """, (recipient_id, gift_key)).fetchone()

        con.commit()
        return {
            "status": "ok",
            "gift": gift,
            "balance": balance - price,
            "recipient_count": int(row["count"]),
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def get_gift_collection(user_id: int):
    with connect() as con:
        rows = con.execute("""
            SELECT gift_key, count
            FROM gift_inventory
            WHERE user_id=? AND count>0
            ORDER BY count DESC, gift_key
        """, (user_id,)).fetchall()

        total = con.execute("""
            SELECT COALESCE(SUM(count), 0) AS total
            FROM gift_inventory
            WHERE user_id=?
        """, (user_id,)).fetchone()

    items = []
    for row in rows:
        gift = GIFT_CATALOG.get(row["gift_key"])
        if not gift:
            continue
        items.append({
            "key": row["gift_key"],
            "count": int(row["count"]),
            **gift,
        })

    return {
        "items": items,
        "total": int(total["total"]),
    }
