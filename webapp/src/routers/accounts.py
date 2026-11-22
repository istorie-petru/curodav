"""The Accounts module: the vault page, its windows and its Settings page (features/accounts-vault.md).

Every route needs the module switched on. Every route except the page, create and unlock needs the vault open in this
browser. Secret values leave the server only one at a time, through `secret` and `otp`, and never inside a page, except
in the edit form of an entry. Nothing here is reachable through the API or MCP.
"""

from __future__ import annotations

import ipaddress
import json

from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import auth, clock, db, modules
from .. import vault_exchange as vx
from .. import vault_kdbx as kdbx
from .. import vault_service as vs
from .. import vault_session as session
from ..deps import get_db, templates, validation_response, wants_json
from ..log import get_logger

logger = get_logger(__name__)

MODULE = modules.register(modules.Module("accounts", "Accounts", "/settings/accounts", icon="lock",
                                         description="Logins, identities, cards and other secrets in an encrypted KeePass vault"))
TYPES_KEY = "accounts_types"
MIN_PASSWORD = 10
MAX_KEY_FILE = 64 * 1024

router = APIRouter(prefix="/accounts", tags=["accounts"])
settings_router = APIRouter(prefix="/settings/accounts", tags=["accounts"])


def _enabled() -> None:
    if not modules.is_enabled(MODULE.key):
        raise HTTPException(404, "Not found")


def types(conn) -> list[dict]:
    try:
        stored = json.loads(db.get_app_meta(conn, TYPES_KEY) or "null")
    except ValueError:
        stored = None
    return stored if isinstance(stored, list) and stored else [dict(t) for t in vs.DEFAULT_TYPES]


def _state(request: Request, conn) -> session.Unlocked | None:
    return session.current(conn, request.cookies.get(session.COOKIE))


def _open(request: Request, conn) -> session.Unlocked:
    _enabled()
    state = _state(request, conn)
    if state is None:
        raise HTTPException(423, "The vault is locked")
    return state


def _safe_transport(request: Request) -> bool:
    """The master password only travels over HTTPS, or to the machine itself."""
    if auth.is_secure_request(request):
        return True
    host = (request.client.host if request.client else "") or ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _error(field: str, message: str, xrw: str | None, back: str = "/accounts"):
    return validation_response({"field": field, "message": message}, xrw, back)


def _set_cookie(response: Response, request: Request, token: str) -> Response:
    response.set_cookie(session.COOKIE, token, httponly=True, samesite="strict", secure=auth.is_secure_request(request), path="/")
    return response


async def _key_file(upload: UploadFile | None) -> bytes | None:
    if upload is None or not upload.filename:
        return None
    data = await upload.read(MAX_KEY_FILE + 1)
    if len(data) > MAX_KEY_FILE:
        raise HTTPException(400, "That key file is too large")
    return data or None


def _save(conn, state: session.Unlocked) -> None:
    try:
        session.save(conn, state)
    except kdbx.VaultError as exc:
        raise HTTPException(409, str(exc)) from None


# ---------------------------------------------------------------- the page

NO_SPACE = "_"
HEALTH = (("weak", "Weak"), ("reused", "Used more than once"), ("old", "Not changed for a year"), ("expired", "Expired"))


def _spaces(conn) -> list[dict]:
    return [{"name": g["name"], "icon": g.get("icon") or "layers", "color": g.get("color") or "gray"} for g in db.list_groups(conn)]


def _sync(conn, state: session.Unlocked) -> None:
    """Every space has its group in the vault; a new space adds one the next time the vault is shown."""
    if vs.sync_spaces(state.db, [s["name"] for s in _spaces(conn)]):
        _save(conn, state)


@router.get("")
def accounts_page(request: Request, space: str | None = None, q: str = "", tag: str = "", kind: str = "", view: str = "", health: str = "",
                  conn=Depends(get_db)):
    _enabled()
    state = _state(request, conn)
    ctx = {"request": request, "active_tab": "accounts", "exists": session.exists(conn), "unlocked": state is not None,
           "safe": _safe_transport(request), "types": types(conn)}
    if state is not None:
        _sync(conn, state)
        database = state.db
        ctx["notice"], state.notice = state.notice, ""
        spaces = _spaces(conn)
        known = {s["name"].lower() for s in spaces}
        everything = vs.list_entries(database, known=known)
        report = vs.health(database)
        view = "trash" if view == "trash" else ""
        health = health if health in dict(HEALTH) else ""
        chosen = None if space is None else ("" if space == NO_SPACE else space)
        uuids = {r["uuid"] for r in report[health]} if health else None
        entries = vs.list_entries(database, space=chosen, query=q, tag=tag, kind=kind, trash=view == "trash", uuids=uuids, known=known)
        counts = {}
        for e in everything:
            counts[e["space"].lower()] = counts.get(e["space"].lower(), 0) + 1
        ctx.update({
            "spaces": [{**s, "count": counts.get(s["name"].lower(), 0)} for s in spaces], "no_space_count": counts.get("", 0),
            "space": space, "q": q, "tag": tag, "kind": kind, "view": view, "health": health, "health_items": HEALTH, "report": report,
            "entries": entries, "trash_count": len(vs.list_entries(database, trash=True)), "total": len(everything),
            "type_map": {t["key"]: t for t in types(conn)}, "no_space": NO_SPACE,
            "heading": (dict(HEALTH)[health] if health else "Recycle bin" if view == "trash" else
                        "No space" if space == NO_SPACE else (space or "All entries")),
        })
    return templates.TemplateResponse("accounts_page.html", ctx)


# ---------------------------------------------------------------- create, unlock, lock

@router.get("/create")
def create_modal(request: Request, conn=Depends(get_db)):
    _enabled()
    if session.exists(conn):
        return RedirectResponse("/accounts", status_code=303)
    return templates.TemplateResponse("accounts_create_modal.html", {"request": request, "min_length": MIN_PASSWORD})


@router.get("/key-file")
def new_key_file(conn=Depends(get_db)):
    """A fresh random key file to keep beside the master password; it is never stored here."""
    _enabled()
    return Response(kdbx.make_key_file(), media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="Curodav accounts.keyx"', "Cache-Control": "no-store"})


@router.post("/create")
async def create_vault(request: Request, password: str = Form(""), confirm: str = Form(""), key_file: UploadFile | None = File(None),
                       x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    _enabled()
    if not _safe_transport(request):
        return _error("password", "Open Curodav over HTTPS to set a master password", x_requested_with)
    if len(password) < MIN_PASSWORD:
        return _error("password", f"The master password needs at least {MIN_PASSWORD} characters", x_requested_with)
    if password != confirm:
        return _error("confirm", "The two passwords are not the same", x_requested_with)
    try:
        token = session.create(conn, password, await _key_file(key_file))
    except kdbx.VaultError as exc:
        return _error("password", str(exc), x_requested_with)
    return _set_cookie(RedirectResponse(_next(next), status_code=303), request, token)


def _next(value: str) -> str:
    """Where to go after unlocking or locking: the vault, or its settings page when that is where the person was."""
    return value if value == "/settings/accounts" else "/accounts"


@router.get("/unlock")
def unlock_modal(request: Request, next: str = "", conn=Depends(get_db)):
    _enabled()
    return templates.TemplateResponse("accounts_unlock_modal.html", {"request": request, "wait": session.wait_seconds(), "next": _next(next)})


@router.post("/unlock")
async def unlock_vault(request: Request, password: str = Form(""), key_file: UploadFile | None = File(None), next: str = Form(""),
                       x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    _enabled()
    if not _safe_transport(request):
        return _error("password", "Open Curodav over HTTPS to unlock the vault", x_requested_with)
    try:
        token = session.unlock(conn, password, await _key_file(key_file))
    except kdbx.WrongKey:
        return _error("password", "The master password or key file is wrong", x_requested_with)
    except PermissionError as exc:
        return _error("password", str(exc), x_requested_with)
    except kdbx.VaultError as exc:
        return _error("password", str(exc), x_requested_with)
    return _set_cookie(RedirectResponse("/accounts", status_code=303), request, token)


@router.post("/lock")
def lock_vault(request: Request, next: str = Form("")):
    session.lock(request.cookies.get(session.COOKIE))
    response = RedirectResponse(_next(next), status_code=303)
    response.delete_cookie(session.COOKIE, path="/")
    return response


@router.get("/status")
def status(request: Request, conn=Depends(get_db)):
    """Whether this browser's vault is still open; the page asks now and then so it can clear itself once it locks."""
    _enabled()
    return JSONResponse({"unlocked": _state(request, conn) is not None}, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- entries

def _field_rows(type_: dict, values: dict | None) -> list[dict]:
    """The entry's fields in its type's order, each one label and one value; values the type does not name follow at the end."""
    values = values or {}
    std = {"UserName": values.get("username", ""), "Password": values.get("password", ""), "URL": values.get("url", ""),
           "Notes": values.get("notes", ""), vs.OTP_FIELD: values.get("otp", "")}
    hidden = set(values.get("hidden") or ([] if values else ["Password"])) | {vs.OTP_FIELD}
    custom = {f["key"]: f for f in values.get("custom") or []}
    rows, used = [], set()
    for f in type_["fields"]:
        key = vs.STANDARD_LABELS.get(f["name"])
        if key:
            rows.append({"name": f["name"], "value": std[key], "hidden": key in hidden or (not values and f["kind"] in ("secret", "code")), "kind": f["kind"]})
            used.add(key)
        else:
            have = custom.get(f["name"])
            rows.append({"name": f["name"], "value": have["value"] if have else "", "hidden": have["protected"] if have else f["kind"] in ("secret", "code"),
                         "kind": f["kind"]})
            used.add(f["name"])
    labels = {v: k for k, v in vs.STANDARD_LABELS.items()}
    for key, value in std.items():
        if value and key not in used:
            rows.append({"name": labels[key], "value": value, "hidden": key in hidden, "kind": "long text" if key == "Notes" else "text"})
    for key, f in custom.items():
        if key not in used:
            rows.append({"name": key, "value": f["value"], "hidden": f["protected"], "kind": "text"})
    return rows


def _entry_context(request, conn, state, uuid: str | None, group: str = "") -> dict:
    values = vs.edit_values(state.db, uuid) if uuid else None
    if uuid and values is None:
        raise HTTPException(404, "No such entry")
    type_list = types(conn)
    chosen = (values or {}).get("type") or request.query_params.get("type") or "login"
    type_ = next((t for t in type_list if t["key"] == chosen), type_list[0])
    spaces = _spaces(conn)
    current = (values or {}).get("space") or ("" if group == NO_SPACE else group)
    if current.lower() not in {s["name"].lower() for s in spaces}:
        current = ""
    return {"request": request, "e": values, "rows": _field_rows(type_, values), "type": type_, "types": type_list,
            "space_items": [{"uid": "", "name": "No space"}] + [{"uid": s["name"], "name": s["name"]} for s in spaces], "space": current,
            "kinds": {t["key"]: [[f["name"], f["kind"]] for f in t["fields"]] for t in type_list}}


@router.get("/entry/new")
def new_entry(request: Request, space: str = "", conn=Depends(get_db)):
    state = _open(request, conn)
    _sync(conn, state)
    return templates.TemplateResponse("accounts_entry_form.html", _entry_context(request, conn, state, None, space))


@router.get("/entry/{uuid}")
def view_entry(uuid: str, request: Request, conn=Depends(get_db)):
    state = _open(request, conn)
    entry = vs.entry_detail(state.db, uuid, types(conn))
    if entry is None:
        raise HTTPException(404, "No such entry")
    contact = db.get_contact(conn, entry["contact"]) if entry["contact"] else None
    in_bin = uuid in {e["uuid"] for e in vs.list_entries(state.db, trash=True)}
    type_ = next((t for t in types(conn) if t["key"] == entry["type"]), types(conn)[0])
    labels = {f["name"] for f in type_["fields"]}
    shown = {key for label, key in vs.STANDARD_LABELS.items() if label in labels}
    return templates.TemplateResponse("accounts_entry_view.html", {"request": request, "e": entry, "contact": contact, "in_bin": in_bin,
                                                                   "shown": shown, "values": vs.edit_values(state.db, uuid)})


@router.post("/entry/{uuid}/update-field")
async def update_field(uuid: str, request: Request, conn=Depends(get_db)):
    """In-place edit from the view window (static/view_inline.js): one field, saved at once."""
    state = _open(request, conn)
    payload = await request.json()
    value = payload.get("value") if isinstance(payload.get("value"), str) else ""
    field = str(payload.get("field") or "")
    try:
        changed = vs.set_field(state.db, uuid, field, value if field == "Notes" else value.strip())
    except vs.EntryError as exc:
        return JSONResponse({"error": exc.message}, status_code=400)
    _save(conn, state)
    body: dict = {"ok": True}
    if changed and vs.is_secret(state.db, uuid, field):
        body["undo"] = {"message": f"{field} changed", "url": f"/accounts/entry/{quote(uuid)}/undo-field", "field": field}
    return JSONResponse(body)


@router.post("/entry/{uuid}/undo-field")
async def undo_field(uuid: str, request: Request, conn=Depends(get_db)):
    """Puts a field back to what it was before its last change (the Undo on the toast after a password is changed)."""
    state = _open(request, conn)
    payload = await request.json()
    try:
        vs.undo_field(state.db, uuid, str(payload.get("field") or ""))
    except vs.EntryError as exc:
        return JSONResponse({"error": exc.message}, status_code=400)
    _save(conn, state)
    logger.info("accounts: a field change was undone")
    return JSONResponse({"ok": True})


@router.get("/entry/{uuid}/edit")
def edit_entry(uuid: str, request: Request, conn=Depends(get_db)):
    state = _open(request, conn)
    return templates.TemplateResponse("accounts_entry_form.html", _entry_context(request, conn, state, uuid))


async def _entry_data(request: Request) -> dict:
    """The form's rows back into the entry: a row named like a standard field is that field, any other is a custom field.
    Tags, expiry and the linked person are not in the form, so they are left as they are."""
    form = await request.form()
    data = {"title": form.get("title"), "type": form.get("type"), "space": form.get("space"), "hidden": [], "custom": [],
            "username": "", "password": "", "url": "", "notes": "", "otp": ""}
    names = {"UserName": "username", "Password": "password", "URL": "url", "Notes": "notes", vs.OTP_FIELD: "otp"}
    for i in form.getlist("field_idx"):
        name = (form.get(f"field_key_{i}") or "").strip()
        value = form.get(f"field_value_{i}") or ""
        hidden = form.get(f"field_secret_{i}") == "1"
        key = vs.STANDARD_LABELS.get(name)
        if key:
            data[names[key]] = value
            if hidden:
                data["hidden"].append(key)
        elif name:
            data["custom"].append({"key": name, "value": value, "protected": hidden})
    return data


@router.post("/entry")
@router.post("/entry/{uuid}")
async def save_entry(request: Request, uuid: str = "", x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    state = _open(request, conn)
    before = (vs.edit_values(state.db, uuid) or {}).get("password", "") if uuid else ""
    try:
        saved = vs.save_entry(state.db, uuid or None, await _entry_data(request), types(conn))
    except vs.EntryError as exc:
        return _error(exc.field, exc.message, x_requested_with)
    _save(conn, state)
    logger.info("accounts: entry saved")
    where = vs.summary(state.db, vs.find_entry(state.db, saved))["space"]
    target = f"/accounts?space={quote(where or NO_SPACE)}"
    if uuid and before and (vs.edit_values(state.db, saved) or {}).get("password", "") != before:
        target += f"&undo_password={quote(saved)}"  # the page offers to put the old password back
    return RedirectResponse(target, status_code=303)


@router.post("/entry/{uuid}/delete")
def delete_entry(uuid: str, request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    state = _open(request, conn)
    try:
        outcome = vs.delete_entry(state.db, uuid)
    except vs.EntryError as exc:
        return _error(exc.field, exc.message, x_requested_with)
    _save(conn, state)
    note = "Moved to the recycle bin" if outcome == "binned" else "Deleted for good"
    return RedirectResponse("/accounts?" + urlencode({"note": note}), status_code=303)


@router.post("/entry/{uuid}/restore")
def restore_entry(uuid: str, request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    state = _open(request, conn)
    try:
        vs.restore_entry(state.db, uuid)
    except vs.EntryError as exc:
        return _error(exc.field, exc.message, x_requested_with)
    _save(conn, state)
    return RedirectResponse("/accounts?view=trash", status_code=303)


@router.post("/trash/empty")
def empty_trash(request: Request, conn=Depends(get_db)):
    state = _open(request, conn)
    count = vs.empty_bin(state.db)
    _save(conn, state)
    return RedirectResponse("/accounts?" + urlencode({"note": f"{count} entr{'y' if count == 1 else 'ies'} deleted for good"}), status_code=303)


@router.post("/entry/{uuid}/secret")
def entry_secret(uuid: str, request: Request, field: str = Form(...), action: str = Form("copy"), conn=Depends(get_db)):
    """One value of one entry, for Copy or Reveal. Logged by entry title and action, never by value."""
    state = _open(request, conn)
    value = vs.secret(state.db, uuid, field)
    if value is None:
        raise HTTPException(404, "No such field")
    title = vs.summary(state.db, vs.find_entry(state.db, uuid))["title"]
    logger.info("accounts: %s %s of %s", "revealed" if action == "reveal" else "copied", field, title)
    return JSONResponse({"value": value}, headers={"Cache-Control": "no-store"})


@router.get("/entry/{uuid}/otp")
def entry_otp(uuid: str, request: Request, conn=Depends(get_db)):
    state = _open(request, conn)
    code = vs.totp(vs.secret(state.db, uuid, vs.OTP_FIELD) or "")
    if code is None:
        raise HTTPException(404, "No one-time code")
    return JSONResponse({"code": code["code"], "remaining": code["remaining"], "period": code["period"]}, headers={"Cache-Control": "no-store"})


@router.get("/entry/{uuid}/history")
def entry_history(uuid: str, request: Request, conn=Depends(get_db)):
    state = _open(request, conn)
    entry = vs.entry_detail(state.db, uuid, types(conn))
    if entry is None:
        raise HTTPException(404, "No such entry")
    return templates.TemplateResponse("accounts_history_modal.html", {"request": request, "e": entry, "versions": vs.history(state.db, uuid)})


@router.post("/entry/{uuid}/history/{index}/restore")
def restore_version(uuid: str, index: int, request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    state = _open(request, conn)
    try:
        vs.restore_version(state.db, uuid, index)
    except vs.EntryError as exc:
        return _error(exc.field, exc.message, x_requested_with)
    _save(conn, state)
    return RedirectResponse("/accounts", status_code=303)


RULE_KEY = "accounts_password_rule"
CHARSETS = (("lower", "Small letters"), ("upper", "Capitals"), ("digits", "Digits"), ("symbols", "Symbols"))
DEFAULT_RULE = {"mode": "random", "length": 20, "sets": ["lower", "upper", "digits", "symbols"], "exclude": "",
                "words": 4, "separator": "-", "capitalize": True, "number": True}


def password_rule(conn) -> dict:
    """How a new password is made, set once in Settings, Accounts and used by every Generate button."""
    try:
        stored = json.loads(db.get_app_meta(conn, RULE_KEY) or "{}")
    except ValueError:
        stored = {}
    return {**DEFAULT_RULE, **(stored if isinstance(stored, dict) else {})}


def _make(rule: dict) -> dict:
    if rule.get("mode") == "memorable":
        made = vs.memorable(rule["words"], rule["separator"], bool(rule["capitalize"]), bool(rule["number"]))
    else:
        sets = set(rule.get("sets") or ["lower"])
        made = vs.generate(rule["length"], "lower" in sets, "upper" in sets, "digits" in sets, "symbols" in sets, False, 1, 1, vs.SYMBOLS,
                           rule.get("exclude") or "")
    return {**made, "rating": vs.rating(made["bits"])}


def _rule_from(form) -> dict:
    def number(name, low, high, default):
        try:
            return max(low, min(high, int(form.get(name) or default)))
        except ValueError:
            return default

    return {"mode": "memorable" if form.get("mode") == "memorable" else "random", "length": number("length", 8, 128, 20),
            "sets": [k for k, _ in CHARSETS if k in form.getlist("sets")] or ["lower"], "exclude": (form.get("exclude") or "")[:64],
            "words": number("words", 3, 10, 4), "separator": (form.get("separator") or "")[:3], "capitalize": form.get("capitalize") == "1",
            "number": form.get("number") == "1"}


# ---------------------------------------------------------------- several entries at once

MAX_BULK = 300
KEEP = "__keep"


def _uuids(text: str) -> list[str]:
    return [u for u in (t.strip().lower() for t in (text or "").split(",")) if len(u) == 32 and all(c in "0123456789abcdef" for c in u)][:MAX_BULK]


@router.get("/bulk")
def bulk_modal(request: Request, uuids: str = "", conn=Depends(get_db)):
    state = _open(request, conn)
    chosen = _uuids(uuids)
    if not chosen:
        raise HTTPException(400, "Choose entries first")
    type_list = types(conn)
    return templates.TemplateResponse("accounts_bulk_modal.html", {
        "request": request, "uuids": ",".join(chosen), "count": len(chosen),
        "space_items": [{"uid": KEEP, "name": "Keep as it is"}, {"uid": "", "name": "No space"}] + [{"uid": s["name"], "name": s["name"]} for s in _spaces(conn)],
        "type_items": [{"uid": KEEP, "name": "Keep as it is"}] + [{"uid": t["key"], "name": t["name"]} for t in type_list], "keep": KEEP})


@router.post("/bulk/edit")
def bulk_edit(request: Request, uuids: str = Form(""), space: str = Form(KEEP), type: str = Form(KEEP), add_tags: str = Form(""), remove_tags: str = Form(""),
              x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    state = _open(request, conn)
    chosen = _uuids(uuids)
    if not chosen:
        return _error("uuids", "Choose entries first", x_requested_with)
    if space not in (KEEP, "") and space.lower() not in {s["name"].lower() for s in _spaces(conn)}:
        return _error("space", "That space does not exist", x_requested_with)
    _sync(conn, state)
    split = lambda text: [t for t in text.replace(";", ",").split(",") if t.strip()]  # noqa: E731
    try:
        changed = vs.bulk_edit(state.db, chosen, space=None if space == KEEP else space, type_key=None if type == KEEP else type,
                               add_tags=split(add_tags), remove_tags=split(remove_tags), types=types(conn))
    except vs.EntryError as exc:
        return _error(exc.field, exc.message, x_requested_with)
    _save(conn, state)
    logger.info("accounts: %s entries changed together", changed)
    return RedirectResponse("/accounts?" + urlencode({"note": f"{changed} entr{'y' if changed == 1 else 'ies'} changed"}), status_code=303)


@router.post("/bulk/delete")
def bulk_delete(request: Request, uuids: str = Form(""), conn=Depends(get_db)):
    state = _open(request, conn)
    binned, deleted = vs.delete_entries(state.db, _uuids(uuids))
    _save(conn, state)
    note = f"{deleted} deleted for good" if deleted and not binned else f"{binned} moved to the recycle bin" + (f", {deleted} deleted for good" if deleted else "")
    return RedirectResponse("/accounts?" + urlencode({"note": note}), status_code=303)


@router.post("/bulk/restore")
def bulk_restore(request: Request, uuids: str = Form(""), conn=Depends(get_db)):
    state = _open(request, conn)
    count = vs.restore_entries(state.db, _uuids(uuids))
    _save(conn, state)
    return RedirectResponse("/accounts?" + urlencode({"view": "trash", "note": f"{count} restored"}), status_code=303)


@router.get("/generate")
def generate(request: Request, conn=Depends(get_db)):
    """A new password by the saved rule, or by the rule being edited in Settings when its fields come along (a preview)."""
    _enabled()
    rule = _rule_from(request.query_params) if "mode" in request.query_params else password_rule(conn)
    return JSONResponse(_make(rule), headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- import and export

@router.get("/import")
def import_modal(request: Request, conn=Depends(get_db)):
    _open(request, conn)
    return templates.TemplateResponse("accounts_import_modal.html", {"request": request})


@router.post("/import")
async def import_preview(request: Request, file: UploadFile | None = File(None), password: str = Form(""), key_file: UploadFile | None = File(None),
                         x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    state = _open(request, conn)
    if file is None or not file.filename:
        return _error("file", "Choose a file to import", x_requested_with)
    data = await file.read(vx.MAX_IMPORT_BYTES + 1)
    try:
        rows = vx.read_import(file.filename, data, password, await _key_file(key_file))
    except vx.ImportError_ as exc:
        return _error("file", str(exc), x_requested_with)
    if not rows:
        return _error("file", "There is nothing to import in that file", x_requested_with)
    state.pending_import = rows
    return RedirectResponse("/accounts/import/preview", status_code=303)


@router.get("/import/preview")
def import_preview_modal(request: Request, conn=Depends(get_db)):
    state = _open(request, conn)
    if not state.pending_import:
        return RedirectResponse("/accounts/import", status_code=303)
    return templates.TemplateResponse("accounts_import_preview.html", {"request": request, "p": vx.preview(state.db, state.pending_import),
                                                                     "space_items": [{"uid": "", "name": "No space"}] + [{"uid": s["name"], "name": s["name"]} for s in _spaces(conn)]})


@router.post("/import/apply")
def import_apply(request: Request, include_duplicates: str = Form(""), space: str = Form(""), conn=Depends(get_db)):
    state = _open(request, conn)
    _sync(conn, state)
    rows, state.pending_import = state.pending_import or [], None
    added = vx.apply(state.db, rows, types(conn), skip_duplicates=include_duplicates != "1", space=space)
    _save(conn, state)
    logger.info("accounts: imported %s entries", added)
    return RedirectResponse("/accounts?" + urlencode({"note": f"{added} entr{'y' if added == 1 else 'ies'} imported"}), status_code=303)


@router.get("/export")
def export_modal(request: Request, conn=Depends(get_db)):
    _open(request, conn)
    return templates.TemplateResponse("accounts_export_modal.html", {"request": request})


@router.get("/export/vault")
def export_vault(request: Request, conn=Depends(get_db)):
    """The vault file as it is stored, still encrypted with the master key."""
    _open(request, conn)
    logger.info("accounts: vault file downloaded")
    return Response(session.vault_path(conn).read_bytes(), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="accounts-{clock.today().isoformat()}.kdbx"', "Cache-Control": "no-store"})


@router.post("/export/csv")
async def export_csv(request: Request, password: str = Form(""), key_file: UploadFile | None = File(None),
                     x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    state = _open(request, conn)
    if not session.check_key(state, password, await _key_file(key_file)):
        logger.warning("accounts: plain export refused, wrong master key")
        return _error("password", "The master password or key file is wrong", x_requested_with)
    logger.warning("accounts: plain CSV export")
    return Response(vx.export_csv(state.db), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="accounts-{clock.today().isoformat()}.csv"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- settings

def _rule_summary(rule: dict) -> str:
    """The rule for new passwords in one line, with how strong a sample is."""
    sample = _make(rule)
    if rule["mode"] == "memorable":
        text = f"{rule['words']} memorable words" + (" with a number" if rule.get("number") else "")
    else:
        text = f"{rule['length']} characters, " + ", ".join(dict(CHARSETS)[k] for k in rule["sets"]) + (f", without {rule['exclude']}" if rule.get("exclude") else "")
    return f"{text}. {sample['rating']}, {sample['bits']} bits"


@settings_router.get("")
def settings_page(request: Request, conn=Depends(get_db)):
    _enabled()
    return templates.TemplateResponse("settings_accounts.html", {
        "request": request, "active_tab": "settings_accounts", "idle": session.idle_minutes(conn), "types": types(conn),
        "rule_summary": _rule_summary(password_rule(conn)),
        "exists": session.exists(conn), "unlocked": _state(request, conn) is not None,
        "idle_items": [{"uid": str(m), "name": n} for m, n in ((1, "1 minute"), (5, "5 minutes"), (10, "10 minutes"), (30, "30 minutes"),
                                                                (60, "1 hour"), (240, "4 hours"), (0, "Never"))]})


@settings_router.post("/idle")
def save_idle(minutes: str = Form("10"), conn=Depends(get_db)):
    _enabled()
    value = minutes if minutes.isdigit() and int(minutes) <= 24 * 60 else str(session.DEFAULT_IDLE_MINUTES)
    db.set_app_meta(conn, session.IDLE_KEY, value)
    return RedirectResponse("/settings/accounts?" + urlencode({"note": "Saved"}), status_code=303)


@settings_router.get("/generator")
def rule_modal(request: Request, conn=Depends(get_db)):
    _enabled()
    rule = password_rule(conn)
    return templates.TemplateResponse("accounts_generator_modal.html", {
        "request": request, "rule": rule, "sample": _make(rule),
        "set_items": [{"uid": k, "name": n, "checked": k in rule["sets"]} for k, n in CHARSETS]})


@settings_router.post("/generator")
async def save_rule(request: Request, conn=Depends(get_db)):
    _enabled()
    db.set_app_meta(conn, RULE_KEY, json.dumps(_rule_from(await request.form())))
    return RedirectResponse("/settings/accounts?" + urlencode({"note": "Saved"}), status_code=303)


@settings_router.get("/snapshot/{name}")
def download_snapshot(name: str, request: Request, conn=Depends(get_db)):
    """An earlier copy of the vault, still encrypted with the master key it had then."""
    _open(request, conn)
    path = session.snapshot_path(conn, name)
    if path is None:
        raise HTTPException(404, "No such copy")
    logger.info("accounts: an earlier copy of the vault was downloaded")
    return Response(path.read_bytes(), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{path.name}"', "Cache-Control": "no-store"})


@settings_router.get("/master")
def master_modal(request: Request, conn=Depends(get_db)):
    _open(request, conn)
    return templates.TemplateResponse("accounts_master_modal.html", {"request": request, "min_length": MIN_PASSWORD})


@settings_router.post("/master")
async def change_master(request: Request, current: str = Form(""), current_key: UploadFile | None = File(None), password: str = Form(""),
                        confirm: str = Form(""), key_file: UploadFile | None = File(None), x_requested_with: str | None = Header(default=None),
                        conn=Depends(get_db)):
    state = _open(request, conn)
    if not _safe_transport(request):
        return _error("password", "Open Curodav over HTTPS to change the master password", x_requested_with, "/settings/accounts")
    if not session.check_key(state, current, await _key_file(current_key)):
        return _error("current", "The current master password or key file is wrong", x_requested_with, "/settings/accounts")
    if len(password) < MIN_PASSWORD:
        return _error("password", f"The master password needs at least {MIN_PASSWORD} characters", x_requested_with, "/settings/accounts")
    if password != confirm:
        return _error("confirm", "The two passwords are not the same", x_requested_with, "/settings/accounts")
    session.change_key(conn, state, password, await _key_file(key_file))
    return RedirectResponse("/settings/accounts?" + urlencode({"note": "Master password changed"}), status_code=303)


@settings_router.get("/type/{key}")
def type_modal(key: str, request: Request, conn=Depends(get_db)):
    _enabled()
    type_ = next((t for t in types(conn) if t["key"] == key), None) if key != "new" else {"key": "", "name": "", "icon": "key", "fields": []}
    if type_ is None:
        raise HTTPException(404, "No such type")
    return templates.TemplateResponse("accounts_type_form.html", {"request": request, "t": type_, "kinds": vs.FIELD_KINDS, "is_new": key == "new",
                                                                  "can_delete": key not in ("new", "login"), "standard": vs.STANDARD_KINDS})


@settings_router.post("/type")
async def save_type(request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    _enabled()
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        return _error("name", "A type needs a name", x_requested_with, "/settings/accounts")
    fields = []
    for i in form.getlist("field_idx"):
        fname = (form.get(f"field_name_{i}") or "").strip()
        kind = form.get(f"field_kind_{i}") or "text"
        if fname:
            standard = next((label for label in vs.STANDARD_KINDS if label.lower() == fname.lower()), None)
            if standard:  # a KeePass field keeps its own name and kind
                fname, kind = standard, vs.STANDARD_KINDS[standard]
            elif fname in vs.STANDARD or fname == vs.OTP_FIELD or fname.startswith("curodav."):
                return _error("fields", f"{fname} is a reserved field name", x_requested_with, "/settings/accounts")
            if any(f["name"] == fname for f in fields):
                return _error("fields", f"{fname} appears twice", x_requested_with, "/settings/accounts")
            fields.append({"name": fname, "kind": kind if kind in vs.FIELD_KINDS else "text"})
    all_types = types(conn)
    key = form.get("key") or ""
    if not key:
        key = "".join(c for c in name.lower() if c.isalnum())[:24] or "type"
        while any(t["key"] == key for t in all_types):
            key += "x"
        all_types.append({"key": key, "name": name, "icon": "key", "fields": fields})
    else:
        for t in all_types:
            if t["key"] == key:
                t.update({"name": name, "fields": fields})
    db.set_app_meta(conn, TYPES_KEY, json.dumps(all_types))
    return RedirectResponse("/settings/accounts", status_code=303)


@settings_router.post("/type/{key}/delete")
def delete_type(key: str, conn=Depends(get_db)):
    _enabled()
    if key == "login":
        raise HTTPException(400, "The Login type stays")
    db.set_app_meta(conn, TYPES_KEY, json.dumps([t for t in types(conn) if t["key"] != key]))
    return RedirectResponse("/settings/accounts", status_code=303)
