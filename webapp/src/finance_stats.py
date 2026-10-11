"""Pure money maths for the finance module (features/finance.md): amounts, balances, monthly totals, chart geometry and CSV."""

from __future__ import annotations

import csv
import io
import math
import re
from collections import defaultdict
from datetime import date, datetime

CURRENCIES = ["USD", "EUR", "RON", "GBP", "CHF", "CAD"]
ACCOUNT_TYPES = [("cash", "Cash"), ("bank", "Bank account"), ("savings", "Savings"), ("credit_card", "Credit card")]
TRANSACTION_TYPES = [("expense", "Expense"), ("income", "Income"), ("transfer", "Transfer")]
CSV_COLUMNS = ["date", "description", "account", "type", "amount", "label", "tags", "to_account"]


def parse_amount(text: str) -> int | None:
    """'12.50', '12,50' and '1,234.56' to minor units; None when it is not a plain positive-or-negative number."""
    value = (text or "").strip().replace(" ", "")
    if not re.fullmatch(r"-?[\d.,]+", value):
        return None
    sign = -1 if value.startswith("-") else 1
    value = value.lstrip("-")
    match = re.fullmatch(r"([\d.,]*?)[.,](\d{1,2})", value)
    whole, cents = (match.group(1), match.group(2)) if match else (value, "")
    whole = re.sub(r"[.,]", "", whole)
    if not whole and not cents:
        return None
    return sign * (int(whole or 0) * 100 + int(cents.ljust(2, "0") or 0))


def format_money(minor: int, currency: str = "", signed: bool = False) -> str:
    sign = "-" if minor < 0 else ("+" if signed and minor > 0 else "")
    whole, cents = divmod(abs(minor), 100)
    text = f"{sign}{whole:,}.{cents:02d}"
    return f"{text} {currency}".strip()


def amount_input(minor: int) -> str:
    whole, cents = divmod(abs(minor), 100)
    return f"{'-' if minor < 0 else ''}{whole}.{cents:02d}"


def effect_on(account_uid: str, txn: dict) -> int:
    """Signed change a transaction makes to one account's balance."""
    if txn["type"] == "income" and txn["account_uid"] == account_uid:
        return txn["amount"]
    if txn["type"] == "expense" and txn["account_uid"] == account_uid:
        return -txn["amount"]
    if txn["type"] == "transfer":
        if txn["account_uid"] == account_uid:
            return -txn["amount"]
        if txn.get("to_account_uid") == account_uid:
            return txn["amount"]
    return 0


def balance_on(account: dict, txns: list[dict], on: str | None = None) -> int:
    """Opening balance plus every transaction from the opening date up to `on` (inclusive)."""
    total = account["opening_balance"]
    for t in txns:
        if t["date"] < account["opening_date"] or (on and t["date"] > on):
            continue
        total += effect_on(account["uid"], t)
    return total


def month_key(day: str) -> str:
    return day[:7]


def month_add(key: str, months: int) -> str:
    year, month = int(key[:4]), int(key[5:7])
    index = year * 12 + month - 1 + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_end(key: str) -> str:
    nxt = month_add(key, 1)
    last = date.fromisoformat(nxt + "-01").toordinal() - 1
    return date.fromordinal(last).isoformat()


def months_between(first: str, last: str) -> list[str]:
    keys, current = [], first
    while current <= last:
        keys.append(current)
        current = month_add(current, 1)
    return keys


def totals(txns: list[dict]) -> dict[str, int]:
    """Income, expenses and net for the given transactions; transfers never count."""
    income = sum(t["amount"] for t in txns if t["type"] == "income")
    expenses = sum(t["amount"] for t in txns if t["type"] == "expense")
    return {"income": income, "expenses": expenses, "net": income - expenses}


def balance_trend(accounts: list[dict], txns: list[dict], months: list[str]) -> list[dict]:
    """Total balance of `accounts` at the end of each month (one currency only)."""
    by_account: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        by_account[t["account_uid"]].append(t)
        if t.get("to_account_uid"):
            by_account[t["to_account_uid"]].append(t)
    return [
        {"month": m, "balance": sum(balance_on(a, by_account[a["uid"]], month_end(m)) for a in accounts)}
        for m in months
    ]


def spending_by_label(expenses: list[dict]) -> list[dict]:
    sums: dict[str, int] = defaultdict(int)
    for t in expenses:
        sums[t.get("label") or ""] += t["amount"]
    total = sum(sums.values()) or 1
    rows = [{"label": k, "amount": v, "share": v / total} for k, v in sums.items()]
    return sorted(rows, key=lambda r: -r["amount"])


def line_chart(points: list[dict], width: int = 640, height: int = 220, pad: int = 28) -> dict:
    """SVG geometry for the balance trend: polyline points, dots and the vertical range."""
    if not points:
        return {"path": "", "dots": [], "min": 0, "max": 0}
    values = [p["balance"] for p in points]
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = (width - 2 * pad) / max(len(points) - 1, 1)
    dots = []
    for i, p in enumerate(points):
        x = pad + (i * step if len(points) > 1 else (width - 2 * pad) / 2)
        y = height - pad - (p["balance"] - low) / span * (height - 2 * pad)
        dots.append({"x": round(x, 1), "y": round(y, 1), **p})
    return {"path": " ".join(f"{d['x']},{d['y']}" for d in dots), "dots": dots, "min": low, "max": high,
            "width": width, "height": height}


def doughnut(parts: list[dict], radius: float = 80, inner: float = 50, center: float = 100) -> list[dict]:
    """Arc paths for each part (`share` 0..1); a single full part is drawn as two half arcs."""
    out, angle = [], -math.pi / 2
    for part in parts:
        sweep = min(part["share"], 0.9999) * 2 * math.pi
        end = angle + sweep
        large = 1 if sweep > math.pi else 0

        def pt(r, a):
            return f"{center + r * math.cos(a):.2f} {center + r * math.sin(a):.2f}"

        path = (f"M {pt(radius, angle)} A {radius} {radius} 0 {large} 1 {pt(radius, end)} "
                f"L {pt(inner, end)} A {inner} {inner} 0 {large} 0 {pt(inner, angle)} Z")
        out.append({**part, "path": path})
        angle = end
    return out


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "date": row["date"], "description": row["description"], "account": row["account_name"],
            "type": row["type"], "amount": amount_input(row["amount"]), "label": row.get("label") or "",
            "tags": ";".join(row.get("tags") or []), "to_account": row.get("to_account_name") or "",
        })
    return buf.getvalue()


def parse_csv(text: str) -> tuple[list[dict], list[str]]:
    """(rows, problems): each row is a dict with CSV_COLUMNS keys; a row that cannot be read is reported by line number."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    rows, problems = [], []
    if not reader.fieldnames or not {"date", "account", "amount"} <= {f.strip().lower() for f in reader.fieldnames}:
        return [], ["The file needs at least the columns date, account and amount."]
    for number, raw in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        try:
            date.fromisoformat(row.get("date", ""))
        except ValueError:
            problems.append(f"Line {number}: the date must look like 2026-10-31")
            continue
        amount = parse_amount(row.get("amount", ""))
        if amount is None:
            problems.append(f"Line {number}: the amount is not a number")
            continue
        kind = (row.get("type") or ("income" if amount > 0 else "expense")).lower()
        if kind not in {k for k, _ in TRANSACTION_TYPES}:
            problems.append(f"Line {number}: the type must be income, expense or transfer")
            continue
        rows.append({**{c: row.get(c, "") for c in CSV_COLUMNS}, "type": kind, "amount": abs(amount)})
    return rows, problems


def next_occurrence(rule: str, start: str, after: date) -> str | None:
    """The first date after `after` that an RRULE string produces, counting from `start` ('' when it never recurs again)."""
    from dateutil.rrule import rrulestr

    try:
        begin = datetime.fromisoformat((start or after.isoformat())[:10])
        found = rrulestr(rule.replace("RRULE:", ""), dtstart=begin).after(datetime.combine(after, datetime.max.time()))
    except (ValueError, TypeError):
        return None
    return found.date().isoformat() if found else ""


def valid_rule(rule: str) -> bool:
    from dateutil.rrule import rrulestr

    try:
        rrulestr(rule.replace("RRULE:", ""), dtstart=datetime(2026, 1, 1))
    except (ValueError, TypeError):
        return False
    return True
