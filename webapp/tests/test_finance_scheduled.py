"""Scheduled transactions: a pending one-off and a recurring transaction are one model, shown once and posted into real
transactions, either by hand or when the linked task is completed."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src import db, finance, finance_stats, tags


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def account(conn, name="Cash", currency="RON"):
    clean, error = finance.validate_account(conn, dict(name=name, type="cash", currency=currency, opening_balance="100", opening_date="2026-01-01"))
    assert error is None
    return finance.save_account(conn, clean)


def task(conn, uid="t1", title="Renew the bus subscription", tags=("Transport",), status="todo"):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_task(conn, {"uid": uid, "title": title, "description": "", "status": status, "created_at": now, "updated_at": now, "tags": list(tags)})


def schedule(conn, account_uid, **extra):
    data = dict(type="expense", amount="80", account_uid=account_uid, description="Bus pass", date="2026-11-01")
    data.update(extra)
    clean, error = finance.validate_scheduled(conn, data)
    assert error is None, error
    return finance.save_scheduled(conn, clean)


def test_a_scheduled_row_does_not_change_any_balance(conn):
    a = account(conn)
    schedule(conn, a)
    assert finance.list_accounts(conn)[0]["balance"] == 10000 and finance.list_transactions(conn) == []


@pytest.mark.parametrize("extra,field", [
    (dict(type=""), "type"), (dict(amount="0"), "amount"), (dict(account_uid=""), "account_uid"),
    (dict(date="soon"), "date"), (dict(recurrence="NOT A RULE"), "recurrence"), (dict(type="transfer"), "to_account_uid"),
    (dict(task_uid="missing"), "task_uid"),
])
def test_invalid_scheduled_rows_name_the_field(conn, extra, field):
    a = account(conn)
    data = dict(type="expense", amount="5", account_uid=a)
    data.update(extra)
    assert finance.validate_scheduled(conn, data)[1]["field"] == field


def test_a_scheduled_row_may_have_no_date_and_no_task(conn):
    a = account(conn)
    uid = schedule(conn, a, date="")
    assert finance.get_scheduled(conn, uid)["date"] is None


def test_posting_a_one_off_creates_the_real_transaction_and_removes_the_row(conn):
    a = account(conn)
    uid = schedule(conn, a)
    new = finance.post_scheduled(conn, uid, "2026-10-20")
    row = finance.get_transaction(conn, new)
    assert row["date"] == "2026-10-20" and row["amount"] == 8000
    assert finance.get_scheduled(conn, uid) is None and finance.list_accounts(conn)[0]["balance"] == 2000


def test_posting_a_recurring_row_moves_it_to_the_next_date_and_keeps_one_row(conn):
    a = account(conn)
    uid = schedule(conn, a, date="2026-10-05", recurrence="FREQ=MONTHLY;BYMONTHDAY=5")
    finance.post_scheduled(conn, uid, "2026-10-08")
    assert finance.get_scheduled(conn, uid)["date"] == "2026-11-05"
    assert len(finance.list_scheduled(conn)) == 1 and len(finance.list_transactions(conn)) == 1


def test_a_transfer_can_be_scheduled_and_posted(conn):
    a, b = account(conn, "Cash"), account(conn, "Revolut")
    uid = schedule(conn, a, type="transfer", to_account_uid=b, amount="500")
    finance.post_scheduled(conn, uid, "2026-10-20")
    assert {x["name"]: x["balance"] for x in finance.list_accounts(conn)} == {"Cash": 10000 - 50000, "Revolut": 10000 + 50000}


def test_completing_the_linked_task_posts_its_scheduled_rows(conn):
    a = account(conn)
    task(conn)
    schedule(conn, a, task_uid="t1")
    task(conn, status="done")
    [posted] = finance.list_transactions(conn)
    assert posted["description"] == "Bus pass"
    assert finance.list_scheduled(conn) == []


def test_editing_a_done_task_again_does_not_post_twice(conn):
    a = account(conn)
    task(conn, status="done")
    schedule(conn, a, task_uid="t1")
    task(conn, status="done", title="Renamed")
    assert finance.list_transactions(conn) == [] and len(finance.list_scheduled(conn)) == 1


def test_deleting_the_task_keeps_the_scheduled_row_unlinked(conn):
    a = account(conn)
    task(conn)
    uid = schedule(conn, a, task_uid="t1")
    db.delete_task(conn, "t1")
    row = finance.get_scheduled(conn, uid)
    assert row["task_uid"] is None


def test_the_task_form_rows_replace_the_tasks_list_and_report_errors(conn):
    a = account(conn)
    task(conn)
    base = dict(type="income", amount="15", account_uid=a, description="Mihai pays for the meal")
    assert finance.sync_task_rows(conn, "t1", [base]) == []
    [row] = finance.list_scheduled(conn, task_uid="t1")
    assert finance.sync_task_rows(conn, "t1", [{**base, "uid": row["uid"], "amount": "20"}]) == []
    assert [r["amount"] for r in finance.list_scheduled(conn, task_uid="t1")] == [2000]
    assert finance.sync_task_rows(conn, "t1", [{**base, "amount": "x"}])[0]["field"] == "amount"
    assert len(finance.list_scheduled(conn, task_uid="t1")) == 1
    assert finance.sync_task_rows(conn, "t1", []) == [] and finance.list_scheduled(conn, task_uid="t1") == []


def test_scheduled_rows_list_dated_ones_first_and_filter_by_account_and_type(conn):
    a, b = account(conn, "Cash"), account(conn, "Bank")
    schedule(conn, a, description="Later", date="2026-12-01")
    schedule(conn, b, description="Undated", date="", type="income")
    schedule(conn, a, description="Sooner", date="2026-11-01")
    assert [r["description"] for r in finance.list_scheduled(conn)] == ["Sooner", "Later", "Undated"]
    assert [r["description"] for r in finance.list_scheduled(conn, {"account_uid": b})] == ["Undated"]
    assert [r["description"] for r in finance.list_scheduled(conn, {"type": "income"})] == ["Undated"]


def test_scheduled_rows_are_backed_up_and_deleted_with_their_account(conn, tmp_path):
    a = account(conn)
    schedule(conn, a)
    payload = finance.backup_rows(conn)
    with db.connect(tmp_path / "other.sqlite") as other:
        finance.restore_rows(other, payload)
        assert len(finance.list_scheduled(other)) == 1
    finance.delete_account(conn, a)
    assert finance.list_scheduled(conn) == []


def test_next_occurrence_follows_the_rule_after_a_date():
    assert finance_stats.next_occurrence("FREQ=MONTHLY;BYMONTHDAY=5", "2026-10-05", date(2026, 10, 8)) == "2026-11-05"
    assert finance_stats.next_occurrence("FREQ=WEEKLY", "2026-10-05", date(2026, 10, 5)) == "2026-10-12"
    assert finance_stats.next_occurrence("FREQ=DAILY;COUNT=1", "2026-10-05", date(2026, 10, 5)) == ""
    assert finance_stats.valid_rule("FREQ=WEEKLY") and not finance_stats.valid_rule("nonsense")


def _request(path="/finance/transactions"):
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def _form(**values):
    class Form(dict):
        def getlist(self, key):
            return []

    class Req:
        async def form(self):
            return Form(values)

    return Req()


def test_the_transaction_form_creates_a_scheduled_row_when_the_status_is_scheduled(conn):
    import asyncio

    from src.routers import finance as router
    a = account(conn)
    resp = asyncio.run(router.create_transaction(
        _form(status="scheduled", type="expense", amount="80", account_uid=a, description="Bus pass", date="2026-11-01"),
        x_requested_with="fetch", conn=conn))
    assert resp.status_code == 201 and finance.list_transactions(conn) == [] and len(finance.list_scheduled(conn)) == 1


def test_a_new_transaction_is_always_posted_without_choosing_a_status(conn):
    import asyncio

    from src.routers import finance as router
    a = account(conn)
    resp = asyncio.run(router.create_transaction(_form(type="expense", amount="5", account_uid=a, date="2026-10-02"),
                                                 x_requested_with="fetch", conn=conn))
    assert resp.status_code == 201
    assert [t["amount"] for t in finance.list_transactions(conn)] == [500]
    assert finance.list_scheduled(conn) == []


def test_scheduled_rows_sit_grayed_at_the_top_of_the_transactions_table(conn):
    from src.routers import finance as router
    a = account(conn)
    clean, _ = finance.validate_transaction(conn, dict(date="2026-10-02", type="expense", amount="5", account_uid=a, description="Posted lunch"))
    finance.save_transaction(conn, clean)
    schedule(conn, a, description="Pending subscription")
    body = router.transactions(_request(), month="2026-10", conn=conn).body.decode()
    assert body.index("Pending subscription") < body.index("Posted lunch")
    assert 'class="entity-row finance-pending"' in body and "/finance/scheduled/" in body


def test_posting_from_the_table_makes_the_row_real(conn):
    from src.routers import finance as router
    a = account(conn)
    uid = schedule(conn, a)
    router.post_scheduled(uid, conn=conn)
    assert finance.list_scheduled(conn) == [] and len(finance.list_transactions(conn)) == 1


def test_the_scheduled_edit_modal_has_no_status_choice_and_keeps_its_task_and_recurrence(conn):
    from src.routers import finance as router
    a = account(conn)
    task(conn)
    uid = schedule(conn, a, task_uid="t1", recurrence="FREQ=MONTHLY")
    body = router.edit_scheduled_modal(uid, _request(), conn=conn).body.decode()
    assert 'name="status" value="scheduled"' in body and "FREQ=MONTHLY" in body and "Renew the bus subscription" in body


def test_the_pending_filters_follow_the_table_filters(conn):
    from src.routers import finance as router
    a, b = account(conn, "Cash"), account(conn, "Bank")
    schedule(conn, a, description="Cash thing")
    schedule(conn, b, description="Bank thing")
    body = router.transactions(_request(), account=b, month="2026-10", conn=conn).body.decode()
    assert "Bank thing" in body and "Cash thing" not in body


def test_the_task_edit_form_lists_its_pending_transactions(conn):
    from src.routers import tasks as tasks_router
    a = account(conn, "Cash")
    task(conn)
    schedule(conn, a, task_uid="t1", description="Bus pass")
    body = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn).body.decode()
    assert "Pending transactions" in body and 'value="Bus pass"' in body and 'name="pt_account"' in body


def test_the_task_edit_form_hides_the_section_until_an_account_exists(conn):
    from src.routers import tasks as tasks_router
    task(conn)
    body = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn).body.decode()
    assert "Pending transactions" not in body


def test_saving_the_task_form_saves_its_pending_transactions_and_validates_them_first(conn):
    from src.routers import tasks as tasks_router
    a = account(conn, "Cash")
    tags.add_finance_tag(conn, "monthly")
    tags.add_finance_tag(conn, "commute")
    task(conn)
    kwargs = dict(title="Renew", description="", due_at="", start_at="", status="active", tags="", tags_labels=[], project="", project_field="", recurrence="", pending_tx_present="1", pt_key=["1"], pending_tags={"1": ["monthly", "commute"]}, pt_uid=[""], pt_type=["Expense"], pt_amount=["80"],
                  pt_description=["Bus pass"], pt_account=["Cash"], pt_to_account=[""], pt_date=["2026-11-01"], x_requested_with="fetch")
    bad = tasks_router.update_task("t1", **{**kwargs, "pt_amount": ["abc"]}, conn=conn)
    assert bad.status_code == 422 and db.get_task(conn, "t1")["title"] == "Renew the bus subscription"
    tasks_router.update_task("t1", **kwargs, conn=conn)
    [row] = finance.list_scheduled(conn, task_uid="t1")
    assert row["amount"] == 8000 and row["account_uid"] == a and row["type"] == "expense" and row["date"] == "2026-11-01"
    assert row["tags"] == ["commute", "monthly"]


def test_tags_travel_from_the_scheduled_row_to_the_real_transaction(conn):
    tags.add_finance_tag(conn, "commute")
    tags.add_finance_tag(conn, "monthly")
    a = account(conn)
    uid = schedule(conn, a, tags=["commute", "monthly"])
    assert finance.get_scheduled(conn, uid)["tags"] == ["commute", "monthly"]
    new = finance.post_scheduled(conn, uid, "2026-10-20")
    assert finance.get_transaction(conn, new)["tags"] == ["commute", "monthly"]
    assert finance.list_scheduled(conn) == []


def test_a_transfer_keeps_no_tags(conn):
    a, b = account(conn, "Cash"), account(conn, "Revolut")
    uid = schedule(conn, a, type="transfer", to_account_uid=b, tags=["x"])
    assert finance.get_scheduled(conn, uid)["tags"] == []


def test_tags_are_never_made_on_a_scheduled_row(conn):
    a = account(conn)
    uid = schedule(conn, a, tags=["commute"])
    assert finance.get_scheduled(conn, uid)["tags"] == [] and tags.get_tag(conn, "commute") is None


def test_the_task_form_rows_ask_for_a_description_and_offer_tags_and_type_dependent_accounts(conn):
    from src.routers import tasks as tasks_router
    account(conn, "Cash")
    task(conn)
    body = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn).body.decode()
    assert "<label>Description</label>" in body and "Tags" in body
    assert 'pending-tx-expense' in body and 'pending-tx-income' in body and 'pending-tx-to' in body and 'name="pt_key"' in body


def test_tags_survive_in_a_backup(conn, tmp_path):
    tags.add_finance_tag(conn, "monthly")
    a = account(conn)
    schedule(conn, a, tags=["monthly"])
    with db.connect(tmp_path / "other.sqlite") as other:
        finance.restore_rows(other, finance.backup_rows(conn))
        assert finance.list_scheduled(other)[0]["tags"] == ["monthly"]


def test_contacts_follow_a_scheduled_row_into_the_posted_transaction_and_go_with_deletes(conn):
    a = account(conn)
    sid = schedule(conn, a)
    people = db.resolve_contact_entries(conn, ["Ana Pop"])
    db.set_object_contacts(conn, "scheduled", sid, people)
    posted = finance.post_scheduled(conn, sid, "2026-11-02")
    assert [c["uid"] for c in db.list_object_contacts(conn, "transaction", posted)] == people
    assert db.list_object_contacts(conn, "scheduled", sid) == []
    finance.delete_transaction(conn, posted)
    assert db.list_object_contacts(conn, "transaction", posted) == []
