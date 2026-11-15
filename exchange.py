import asyncio
import math
import random
from datetime import datetime, timedelta

from config import bot_now, get_bool, get_float, get_int
from database import connect


def init_exchange_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS exchange_state (
            id INTEGER PRIMARY KEY CHECK(id=1),
            current_price REAL NOT NULL,
            drift_pct REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS exchange_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            price REAL NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS exchange_portfolios (
            user_id INTEGER PRIMARY KEY,
            shares REAL NOT NULL DEFAULT 0,
            cost_basis REAL NOT NULL DEFAULT 0,
            realized_profit REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS exchange_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            side TEXT NOT NULL,
            shares REAL NOT NULL,
            price REAL NOT NULL,
            honey_amount REAL NOT NULL,
            fee REAL NOT NULL,
            realized_profit REAL,
            created_at TEXT NOT NULL
        );
        """)

        row = con.execute("SELECT current_price FROM exchange_state WHERE id=1").fetchone()
        if not row:
            price = max(0.01, get_float("exchange.start_price", 20))
            now = bot_now().isoformat(timespec="seconds")
            con.execute(
                "INSERT INTO exchange_state(id, current_price, drift_pct, updated_at) VALUES (1, ?, 0, ?)",
                (price, now),
            )
            con.execute(
                "INSERT INTO exchange_prices(price, created_at) VALUES (?, ?)",
                (price, now),
            )


def _settings():
    low = max(0.01, get_float("exchange.min_price", 5))
    high = max(low + 0.01, get_float("exchange.max_price", 100))
    return {
        "enabled": get_bool("exchange.enabled", True),
        "min_price": low,
        "max_price": high,
        "volatility_pct": max(0.05, min(50.0, get_float("exchange.volatility_pct", 3))),
        "update_minutes": max(1, min(1440, get_int("exchange.update_minutes", 5))),
        "buy_fee_pct": max(0.0, min(100.0, get_float("exchange.buy_fee_pct", 1))),
        "sell_fee_pct": max(0.0, min(100.0, get_float("exchange.sell_fee_pct", 1))),
        "news_chance_pct": max(0.0, min(100.0, get_float("exchange.news_chance_pct", 6))),
    }


def update_market_if_due():
    init_exchange_db()
    cfg = _settings()
    if not cfg["enabled"]:
        return

    now = bot_now()
    interval = timedelta(minutes=cfg["update_minutes"])

    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT current_price, drift_pct, updated_at FROM exchange_state WHERE id=1"
        ).fetchone()
        try:
            last = datetime.fromisoformat(row["updated_at"])
        except Exception:
            last = now

        elapsed = now - last
        steps = int(elapsed.total_seconds() // interval.total_seconds())
        if steps <= 0:
            con.commit()
            return

        # Ограничение защищает от слишком тяжёлого catch-up после долгого простоя.
        steps = min(steps, 576)
        price = float(row["current_price"])
        drift = float(row["drift_pct"])
        created = last

        for _ in range(steps):
            created = created + interval

            # Тренд меняется редко и плавно.
            if random.random() < 0.18:
                drift = random.uniform(
                    -cfg["volatility_pct"] * 0.28,
                    cfg["volatility_pct"] * 0.28,
                )

            noise = random.gauss(0, cfg["volatility_pct"] / 3.2)
            change_pct = drift + noise

            # Редкая игровая "новость" — чуть более заметный импульс.
            if random.random() * 100 < cfg["news_chance_pct"]:
                change_pct += random.choice([-1, 1]) * random.uniform(
                    cfg["volatility_pct"] * 0.3,
                    cfg["volatility_pct"] * 0.9,
                )

            change_pct = max(-cfg["volatility_pct"], min(cfg["volatility_pct"], change_pct))
            price *= 1 + change_pct / 100.0
            price = max(cfg["min_price"], min(cfg["max_price"], price))
            price = round(price, 4)

            con.execute(
                "INSERT INTO exchange_prices(price, created_at) VALUES (?, ?)",
                (price, created.isoformat(timespec="seconds")),
            )

        con.execute(
            "UPDATE exchange_state SET current_price=?, drift_pct=?, updated_at=? WHERE id=1",
            (price, drift, created.isoformat(timespec="seconds")),
        )

        cutoff = now - timedelta(days=14)
        con.execute(
            "DELETE FROM exchange_prices WHERE created_at<?",
            (cutoff.isoformat(timespec="seconds"),),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _portfolio(con, user_id: int, price: float):
    row = con.execute(
        "SELECT shares, cost_basis, realized_profit, updated_at FROM exchange_portfolios WHERE user_id=?",
        (int(user_id),),
    ).fetchone()
    shares = float(row["shares"]) if row else 0.0
    basis = float(row["cost_basis"]) if row else 0.0
    realized = float(row["realized_profit"]) if row else 0.0
    value = shares * price
    unrealized = value - basis
    return {
        "shares": round(shares, 6),
        "cost_basis": round(basis, 2),
        "current_value": round(value, 2),
        "unrealized_profit": round(unrealized, 2),
        "realized_profit": round(realized, 2),
        "return_pct": round((unrealized / basis * 100.0), 2) if basis > 0 else 0.0,
    }


def _history_cutoff(range_key: str):
    now = bot_now()
    mapping = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
    }
    return now - mapping.get(range_key, timedelta(hours=24))


def get_market(user_id: int, range_key: str = "24h"):
    update_market_if_due()
    init_exchange_db()
    cfg = _settings()

    with connect() as con:
        state = con.execute(
            "SELECT current_price, updated_at FROM exchange_state WHERE id=1"
        ).fetchone()
        price = float(state["current_price"])
        cutoff = _history_cutoff(range_key)
        rows = con.execute(
            """
            SELECT price, created_at
            FROM exchange_prices
            WHERE created_at>=?
            ORDER BY id ASC
            """,
            (cutoff.isoformat(timespec="seconds"),),
        ).fetchall()

        rows24 = con.execute(
            """
            SELECT price, created_at FROM exchange_prices
            WHERE created_at>=?
            ORDER BY id ASC
            """,
            ((bot_now() - timedelta(hours=24)).isoformat(timespec="seconds"),),
        ).fetchall()

        first24 = float(rows24[0]["price"]) if rows24 else price
        prices24 = [float(r["price"]) for r in rows24] or [price]
        change24 = (price - first24) / first24 * 100.0 if first24 else 0.0

        portfolio = _portfolio(con, user_id, price)
        trades = con.execute(
            """
            SELECT side, shares, price, honey_amount, fee, realized_profit, created_at
            FROM exchange_trades
            WHERE user_id=?
            ORDER BY id DESC LIMIT 12
            """,
            (int(user_id),),
        ).fetchall()

        wallet = con.execute(
            "SELECT balance FROM honey_wallets WHERE user_id=?",
            (int(user_id),),
        ).fetchone()

    return {
        "enabled": cfg["enabled"],
        "symbol": "HNY",
        "price": round(price, 4),
        "change_24h_pct": round(change24, 2),
        "min_24h": round(min(prices24), 4),
        "max_24h": round(max(prices24), 4),
        "updated_at": state["updated_at"],
        "history": [
            {"price": round(float(r["price"]), 4), "time": r["created_at"]}
            for r in rows
        ],
        "portfolio": portfolio,
        "trades": [dict(r) for r in trades],
        "wallet_balance": int(wallet["balance"]) if wallet else 0,
        "fees": {
            "buy_pct": cfg["buy_fee_pct"],
            "sell_pct": cfg["sell_fee_pct"],
        },
        "range": range_key,
        "disclaimer": "Игровая биржа MurrlyBot. HNY не является реальной валютой или инвестицией.",
    }


def buy_hny(user_id: int, honey_amount: int):
    update_market_if_due()
    init_exchange_db()
    cfg = _settings()
    if not cfg["enabled"]:
        return {"status": "disabled"}

    honey_amount = int(honey_amount)
    if honey_amount <= 0:
        return {"status": "invalid"}

    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        state = con.execute(
            "SELECT current_price FROM exchange_state WHERE id=1"
        ).fetchone()
        price = float(state["current_price"])

        wallet = con.execute(
            "SELECT balance FROM honey_wallets WHERE user_id=?",
            (int(user_id),),
        ).fetchone()
        balance = int(wallet["balance"]) if wallet else 0
        if balance < honey_amount:
            con.rollback()
            return {"status": "insufficient", "need": honey_amount - balance}

        fee = honey_amount * cfg["buy_fee_pct"] / 100.0
        net = max(0.0, honey_amount - fee)
        shares = net / price if price > 0 else 0.0
        if shares <= 0:
            con.rollback()
            return {"status": "invalid"}

        now = bot_now().isoformat(timespec="seconds")
        con.execute(
            "UPDATE honey_wallets SET balance=balance-? WHERE user_id=?",
            (honey_amount, int(user_id)),
        )
        con.execute("""
            INSERT INTO exchange_portfolios(user_id, shares, cost_basis, realized_profit, updated_at)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                shares=shares+excluded.shares,
                cost_basis=cost_basis+excluded.cost_basis,
                updated_at=excluded.updated_at
        """, (int(user_id), shares, float(honey_amount), now))
        con.execute("""
            INSERT INTO exchange_trades(
                user_id, side, shares, price, honey_amount, fee, realized_profit, created_at
            ) VALUES (?, 'buy', ?, ?, ?, ?, NULL, ?)
        """, (int(user_id), shares, price, float(honey_amount), fee, now))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    try:
        from daily_tasks import record_task_progress
        record_task_progress(user_id, "trade", 1)
    except Exception:
        pass

    return {
        "status": "ok",
        "shares": round(shares, 6),
        "price": round(price, 4),
        "fee": round(fee, 2),
        "spent": honey_amount,
    }


def sell_hny(user_id: int, shares_to_sell: float):
    update_market_if_due()
    init_exchange_db()
    cfg = _settings()
    if not cfg["enabled"]:
        return {"status": "disabled"}

    shares_to_sell = float(shares_to_sell)
    if not math.isfinite(shares_to_sell) or shares_to_sell <= 0:
        return {"status": "invalid"}

    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        state = con.execute(
            "SELECT current_price FROM exchange_state WHERE id=1"
        ).fetchone()
        price = float(state["current_price"])

        row = con.execute(
            "SELECT shares, cost_basis, realized_profit FROM exchange_portfolios WHERE user_id=?",
            (int(user_id),),
        ).fetchone()
        if not row or float(row["shares"]) + 1e-9 < shares_to_sell:
            held = float(row["shares"]) if row else 0.0
            con.rollback()
            return {"status": "insufficient_shares", "held": round(held, 6)}

        held = float(row["shares"])
        basis = float(row["cost_basis"])
        old_realized = float(row["realized_profit"])
        ratio = shares_to_sell / held if held > 0 else 0
        basis_part = basis * ratio

        gross = shares_to_sell * price
        fee = gross * cfg["sell_fee_pct"] / 100.0
        net = max(0.0, gross - fee)
        realized = net - basis_part

        new_shares = max(0.0, held - shares_to_sell)
        new_basis = max(0.0, basis - basis_part)
        now = bot_now().isoformat(timespec="seconds")

        con.execute("""
            UPDATE exchange_portfolios
            SET shares=?, cost_basis=?, realized_profit=?, updated_at=?
            WHERE user_id=?
        """, (
            new_shares, new_basis, old_realized + realized, now, int(user_id)
        ))
        con.execute("""
            INSERT INTO honey_wallets(user_id, balance, total_earned, giveaways_claimed, biggest_claim)
            VALUES (?, ?, 0, 0, 0)
            ON CONFLICT(user_id) DO UPDATE SET balance=balance+excluded.balance
        """, (int(user_id), int(math.floor(net))))
        con.execute("""
            INSERT INTO exchange_trades(
                user_id, side, shares, price, honey_amount, fee, realized_profit, created_at
            ) VALUES (?, 'sell', ?, ?, ?, ?, ?, ?)
        """, (
            int(user_id), shares_to_sell, price, net, fee, realized, now
        ))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    try:
        from daily_tasks import record_task_progress
        record_task_progress(user_id, "trade", 1)
    except Exception:
        pass

    return {
        "status": "ok",
        "shares": round(shares_to_sell, 6),
        "price": round(price, 4),
        "fee": round(fee, 2),
        "received": int(math.floor(net)),
        "realized_profit": round(realized, 2),
    }


def admin_nudge(direction: str):
    init_exchange_db()
    pct = max(0.1, min(50.0, get_float("exchange.admin_nudge_pct", 5)))
    cfg = _settings()
    mult = 1 + pct / 100.0 if direction == "up" else 1 - pct / 100.0

    with connect() as con:
        row = con.execute("SELECT current_price FROM exchange_state WHERE id=1").fetchone()
        old = float(row["current_price"])
        new = max(cfg["min_price"], min(cfg["max_price"], old * mult))
        now = bot_now().isoformat(timespec="seconds")
        con.execute(
            "UPDATE exchange_state SET current_price=?, updated_at=? WHERE id=1",
            (new, now),
        )
        con.execute(
            "INSERT INTO exchange_prices(price, created_at) VALUES (?, ?)",
            (new, now),
        )
    return {"old": round(old, 4), "new": round(new, 4), "pct": pct}


def admin_reset_market():
    init_exchange_db()
    price = max(0.01, get_float("exchange.start_price", 20))
    now = bot_now().isoformat(timespec="seconds")
    with connect() as con:
        con.execute(
            "UPDATE exchange_state SET current_price=?, drift_pct=0, updated_at=? WHERE id=1",
            (price, now),
        )
        con.execute("DELETE FROM exchange_prices")
        con.execute(
            "INSERT INTO exchange_prices(price, created_at) VALUES (?, ?)",
            (price, now),
        )
    return {"price": round(price, 4)}


async def market_scheduler():
    while True:
        try:
            update_market_if_due()
        except Exception as exc:
            print(f"Exchange scheduler error: {exc}")
        await asyncio.sleep(20)
