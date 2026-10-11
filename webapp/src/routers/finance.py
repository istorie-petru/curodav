"""Personal finance pages: Overview, Transactions and Accounts (features/finance.md)."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Header, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import clock, db, finance, finance_stats
from ..deps import get_db, respond, templates, wants_json
from .labels import COLORS

router = APIRouter(prefix="/finance", tags=["finance"])
settings_router = APIRouter(prefix="/settings/finance-accounts", tags=["finance-settings"])

RANGES = [
    ("month", "This month"), ("last_month", "Last month"), ("3m", "Last 3 months"),
    ("6m", "Last 6 months"), ("year", "This year"), ("all", "All time"), ("custom", "Custom range"),
]
PAGE_SIZE = 100
TREND_MONTHS = 6


def date_range(preset: str, today: date) -> tuple[str, str]:
    this = today.isoformat()[:7]
    if preset == "last_month":
        prev = finance_stats.month_add(this, -1)
        return prev + "-01", finance_stats.month_end(prev)
    if preset == "3m":
        return finance_stats.month_add(this, -2) + "-01", this_end(this)
    if preset == "6m":
        return finance_stats.month_add(this, -5) + "-01", this_end(this)
    if preset == "year":
        return f"{today.year}-01-01", f"{today.year}-12-31"
    if preset == "all":
        return "", ""
    return this + "-01", this_end(this)


def this_end(month: str) -> str:
    return finance_stats.month_end(month)


_NONE = {"uid": "", "name": "None"}


def _label_choices(conn) -> list[dict]:
    return [{"uid": n, "name": n} for n in sorted(db.list_all_known_label_names(conn), key=str.lower)]


def _group_choices(conn) -> list[dict]:
    return [{"value": "", "name": "All groups"}] + [{"value": g["name"], "name": g["name"]} for g in db.list_groups(conn)]


def _error_response(error: dict, x_requested_with, back: str):
    if wants_json(x_requested_with):
        return JSONResponse({"detail": [{"loc": ["body", error["field"]], "msg": error["message"]}]}, status_code=422)
    return RedirectResponse(url=f"{back}?{urlencode({'error': error['message']})}", status_code=303)


def _header_links(active: str) -> list[dict]:
    return [{"url": u, "icon": i, "title": t, "key": k} for k, u, i, t in (
        ("overview", "/finance", "pie-chart", "Overview"),
        ("transactions", "/finance/transactions", "list", "Transactions"))
        if k != active]


# Overview

def _assign_colors(conn, breakdown: list[dict]) -> None:
    """Each slice gets its label's colour; a repeat (labels share the default colour) takes the next unused one."""
    used: set[str] = set()
    spare = iter(c for c in COLORS if c not in ("gray", "slate"))
    for row in breakdown:
        color = db.effective_label_config(conn, row["label"])["color"] if row["label"] else "gray"
        while color in used and row["label"]:
            color = next(spare, "gray")
        row["color"] = color
        used.add(color)


def _overview_sections(conn, start: str, end: str, group: str) -> list[dict]:
    accounts = finance.list_accounts(conn)
    everything = finance.all_transactions(conn)
    in_range = finance.list_transactions(conn, {"date_from": start, "date_to": end, "group": group})
    today = clock.today().isoformat()
    last_month = (end or today)[:7]
    first_month = min(start[:7] if start else last_month, finance_stats.month_add(last_month, -(TREND_MONTHS - 1)))
    months = finance_stats.months_between(first_month, last_month)
    sections = []
    for currency in dict.fromkeys(a["currency"] for a in accounts):
        mine = [a for a in accounts if a["currency"] == currency]
        mine_uids = {a["uid"] for a in mine}
        spent = [t for t in in_range if t["currency"] == currency and t["type"] == "expense"]
        counted = [t for t in in_range if t["currency"] == currency]
        trend = finance_stats.balance_trend(mine, [t for t in everything if t["account_uid"] in mine_uids], months)
        cash_on = end or today
        breakdown = finance_stats.spending_by_label(spent)
        _assign_colors(conn, breakdown)
        sections.append({
            "currency": currency,
            "cash": sum(finance_stats.balance_on(a, [t for t in everything if a["uid"] in (t["account_uid"], t["to_account_uid"])], cash_on) for a in mine),
            "totals": finance_stats.totals(counted),
            "chart": finance_stats.line_chart(trend),
            "breakdown": finance_stats.doughnut(breakdown),
        })
    return sections


@router.get("")
def overview(request: Request, range: str = "month", group: str = "", conn=Depends(get_db)):
    start, end = date_range(range, clock.today())
    return templates.TemplateResponse("finance_overview.html", {
        "request": request, "active_tab": "finance", "links": _header_links("overview"),
        "sections": _overview_sections(conn, start, end, group), "range": range, "range_items": [{"value": k, "name": n} for k, n in RANGES],
        "group": group, "group_items": _group_choices(conn), "has_accounts": bool(finance.list_accounts(conn)),
        "money": finance_stats.format_money,
    })


# Transactions

def _filters(q: str, account: str, type: str, label: str, group: str, range: str, sort: str, dir: str,
             date_from: str = "", date_to: str = "") -> dict:
    start, end = (date_from, date_to) if range == "custom" else date_range(range, clock.today())
    return {"q": q.strip(), "account_uid": account, "type": type, "label": label, "group": group,
            "date_from": start, "date_to": end, "sort": sort, "dir": dir}


@router.get("/transactions")
def transactions(request: Request, q: str = "", account: str = "", type: str = "", label: str = "", group: str = "",
                 range: str = "all", date_from: str = "", date_to: str = "", sort: str = "date", dir: str = "desc",
                 limit: int = PAGE_SIZE, conn=Depends(get_db)):
    limit = max(PAGE_SIZE, min(limit, 5000))
    rows = finance.list_transactions(conn, _filters(q, account, type, label, group, range, sort, dir, date_from, date_to))
    sums = {}
    for t in rows:
        s = sums.setdefault(t["currency"], [])
        s.append(t)
    summary = [{"currency": c, **finance_stats.totals(items)} for c, items in sums.items()]
    accounts = finance.list_accounts(conn)
    pending = finance.list_scheduled(conn, {"q": q.strip(), "account_uid": account, "type": type, "label": label, "group": group})
    query = {"q": q, "account": account, "type": type, "label": label, "group": group, "range": range}
    if range == "custom":
        query.update(date_from=date_from, date_to=date_to)
    return templates.TemplateResponse("finance_transactions.html", {
        "request": request, "active_tab": "finance", "links": _header_links("transactions"),
        "rows": rows[:limit], "pending": pending, "total": len(rows), "has_more": len(rows) > limit, "limit": limit, "summary": summary,
        "q": q, "account": account, "type": type, "label": label, "group": group, "range": range, "sort": sort, "dir": dir, "date_from": date_from, "date_to": date_to,
        "range_items": [{"value": k, "name": n} for k, n in RANGES],
        "account_items": [{"value": "", "name": "All accounts"}] + [{"value": a["uid"], "name": a["name"]} for a in accounts],
        "type_items": [{"value": "", "name": "All types"}] + [{"value": k, "name": n} for k, n in finance_stats.TRANSACTION_TYPES],
        "label_items": [{"value": "", "name": "All labels"}] + [{"value": c["uid"], "name": c["name"]} for c in _label_choices(conn)],
        "group_items": _group_choices(conn), "has_accounts": bool(accounts),
        "query": urlencode({k: v for k, v in query.items() if v}), "money": finance_stats.format_money,
    })


STATUS_ITEMS = [{"uid": "posted", "name": "Posted"}, {"uid": "scheduled", "name": "Scheduled"}]


def _task_items(conn) -> list[dict]:
    return [_NONE] + [{"uid": t["uid"], "name": t["title"]} for t in db.list_tasks(conn) if t.get("status") not in ("done", "archived")]


def transaction_form_context(request: Request, conn, txn: dict | None, action: str, scheduled: bool = False) -> dict:
    accounts = finance.list_accounts(conn)
    label = (txn or {}).get("effective_label" if scheduled else "label", "")
    return {
        "request": request, "t": txn, "form_action": action, "kind": (txn or {}).get("type", ""),
        "status": "scheduled" if scheduled else "", "status_items": [_NONE] + STATUS_ITEMS, "status_fixed": scheduled,
        "task_items": _task_items(conn), "recurrence": (txn or {}).get("recurrence") or "",
        "account_items": [_NONE] + [{"uid": a["uid"], "name": f"{a['name']} ({a['currency']})"} for a in accounts],
        "type_items": [_NONE] + [{"uid": k, "name": n} for k, n in finance_stats.TRANSACTION_TYPES],
        "label_items": [_NONE] + _label_choices(conn),
        "amount_text": finance_stats.amount_input((txn or {}).get("amount", 0)) if txn else "",
        **_tag_context(conn, label, (txn or {}).get("tags", [])),
    }


def _tag_context(conn, label: str, selected: list[str]) -> dict:
    known = finance.tags_for_group(conn, finance.label_group(conn, label))
    names = list(dict.fromkeys(known + list(selected)))
    return {"tag_items": [{"uid": n, "name": n} for n in names], "tag_selected": selected}


@router.get("/transactions/new")
def new_transaction_modal(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse("finance_transaction_modal.html",
                                      transaction_form_context(request, conn, None, "/finance/transactions"))


@router.get("/transactions/tag-field")
def tag_field(request: Request, label: str = "", tags: list[str] = Query([]), conn=Depends(get_db)):
    """The tag picker for the chosen label, swapped into the transaction modal; tags already picked stay picked."""
    return templates.TemplateResponse("_finance_tag_field.html", {"request": request, **_tag_context(conn, label, tags)})


@router.get("/transactions/{uid}/edit")
def edit_transaction_modal(uid: str, request: Request, conn=Depends(get_db)):
    txn = finance.get_transaction(conn, uid)
    if txn is None:
        return RedirectResponse(url="/finance/transactions", status_code=303)
    return templates.TemplateResponse("finance_transaction_modal.html",
                                      transaction_form_context(request, conn, txn, f"/finance/transactions/{uid}/update"))


async def _form_values(request: Request) -> dict:
    form = await request.form()
    data = {k: form.get(k, "") for k in ("date", "type", "account_uid", "to_account_uid", "amount", "description", "label",
                                         "status", "recurrence", "task_uid")}
    data["tags"] = form.getlist("tags")
    return data


def _save_scheduled(conn, data: dict, x_requested_with, uid: str | None):
    clean, error = finance.validate_scheduled(conn, data)
    if error:
        return _error_response(error, x_requested_with, "/finance/transactions")
    new_uid = finance.save_scheduled(conn, clean, uid)
    return respond(x_requested_with, "/finance/transactions", status_code=200 if uid else 201, uid=new_uid)


def _save_transaction(conn, data: dict, x_requested_with, uid: str | None):
    if data.get("status") == "scheduled":
        return _save_scheduled(conn, data, x_requested_with, uid)
    if not data.get("status") and uid is None:
        return _error_response({"field": "status", "message": "Choose a status"}, x_requested_with, "/finance/transactions")
    clean, error = finance.validate_transaction(conn, data)
    if error:
        return _error_response(error, x_requested_with, "/finance/transactions")
    new_uid = finance.save_transaction(conn, clean, uid)
    return respond(x_requested_with, "/finance/transactions", status_code=200 if uid else 201, uid=new_uid)


@router.post("/transactions")
async def create_transaction(request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    return _save_transaction(conn, await _form_values(request), x_requested_with, None)


@router.post("/transactions/{uid}/update")
async def update_transaction(uid: str, request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if finance.get_transaction(conn, uid) is None:
        return RedirectResponse(url="/finance/transactions", status_code=303)
    return _save_transaction(conn, await _form_values(request), x_requested_with, uid)


@router.get("/scheduled/{uid}/edit")
def edit_scheduled_modal(uid: str, request: Request, conn=Depends(get_db)):
    row = finance.get_scheduled(conn, uid)
    if row is None:
        return RedirectResponse(url="/finance/transactions", status_code=303)
    return templates.TemplateResponse("finance_transaction_modal.html", {
        **transaction_form_context(request, conn, row, f"/finance/scheduled/{uid}/update", scheduled=True),
        "delete_url": f"/finance/scheduled/{uid}/delete"})


@router.post("/scheduled/{uid}/update")
async def update_scheduled(uid: str, request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if finance.get_scheduled(conn, uid) is None:
        return RedirectResponse(url="/finance/transactions", status_code=303)
    data = await _form_values(request)
    data["status"] = "scheduled"
    return _save_scheduled(conn, data, x_requested_with, uid)


@router.post("/scheduled/{uid}/post")
def post_scheduled(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    """Turns a scheduled row into a real transaction dated today."""
    finance.post_scheduled(conn, uid, clock.today().isoformat())
    return respond(x_requested_with, "/finance/transactions")


@router.post("/scheduled/{uid}/delete")
def delete_scheduled(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    finance.delete_scheduled(conn, uid)
    return respond(x_requested_with, "/finance/transactions")


@router.post("/transactions/{uid}/delete")
def delete_transaction(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    finance.delete_transaction(conn, uid)
    return respond(x_requested_with, "/finance/transactions")


# Accounts

@settings_router.get("")
def accounts_page(request: Request, conn=Depends(get_db)):
    accounts = finance.list_accounts(conn)
    return templates.TemplateResponse("finance_accounts.html", {
        "request": request, "crumbs": [{"url": "/settings", "name": "Settings"}], "active_tab": "settings_finance_accounts", "accounts": accounts,
        "type_names": dict(finance_stats.ACCOUNT_TYPES), "money": finance_stats.format_money,
    })


def _account_context(request: Request, conn, account: dict | None, action: str) -> dict:
    return {
        "request": request, "a": account, "form_action": action,
        "type_items": [_NONE] + [{"uid": k, "name": n} for k, n in finance_stats.ACCOUNT_TYPES],
        "currency_items": [_NONE] + [{"uid": c, "name": c} for c in finance_stats.CURRENCIES],
        "currency": (account or {}).get("currency") or finance.default_currency(conn),
        "opening_text": finance_stats.amount_input(account["opening_balance"]) if account else "",
        "opening_date": (account or {}).get("opening_date") or "",
        "locked_currency": bool(account) and finance.transactions_exist(conn, account["uid"]),
    }


@settings_router.get("/new")
def new_account_modal(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse("finance_account_modal.html", _account_context(request, conn, None, "/settings/finance-accounts"))


@settings_router.get("/{uid}/edit")
def edit_account_modal(uid: str, request: Request, conn=Depends(get_db)):
    account = finance.get_account(conn, uid)
    if account is None:
        return RedirectResponse(url="/settings/finance-accounts", status_code=303)
    return templates.TemplateResponse("finance_account_modal.html", _account_context(request, conn, account, f"/settings/finance-accounts/{uid}/update"))


def _save_account(conn, form: dict, x_requested_with, uid: str | None):
    clean, error = finance.validate_account(conn, form, uid)
    if error:
        return _error_response(error, x_requested_with, "/settings/finance-accounts")
    new_uid = finance.save_account(conn, clean, uid)
    return respond(x_requested_with, "/settings/finance-accounts", status_code=200 if uid else 201, uid=new_uid)


@settings_router.post("")
def create_account(name: str = Form(""), type: str = Form(""), currency: str = Form(""), opening_balance: str = Form(""),
                   opening_date: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    form = dict(name=name, type=type, currency=currency, opening_balance=opening_balance, opening_date=opening_date)
    return _save_account(conn, form, x_requested_with, None)


@settings_router.post("/{uid}/update")
def update_account(uid: str, name: str = Form(""), type: str = Form(""), currency: str = Form(""),
                   opening_balance: str = Form(""), opening_date: str = Form(""),
                   x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if finance.get_account(conn, uid) is None:
        return RedirectResponse(url="/settings/finance-accounts", status_code=303)
    form = dict(name=name, type=type, currency=currency, opening_balance=opening_balance, opening_date=opening_date)
    return _save_account(conn, form, x_requested_with, uid)


@settings_router.post("/{uid}/delete")
def delete_account(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    finance.delete_account(conn, uid)
    return respond(x_requested_with, "/settings/finance-accounts")


# Transaction tags (listed in Settings > Taxonomy & Data)

def _tag_context_modal(request: Request, conn, tag: dict | None) -> dict:
    groups = [{"uid": "", "name": "None"}] + [{"uid": g["name"], "name": g["name"]} for g in db.list_groups(conn)]
    action = "/finance/tags/update" if tag else "/finance/tags"
    return {"request": request, "tag": tag, "group_items": groups, "form_action": action}


@router.get("/tags/new")
def new_tag_modal(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse("finance_tag_modal.html", _tag_context_modal(request, conn, None))


@router.get("/tags/edit")
def edit_tag_modal(request: Request, group: str = "", name: str = "", conn=Depends(get_db)):
    tag = finance.get_tag(conn, group, name)
    if tag is None:
        return RedirectResponse(url="/settings/taxonomy?view=tags", status_code=303)
    return templates.TemplateResponse("finance_tag_modal.html", _tag_context_modal(request, conn, tag))


def _save_tag(conn, name: str, group: str, x_requested_with, old: tuple[str, str] | None):
    clean, error = finance.validate_tag(conn, name, group, old)
    if error:
        return _error_response(error, x_requested_with, "/settings/taxonomy")
    finance.save_tag(conn, clean, old)
    return respond(x_requested_with, "/settings/taxonomy?view=tags")


@router.post("/tags")
def create_tag(name: str = Form(""), group: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    return _save_tag(conn, name, group, x_requested_with, None)


@router.post("/tags/update")
def update_tag(name: str = Form(""), group: str = Form(""), old_name: str = Form(""), old_group: str = Form(""),
               x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if finance.get_tag(conn, old_group, old_name) is None:
        return RedirectResponse(url="/settings/taxonomy?view=tags", status_code=303)
    return _save_tag(conn, name, group, x_requested_with, (old_group, old_name))


@router.post("/tags/delete")
def delete_tag(group: str = "", name: str = "", x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    finance.delete_tag(conn, group, name)
    return respond(x_requested_with, "/settings/taxonomy?view=tags")
