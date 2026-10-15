"""Personal finance pages: the monthly Transactions table, and Accounts in Settings (features/finance.md)."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import clock, db, finance, finance_stats
from ..deps import get_db, respond, templates, wants_json
from .labels import COLORS

router = APIRouter(prefix="/finance", tags=["finance"])
settings_router = APIRouter(prefix="/settings/finance-accounts", tags=["finance-settings"])

def _month(value: str, today: date) -> str:
    """The month shown, as YYYY-MM; anything unusable falls back to the current month."""
    try:
        date.fromisoformat(value + "-01")
        return value
    except ValueError:
        return today.isoformat()[:7]


_NONE = {"uid": "", "name": "None"}


def _error_response(error: dict, x_requested_with, back: str):
    if wants_json(x_requested_with):
        return JSONResponse({"detail": [{"loc": ["body", error["field"]], "msg": error["message"]}]}, status_code=422)
    return RedirectResponse(url=f"{back}?{urlencode({'error': error['message']})}", status_code=303)


@router.get("")
def finance_home():
    return RedirectResponse(url="/finance/transactions", status_code=303)


@router.get("/transactions")
def transactions(request: Request, month: str = "", account: str = "", conn=Depends(get_db)):
    """One month at a time, laid out like a ledger: income, its total, expenses, its total, profit, savings."""
    today = clock.today()
    month = _month(month, today)
    accounts = finance.list_accounts(conn)
    rows = finance.list_transactions(conn, {"account_uid": account, "date_from": month + "-01", "date_to": finance_stats.month_end(month),
                                            "sort": "date", "dir": "asc"})
    pending = finance.list_scheduled(conn, {"account_uid": account})
    sections = finance_stats.month_sections(rows, {a["uid"]: a for a in accounts}, accounts[0]["currency"] if accounts else "")
    return templates.TemplateResponse("finance_transactions.html", {
        "request": request, "active_tab": "finance", "sections": sections, "pending": pending, "has_accounts": bool(accounts),
        "month": month, "month_label": finance_stats.month_title(month),
        "prev_month": finance_stats.month_add(month, -1), "next_month": finance_stats.month_add(month, 1), "account": account,
        "account_items": [{"value": "", "name": "All accounts"}] + [{"value": a["uid"], "name": a["short"]} for a in accounts],
        "money": finance_stats.format_money, "short_date": finance_stats.short_date, "tag_styles": finance.tag_styles(conn),
    })


def _task_items(conn) -> list[dict]:
    return [_NONE] + [{"uid": t["uid"], "name": t["title"]} for t in db.list_tasks(conn) if t.get("status") not in ("done", "archived")]


def transaction_form_context(request: Request, conn, txn: dict | None, action: str, scheduled: bool = False,
                             copy: bool = False) -> dict:
    accounts = finance.list_accounts(conn)
    return {
        "request": request, "t": txn, "copy": copy, "form_action": action, "kind": (txn or {}).get("type", ""),
        "status": "scheduled" if scheduled else "posted", "status_fixed": scheduled,
        "task_items": _task_items(conn), "recurrence": (txn or {}).get("recurrence") or "",
        "account_items": [_NONE] + [{"uid": a["uid"], "name": f"{a['short']} ({a['currency']})"} for a in accounts],
        "type_items": [_NONE] + [{"uid": k, "name": n} for k, n in finance_stats.TRANSACTION_TYPES],
        "amount_text": finance_stats.amount_input((txn or {}).get("amount", 0)) if txn else "",
        **_tag_context(conn, (txn or {}).get("tags", [])),
    }


def _tag_context(conn, selected: list[str]) -> dict:
    known = finance.tag_names(conn)
    names = list(dict.fromkeys(known + list(selected)))
    return {"tag_items": [{"uid": n, "name": n} for n in names], "tag_selected": selected}


@router.get("/transactions/new")
def new_transaction_modal(request: Request, copy: str = "", conn=Depends(get_db)):
    """`copy` (Duplicate): a transaction whose values fill the create form; nothing is saved until Save."""
    source = finance.get_transaction(conn, copy) if copy else None
    return templates.TemplateResponse("finance_transaction_modal.html",
                                      transaction_form_context(request, conn, source, "/finance/transactions", copy=bool(source)))


@router.get("/transactions/{uid}/edit")
def edit_transaction_modal(uid: str, request: Request, conn=Depends(get_db)):
    txn = finance.get_transaction(conn, uid)
    if txn is None:
        return RedirectResponse(url="/finance/transactions", status_code=303)
    return templates.TemplateResponse("finance_transaction_modal.html",
                                      transaction_form_context(request, conn, txn, f"/finance/transactions/{uid}/update"))


async def _form_values(request: Request) -> dict:
    form = await request.form()
    data = {k: form.get(k, "") for k in ("date", "type", "account_uid", "to_account_uid", "amount", "description",
                                         "status", "recurrence", "task_uid")}
    data["tags"] = form.getlist("tags")
    data["contacts"] = form.getlist("contacts") if form.get("contacts_present") == "1" else None
    return data


def _save_contacts(conn, object_type: str, uid: str, data: dict) -> None:
    if data.get("contacts") is not None:
        db.set_object_contacts(conn, object_type, uid, db.resolve_contact_entries(conn, data["contacts"]))


def _save_scheduled(conn, data: dict, x_requested_with, uid: str | None):
    clean, error = finance.validate_scheduled(conn, data)
    if error:
        return _error_response(error, x_requested_with, "/finance/transactions")
    new_uid = finance.save_scheduled(conn, clean, uid)
    _save_contacts(conn, "scheduled", new_uid, data)
    return respond(x_requested_with, "/finance/transactions", status_code=200 if uid else 201, uid=new_uid)


def _save_transaction(conn, data: dict, x_requested_with, uid: str | None):
    if data.get("status") == "scheduled":
        return _save_scheduled(conn, data, x_requested_with, uid)
    clean, error = finance.validate_transaction(conn, data)
    if error:
        return _error_response(error, x_requested_with, "/finance/transactions")
    new_uid = finance.save_transaction(conn, clean, uid)
    _save_contacts(conn, "transaction", new_uid, data)
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
def create_account(name: str = Form(""), abbreviation: str = Form(""), type: str = Form(""), currency: str = Form(""), opening_balance: str = Form(""),
                   opening_date: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    form = dict(name=name, abbreviation=abbreviation, type=type, currency=currency, opening_balance=opening_balance, opening_date=opening_date)
    return _save_account(conn, form, x_requested_with, None)


@settings_router.post("/{uid}/update")
def update_account(uid: str, name: str = Form(""), abbreviation: str = Form(""), type: str = Form(""), currency: str = Form(""),
                   opening_balance: str = Form(""), opening_date: str = Form(""),
                   x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if finance.get_account(conn, uid) is None:
        return RedirectResponse(url="/settings/finance-accounts", status_code=303)
    form = dict(name=name, abbreviation=abbreviation, type=type, currency=currency, opening_balance=opening_balance, opening_date=opening_date)
    return _save_account(conn, form, x_requested_with, uid)


@settings_router.post("/{uid}/delete")
def delete_account(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    finance.delete_account(conn, uid)
    return respond(x_requested_with, "/settings/finance-accounts")


# Transaction tags (listed in Settings > Taxonomy & Data)

def _tag_context_modal(request: Request, conn, tag: dict | None) -> dict:
    action = "/finance/tags/update" if tag else "/finance/tags"
    from .labels import icon_groups_for

    return {"request": request, "tag": tag, "form_action": action, "colors": COLORS,
            "icon_groups": icon_groups_for((tag or {}).get("icon") or None)}


@router.get("/tags/new")
def new_tag_modal(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse("finance_tag_modal.html", _tag_context_modal(request, conn, None))


@router.get("/tags/edit")
def edit_tag_modal(request: Request, name: str = "", conn=Depends(get_db)):
    tag = finance.get_tag(conn, name)
    if tag is None:
        return RedirectResponse(url="/settings/taxonomy?view=tags", status_code=303)
    return templates.TemplateResponse("finance_tag_modal.html", _tag_context_modal(request, conn, tag))


def _save_tag(conn, name: str, x_requested_with, old: str | None, color: str = "gray", icon: str = ""):
    clean, error = finance.validate_tag(conn, name, old, color if color in COLORS else "gray", icon)
    if error:
        return _error_response(error, x_requested_with, "/settings/taxonomy")
    finance.save_tag(conn, clean, old)
    return respond(x_requested_with, "/settings/taxonomy?view=tags")


@router.post("/tags")
def create_tag(name: str = Form(""), color: str = Form("gray"), icon: str = Form(""),
               x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    return _save_tag(conn, name, x_requested_with, None, color, icon)


@router.post("/tags/update")
def update_tag(name: str = Form(""), old_name: str = Form(""),
               color: str = Form("gray"), icon: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if finance.get_tag(conn, old_name) is None:
        return RedirectResponse(url="/settings/taxonomy?view=tags", status_code=303)
    return _save_tag(conn, name, x_requested_with, old_name, color, icon)


@router.post("/tags/delete")
def delete_tag(name: str = "", x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    finance.delete_tag(conn, name)
    return respond(x_requested_with, "/settings/taxonomy?view=tags")
