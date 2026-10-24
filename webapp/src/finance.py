"""Personal finance storage (features/finance.md): accounts, transactions and scheduled transactions.

Amounts are integer minor units. Transactions carry tags like every other item, stored in `object_tags`; the tags that
started as finance tags sit under the shelf Finance (older label rows are left dormant in the database). Balances are always derived, never stored.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from . import db, finance_stats, tags

DEFAULT_CURRENCY_KEY = "finance_default_currency"
ABBREVIATION_MAX = 8

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS finance_accounts (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    abbreviation TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'bank',
    currency TEXT NOT NULL DEFAULT 'USD',
    opening_balance INTEGER NOT NULL DEFAULT 0,
    opening_date TEXT NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS finance_transactions (
    uid TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    account_uid TEXT NOT NULL,
    to_account_uid TEXT,
    type TEXT NOT NULL,
    amount INTEGER NOT NULL,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_finance_transactions_date ON finance_transactions(date);
CREATE INDEX IF NOT EXISTS idx_finance_transactions_account ON finance_transactions(account_uid);
CREATE TABLE IF NOT EXISTS finance_scheduled (
    uid TEXT PRIMARY KEY,
    date TEXT,
    description TEXT NOT NULL DEFAULT '',
    account_uid TEXT NOT NULL,
    to_account_uid TEXT,
    type TEXT NOT NULL,
    amount INTEGER NOT NULL,
    recurrence TEXT,
    task_uid TEXT,
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_finance_scheduled_task ON finance_scheduled(task_uid);
"""
TABLES = ["finance_accounts", "finance_transactions", "finance_scheduled"]
SORTS = {"date": "t.date", "description": "t.description COLLATE NOCASE", "amount": "t.amount",
         "account": "a.name COLLATE NOCASE"}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def add_look_columns(conn: sqlite3.Connection) -> None:
    """Databases from before 4.0.1: an account abbreviation and a tag colour and icon."""
    columns = [("finance_accounts", "abbreviation", "TEXT NOT NULL DEFAULT ''")]
    if tags._has(conn, "finance_tags"):  # only databases that still have the old finance tag table
        columns += [("finance_tags", "color", "TEXT NOT NULL DEFAULT 'gray'"), ("finance_tags", "icon", "TEXT NOT NULL DEFAULT ''")]
    for table, column, coldef in columns:
        db._ensure_column(conn, table, column, coldef)


def default_currency(conn: sqlite3.Connection) -> str:
    """The currency chosen in Settings, or '' when none was chosen."""
    value = db.get_app_meta(conn, DEFAULT_CURRENCY_KEY)
    return value if value in finance_stats.CURRENCIES else ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


# Accounts

def get_account(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM finance_accounts WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def list_accounts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every account with its derived balance and transaction count."""
    accounts = [dict(r) for r in conn.execute("SELECT * FROM finance_accounts ORDER BY name COLLATE NOCASE")]
    txns = [dict(r) for r in conn.execute("SELECT * FROM finance_transactions")]
    for a in accounts:
        mine = [t for t in txns if t["account_uid"] == a["uid"] or t["to_account_uid"] == a["uid"]]
        a["short"] = a["abbreviation"] or a["name"]
        a["balance"] = finance_stats.balance_on(a, mine)
        a["transaction_count"] = len(mine)
    return accounts


def validate_account(conn: sqlite3.Connection, data: dict, uid: str | None = None) -> tuple[dict, dict | None]:
    name = (data.get("name") or "").strip()
    if not name:
        return {}, _error("name", "Name is required")
    taken = conn.execute("SELECT uid FROM finance_accounts WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if taken and taken["uid"] != uid:
        return {}, _error("name", "An account with this name already exists")
    kind = data.get("type")
    if kind not in dict(finance_stats.ACCOUNT_TYPES):
        return {}, _error("type", "Choose an account type")
    currency = data.get("currency")
    if currency not in finance_stats.CURRENCIES:
        return {}, _error("currency", "Choose a currency")
    opening = finance_stats.parse_amount(data.get("opening_balance") or "")
    if opening is None:
        return {}, _error("opening_balance", "Opening balance must be a number")
    opening_date = (data.get("opening_date") or "").strip()
    try:
        datetime.strptime(opening_date, "%Y-%m-%d")
    except ValueError:
        return {}, _error("opening_date", "Opening date must be a date like 2026-10-31")
    if uid:
        existing = get_account(conn, uid)
        if existing and existing["currency"] != currency and transactions_exist(conn, uid):
            return {}, _error("currency", "The currency cannot change once the account has transactions")
    abbreviation = (data.get("abbreviation") or "").strip()[:ABBREVIATION_MAX]
    return {"name": name, "abbreviation": abbreviation, "type": kind, "currency": currency,
            "opening_balance": opening, "opening_date": opening_date}, None


def save_account(conn: sqlite3.Connection, clean: dict, uid: str | None = None) -> str:
    uid = uid or str(uuid.uuid4())
    conn.execute(
        "INSERT INTO finance_accounts (uid, name, abbreviation, type, currency, opening_balance, opening_date, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET name=excluded.name, abbreviation=excluded.abbreviation, "
        "type=excluded.type, currency=excluded.currency, opening_balance=excluded.opening_balance, opening_date=excluded.opening_date",
        (uid, clean["name"], clean.get("abbreviation") or "", clean["type"], clean["currency"], clean["opening_balance"], clean["opening_date"], _now()),
    )
    conn.commit()
    return uid


def transactions_exist(conn: sqlite3.Connection, account_uid: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM finance_transactions WHERE account_uid = ? OR to_account_uid = ? LIMIT 1",
        (account_uid, account_uid),
    ).fetchone() is not None


def delete_account(conn: sqlite3.Connection, uid: str) -> None:
    for row in conn.execute("SELECT uid FROM finance_scheduled WHERE account_uid = ? OR to_account_uid = ?", (uid, uid)).fetchall():
        delete_scheduled(conn, row["uid"])
    for row in conn.execute("SELECT uid FROM finance_transactions WHERE account_uid = ? OR to_account_uid = ?", (uid, uid)).fetchall():
        _delete_transaction_rows(conn, row["uid"])
    conn.execute("DELETE FROM finance_accounts WHERE uid = ?", (uid,))
    conn.commit()


# Transactions

def _delete_transaction_rows(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM finance_transactions WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_tags WHERE object_type = 'transaction' AND object_id = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'transaction' AND object_id = ?", (uid,))
    conn.execute("DELETE FROM object_contacts WHERE object_type = 'transaction' AND object_id = ?", (uid,))


def delete_transaction(conn: sqlite3.Connection, uid: str) -> None:
    _delete_transaction_rows(conn, uid)
    conn.commit()


def free_tags(conn: sqlite3.Connection) -> None:
    """Old databases: tags used to belong to a label group; now they stand alone. Nothing to do once the old table is gone."""
    if tags._has(conn, "finance_tags"):
        conn.execute("UPDATE OR IGNORE finance_tags SET group_name = '' WHERE group_name != ''")
        conn.execute("DELETE FROM finance_tags WHERE group_name != ''")


def _attach(conn: sqlite3.Connection, rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    uids = [r["uid"] for r in rows]
    marks = ", ".join("?" for _ in uids)
    linked: dict[str, list[str]] = {}
    for r in conn.execute(f"SELECT object_id, tag_name FROM object_tags WHERE object_type = 'transaction' AND object_id IN ({marks}) "
                          "ORDER BY tag_name COLLATE NOCASE", uids):
        linked.setdefault(r["object_id"], []).append(r["tag_name"])
    for row in rows:
        row["tags"] = linked.get(row["uid"], [])
    return rows


_ABBR = "COALESCE(NULLIF({x}.abbreviation, ''), {x}.name) AS {n}"
_SELECT = (
    "SELECT t.*, a.name AS account_name, " + _ABBR.format(x="a", n="account_abbr") + ", a.currency AS currency, b.name AS to_account_name, "
    + _ABBR.format(x="b", n="to_account_abbr") + " "
    "FROM finance_transactions t JOIN finance_accounts a ON a.uid = t.account_uid "
    "LEFT JOIN finance_accounts b ON b.uid = t.to_account_uid"
)


def get_transaction(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute(_SELECT + " WHERE t.uid = ?", (uid,)).fetchone()
    return _attach(conn, [dict(row)])[0] if row else None


def list_transactions(conn: sqlite3.Connection, filters: dict | None = None, limit: int | None = None, offset: int = 0) -> list[dict]:
    """Filters: q, account_uid, type, date_from, date_to, sort, dir. A transfer matches an account filter on either side."""
    f = filters or {}
    where: list[str] = []
    params: list[Any] = []
    if f.get("q"):
        where.append("(t.description LIKE ? OR a.name LIKE ? OR a.abbreviation LIKE ? OR EXISTS (SELECT 1 FROM object_tags g "
                     "WHERE g.object_type = 'transaction' AND g.object_id = t.uid AND g.tag_name LIKE ?))")
        params += [f"%{f['q']}%"] * 4
    if f.get("account_uid"):
        where.append("(t.account_uid = ? OR t.to_account_uid = ?)")
        params += [f["account_uid"]] * 2
    if f.get("type"):
        where.append("t.type = ?")
        params.append(f["type"])
    if f.get("date_from"):
        where.append("t.date >= ?")
        params.append(f["date_from"])
    if f.get("date_to"):
        where.append("t.date <= ?")
        params.append(f["date_to"])
    order = SORTS.get(f.get("sort") or "date", SORTS["date"])
    direction = "ASC" if f.get("dir") == "asc" else "DESC"
    sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order} {direction}, t.created_at DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]
    return _attach(conn, [dict(r) for r in conn.execute(sql, params)])


def all_transactions(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM finance_transactions")]


def validate_transaction(conn: sqlite3.Connection, data: dict) -> tuple[dict, dict | None]:
    day = (data.get("date") or "").strip()
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return {}, _error("date", "Date must be a date like 2026-10-31")
    kind = data.get("type")
    if kind not in dict(finance_stats.TRANSACTION_TYPES):
        return {}, _error("type", "Type must be income, expense or transfer")
    amount = finance_stats.parse_amount(data.get("amount") or "")
    if amount is None or amount == 0:
        return {}, _error("amount", "Amount must be a number above zero")
    amount = abs(amount)
    account = get_account(conn, data.get("account_uid") or "")
    if account is None:
        return {}, _error("account_uid", "Choose an account")
    if day < account["opening_date"]:
        return {}, _error("date", f"The account starts on {account['opening_date']}")
    clean = {"date": day, "type": kind, "amount": amount, "account_uid": account["uid"], "to_account_uid": None,
             "description": (data.get("description") or "").strip(), "tags": []}
    if kind == "transfer":
        target = get_account(conn, data.get("to_account_uid") or "")
        if target is None:
            return {}, _error("to_account_uid", "Choose the account the money goes to")
        if target["uid"] == account["uid"]:
            return {}, _error("to_account_uid", "A transfer needs two different accounts")
        if target["currency"] != account["currency"]:
            return {}, _error("to_account_uid", "Both accounts need the same currency")
        if day < target["opening_date"]:
            return {}, _error("date", f"The account {target['name']} starts on {target['opening_date']}")
        clean["to_account_uid"] = target["uid"]
    else:
        clean["tags"] = [t.strip() for t in (data.get("tags") or []) if t and t.strip()]
    return clean, None


def save_transaction(conn: sqlite3.Connection, clean: dict, uid: str | None = None) -> str:
    uid = uid or str(uuid.uuid4())
    conn.execute(
        "INSERT INTO finance_transactions (uid, date, description, account_uid, to_account_uid, type, amount, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET date=excluded.date, description=excluded.description, "
        "account_uid=excluded.account_uid, to_account_uid=excluded.to_account_uid, type=excluded.type, amount=excluded.amount",
        (uid, clean["date"], clean["description"], clean["account_uid"], clean["to_account_uid"], clean["type"], clean["amount"], _now()),
    )
    tags.record(conn, "transaction", uid, list(dict.fromkeys(clean["tags"])))
    conn.commit()
    return uid


def import_rows(conn: sqlite3.Connection, rows: list[dict]) -> tuple[int, list[str]]:
    """Creates a transaction per parsed CSV row; unknown accounts and invalid rows are reported, never created."""
    by_name = {a["name"].lower(): a["uid"] for a in conn.execute("SELECT uid, name FROM finance_accounts")}
    created, problems = 0, []
    for number, row in enumerate(rows, start=2):
        account = by_name.get(row["account"].lower())
        target = by_name.get(row["to_account"].lower()) if row["to_account"] else None
        if account is None:
            problems.append(f"Line {number}: there is no account named {row['account']}")
            continue
        clean, error = validate_transaction(conn, {
            "date": row["date"], "type": row["type"], "amount": finance_stats.amount_input(row["amount"]),
            "account_uid": account, "to_account_uid": target, "description": row["description"],
            "tags": [t for t in row["tags"].split(";") if t.strip()],
        })
        if error:
            problems.append(f"Line {number}: {error['message']}")
            continue
        save_transaction(conn, clean)
        created += 1
    return created, problems


def purge(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM object_labels WHERE object_type = 'transaction'")
    for table in TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def backup_rows(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    return {
        "finance_scheduled": list_scheduled(conn),
        "finance_accounts": [dict(r) for r in conn.execute("SELECT * FROM finance_accounts")],
        "finance_transactions": list_transactions(conn),
        "finance_tags": [dict(r) for r in conn.execute(
            "SELECT name, color, icon FROM label_tags WHERE name IN (SELECT tag_name FROM object_tags WHERE object_type IN ('transaction', 'scheduled'))")]
        if tags._has(conn, "label_tags") else [],
    }


def restore_rows(conn: sqlite3.Connection, payload: dict) -> int:
    count = 0
    for row in payload.get("finance_tags", []):  # backups from before tags lived under shelves
        tags.add_finance_tag(conn, row["name"], row.get("color") or "gray", row.get("icon") or "")
    for row in payload.get("finance_accounts", []):
        clean = {k: row[k] for k in ("name", "type", "currency", "opening_balance", "opening_date")} | {"abbreviation": row.get("abbreviation") or ""}
        save_account(conn, clean, row["uid"])
        count += 1
    for row in payload.get("finance_transactions", []):
        clean = {k: row.get(k) for k in ("date", "description", "account_uid", "to_account_uid", "type", "amount")}
        clean.update(tags=row.get("tags") or [])
        save_transaction(conn, clean, row["uid"])
        count += 1
    for row in payload.get("finance_scheduled", []):
        save_scheduled(conn, {k: row.get(k) for k in ("date", "description", "account_uid", "to_account_uid", "type", "amount",
                                                     "recurrence", "task_uid")} | {"tags": row.get("tags") or []}, row["uid"])
        count += 1
    conn.commit()
    return count


# Scheduled transactions: one model for a pending one-off and a recurring transaction.
# A scheduled row is shown once, at the top of the table, with its next date. Posting it creates a real
# transaction; a recurring row then moves to its next date and a one-off row is removed.

def _scheduled_select() -> str:
    return (
        "SELECT s.*, a.name AS account_name, " + _ABBR.format(x="a", n="account_abbr") + ", a.currency AS currency, b.name AS to_account_name, "
        + _ABBR.format(x="b", n="to_account_abbr") + " "
        "FROM finance_scheduled s JOIN finance_accounts a ON a.uid = s.account_uid "
        "LEFT JOIN finance_accounts b ON b.uid = s.to_account_uid"
    )


def _decorate_scheduled(conn: sqlite3.Connection, row: dict) -> dict:
    row["tags"] = tags.tags_for_object(conn, "scheduled", row["uid"])
    task = db.get_task(conn, row["task_uid"]) if row.get("task_uid") else None
    row["task_title"] = task["title"] if task else ""
    return row


def get_scheduled(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute(_scheduled_select() + " WHERE s.uid = ?", (uid,)).fetchone()
    return _decorate_scheduled(conn, dict(row)) if row else None


def list_scheduled(conn: sqlite3.Connection, filters: dict | None = None, task_uid: str | None = None) -> list[dict]:
    """Scheduled rows, dated ones first by date. Filters: q, account_uid, type (the period never applies)."""
    f = filters or {}
    where, params = [], []
    if task_uid:
        where.append("s.task_uid = ?")
        params.append(task_uid)
    if f.get("account_uid"):
        where.append("(s.account_uid = ? OR s.to_account_uid = ?)")
        params += [f["account_uid"]] * 2
    if f.get("type"):
        where.append("s.type = ?")
        params.append(f["type"])
    sql = _scheduled_select() + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY s.date IS NULL, s.date, s.created_at"
    rows = [_decorate_scheduled(conn, dict(r)) for r in conn.execute(sql, params)]
    if f.get("q"):
        needle = f["q"].lower()
        rows = [r for r in rows if needle in " ".join([r["description"], r["account_name"], r["task_title"]]).lower()]
    return rows


def validate_scheduled(conn: sqlite3.Connection, data: dict) -> tuple[dict, dict | None]:
    kind = data.get("type")
    if kind not in dict(finance_stats.TRANSACTION_TYPES):
        return {}, _error("type", "Choose a type")
    amount = finance_stats.parse_amount(data.get("amount") or "")
    if amount is None or amount == 0:
        return {}, _error("amount", "Amount must be a number above zero")
    account = get_account(conn, data.get("account_uid") or "")
    if account is None:
        return {}, _error("account_uid", "Choose an account")
    day = (data.get("date") or "").strip()
    if day:
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            return {}, _error("date", "Date must be a date like 2026-10-31")
    rule = (data.get("recurrence") or "").strip()
    if rule and not finance_stats.valid_rule(rule):
        return {}, _error("recurrence", "Recurrence is not a valid rule")
    task_uid = (data.get("task_uid") or "").strip() or None
    if task_uid and db.get_task(conn, task_uid) is None:
        return {}, _error("task_uid", "Choose an existing task")
    clean = {"date": day or None, "type": kind, "amount": abs(amount), "account_uid": account["uid"], "to_account_uid": None,
             "description": (data.get("description") or "").strip(), "recurrence": rule or None, "task_uid": task_uid,
             "tags": [] if kind == "transfer" else list(dict.fromkeys(t.strip() for t in (data.get("tags") or []) if t and t.strip()))}
    if kind == "transfer":
        target = get_account(conn, data.get("to_account_uid") or "")
        if target is None:
            return {}, _error("to_account_uid", "Choose the account the money goes to")
        if target["uid"] == account["uid"]:
            return {}, _error("to_account_uid", "A transfer needs two different accounts")
        if target["currency"] != account["currency"]:
            return {}, _error("to_account_uid", "Both accounts need the same currency")
        clean["to_account_uid"] = target["uid"]
    return clean, None


def save_scheduled(conn: sqlite3.Connection, clean: dict, uid: str | None = None) -> str:
    uid = uid or str(uuid.uuid4())
    conn.execute(
        "INSERT INTO finance_scheduled (uid, date, description, account_uid, to_account_uid, type, amount, recurrence, task_uid, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET date=excluded.date, description=excluded.description, "
        "account_uid=excluded.account_uid, to_account_uid=excluded.to_account_uid, type=excluded.type, amount=excluded.amount, "
        "recurrence=excluded.recurrence, task_uid=excluded.task_uid",
        (uid, clean["date"], clean["description"], clean["account_uid"], clean["to_account_uid"], clean["type"], clean["amount"],
         clean["recurrence"], clean["task_uid"], _now()),
    )
    tags.record(conn, "scheduled", uid, list(clean.get("tags", [])))
    conn.commit()
    return uid


def delete_scheduled(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM finance_scheduled WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_tags WHERE object_type = 'scheduled' AND object_id = ?", (uid,))
    conn.execute("DELETE FROM object_contacts WHERE object_type = 'scheduled' AND object_id = ?", (uid,))
    conn.commit()


def post_scheduled(conn: sqlite3.Connection, uid: str, today: str) -> str | None:
    """Turns a scheduled row into a real transaction dated `today` (not before the account opens), then moves a
    recurring row to its next date or removes a one-off. Returns the new transaction's uid."""
    row = get_scheduled(conn, uid)
    if row is None:
        return None
    account = get_account(conn, row["account_uid"])
    day = max(today, account["opening_date"]) if account else today
    clean, error = validate_transaction(conn, {
        "date": day, "type": row["type"], "amount": finance_stats.amount_input(row["amount"]), "account_uid": row["account_uid"],
        "to_account_uid": row["to_account_uid"], "description": row["description"], "tags": row["tags"],
    })
    if error:
        return None
    new_uid = save_transaction(conn, clean)
    db.set_object_contacts(conn, "transaction", new_uid, [c["uid"] for c in db.list_object_contacts(conn, "scheduled", uid)])
    following = finance_stats.next_occurrence(row["recurrence"], row["date"] or today, datetime.strptime(today, "%Y-%m-%d").date()) if row["recurrence"] else ""
    if following:
        conn.execute("UPDATE finance_scheduled SET date = ? WHERE uid = ?", (following, uid))
        conn.commit()
    else:
        delete_scheduled(conn, uid)
    return new_uid


def post_for_task(conn: sqlite3.Connection, task_uid: str, today: str) -> int:
    """Posts every scheduled row linked to a task that was just completed; returns how many became real."""
    return sum(1 for row in list_scheduled(conn, task_uid=task_uid) if post_scheduled(conn, row["uid"], today))


def unlink_task(conn: sqlite3.Connection, task_uid: str) -> None:
    """A deleted task leaves its scheduled rows behind, now unlinked."""
    conn.execute("UPDATE finance_scheduled SET task_uid = NULL WHERE task_uid = ?", (task_uid,))
    conn.commit()


def sync_task_rows(conn: sqlite3.Connection, task_uid: str, rows: list[dict]) -> list[dict]:
    """Makes a task's scheduled rows match the edit form's list: rows with a uid update, new rows are created and rows
    no longer listed are deleted. Returns the validation errors; nothing is written when there are any."""
    cleaned, errors = [], []
    for row in rows:
        clean, error = validate_scheduled(conn, {**row, "task_uid": task_uid})
        if error:
            errors.append(error)
        else:
            cleaned.append((row.get("uid") or None, clean))
    if errors:
        return errors
    keep = {uid for uid, _ in cleaned if uid}
    for existing in list_scheduled(conn, task_uid=task_uid):
        if existing["uid"] not in keep:
            delete_scheduled(conn, existing["uid"])
    for uid, clean in cleaned:
        save_scheduled(conn, clean, uid if uid and get_scheduled(conn, uid) else None)
    conn.commit()
    return []
