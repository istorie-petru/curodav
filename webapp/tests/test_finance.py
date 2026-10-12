"""Personal finance: accounts, transactions, transfers, labels and tags, filters, CSV and the pages."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import clock, db, finance, finance_stats
from src.routers import finance as router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


@pytest.fixture(autouse=True)
def fixed_today():
    clock.set_override(datetime(2026, 10, 15, 12, tzinfo=timezone.utc))
    yield
    clock.set_override(None)


def _request(path="/finance"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def account(conn, name="Cash", currency="RON", opening="100.00", on="2026-01-01", kind="cash"):
    clean, error = finance.validate_account(conn, dict(name=name, type=kind, currency=currency, opening_balance=opening, opening_date=on))
    assert error is None, error
    return finance.save_account(conn, clean)


def txn(conn, account_uid, day="2026-10-02", kind="expense", amount="10.00", **extra):
    clean, error = finance.validate_transaction(conn, dict(date=day, type=kind, amount=amount, account_uid=account_uid, **extra))
    assert error is None, error
    return finance.save_transaction(conn, clean)


def test_no_currency_or_type_is_imposed_on_a_new_account(conn):
    assert finance.default_currency(conn) == ""
    base = dict(name="X", opening_balance="0", opening_date="2026-01-01")
    assert finance.validate_account(conn, {**base, "type": "cash"})[1]["field"] == "currency"
    assert finance.validate_account(conn, {**base, "currency": "RON"})[1]["field"] == "type"


def test_the_account_modal_prefills_only_the_currency_chosen_in_settings(conn):
    body = router.new_account_modal(_request(), conn=conn).body.decode()
    assert 'name="opening_balance" value=""' in body or 'value="0.00"' not in body
    db.set_app_meta(conn, finance.DEFAULT_CURRENCY_KEY, "RON")
    assert router.new_account_modal(_request(), conn=conn).context["currency"] == "RON"


def test_the_transaction_modal_imposes_no_values(conn):
    account(conn)
    ctx = router.new_transaction_modal(_request(), conn=conn).context
    assert ctx["kind"] == "" and ctx["amount_text"] == "" and "today" not in ctx


def test_duplicating_a_transaction_opens_a_prefilled_create_form(conn):
    a = account(conn)
    uid = txn(conn, a, amount="42.00", description="Rent")
    resp = router.new_transaction_modal(_request(), copy=uid, conn=conn)
    ctx = resp.context
    assert ctx["form_action"] == "/finance/transactions" and ctx["copy"] and ctx["t"]["description"] == "Rent"
    assert ctx["status"] == "posted" and finance.get_transaction(conn, uid)["description"] == "Rent"
    assert len(finance.all_transactions(conn)) == 1


@pytest.mark.parametrize("data,field", [
    (dict(name=" ", opening_date="2026-01-01"), "name"),
    (dict(name="A", type="cash", currency="RON", opening_balance="abc", opening_date="2026-01-01"), "opening_balance"),
    (dict(name="A", type="cash", currency="RON", opening_balance="1", opening_date="soon"), "opening_date"),
    (dict(name="A", type="cash", currency="RON", opening_balance="", opening_date="2026-01-01"), "opening_balance"),
])
def test_invalid_accounts_report_the_field(conn, data, field):
    assert finance.validate_account(conn, data)[1]["field"] == field


def test_account_names_are_unique(conn):
    account(conn, "Cash")
    assert finance.validate_account(conn, dict(name="cash", type="cash", currency="RON", opening_balance="0", opening_date="2026-01-01"))[1]["field"] == "name"


def test_balance_is_derived_from_opening_balance_and_transactions(conn):
    a = account(conn, opening="100.00")
    txn(conn, a, kind="income", amount="50.00")
    txn(conn, a, kind="expense", amount="30.50")
    assert finance.list_accounts(conn)[0]["balance"] == 11950


def test_a_transfer_moves_money_between_accounts_without_changing_totals(conn):
    a, b = account(conn, "Checking", opening="1000.00"), account(conn, "Savings", opening="0")
    txn(conn, a, kind="transfer", amount="500.00", to_account_uid=b)
    balances = {x["name"]: x["balance"] for x in finance.list_accounts(conn)}
    assert balances == {"Checking": 50000, "Savings": 50000}
    totals = finance_stats.totals(finance.list_transactions(conn))
    assert totals == {"income": 0, "expenses": 0, "net": 0}


@pytest.mark.parametrize("extra,field", [
    (dict(kind="transfer"), "to_account_uid"),
    (dict(kind="transfer", to="same"), "to_account_uid"),
    (dict(kind="transfer", to="euro"), "to_account_uid"),
    (dict(amount="0"), "amount"), (dict(amount="x"), "amount"), (dict(day="31/10/2026"), "date"),
    (dict(day="2025-12-31"), "date"),
])
def test_invalid_transactions_report_the_field(conn, extra, field):
    a, e = account(conn), account(conn, "Euro", currency="EUR")
    data = dict(date=extra.get("day", "2026-10-02"), type=extra.get("kind", "expense"), amount=extra.get("amount", "5"), account_uid=a)
    if "to" in extra:
        data["to_account_uid"] = a if extra["to"] == "same" else e
    assert finance.validate_transaction(conn, data)[1]["field"] == field


def test_tags_are_stored_with_the_transaction(conn):
    a = account(conn)
    uid = txn(conn, a, tags=["transport", "bus"])
    row = finance.get_transaction(conn, uid)
    assert "label" not in row and row["tags"] == ["bus", "transport"]
    assert finance.tag_names(conn) == ["bus", "transport"]


def test_filters_narrow_by_search_account_type_and_dates(conn):
    a, b = account(conn, "Cash"), account(conn, "Bank")
    txn(conn, a, "2026-10-01", "expense", "5", description="Coffee beans")
    txn(conn, a, "2026-09-01", "income", "9", description="Salary")
    txn(conn, b, "2026-10-03", "expense", "7", description="Train")
    names = lambda f: sorted(t["description"] for t in finance.list_transactions(conn, f))
    assert names({"q": "coffee"}) == ["Coffee beans"]
    assert names({"account_uid": b}) == ["Train"]
    assert names({"type": "income"}) == ["Salary"]
    assert names({"date_from": "2026-10-01"}) == ["Coffee beans", "Train"]
    assert [t["description"] for t in finance.list_transactions(conn, {"sort": "amount", "dir": "asc"})][0] == "Coffee beans"


def test_deleting_an_account_removes_its_transactions_and_their_transfers(conn):
    a, b = account(conn, "A"), account(conn, "B")
    txn(conn, a, kind="expense", amount="1")
    txn(conn, b, kind="transfer", amount="2", to_account_uid=a)
    finance.delete_account(conn, a)
    assert finance.list_transactions(conn) == [] and [x["name"] for x in finance.list_accounts(conn)] == ["B"]


def test_a_currency_cannot_change_once_the_account_has_transactions(conn):
    a = account(conn, currency="RON")
    txn(conn, a)
    error = finance.validate_account(conn, dict(name="Cash", type="cash", currency="EUR", opening_balance="0", opening_date="2026-01-01"), a)[1]
    assert error["field"] == "currency"


def test_csv_import_creates_rows_and_reports_unknown_accounts(conn):
    account(conn, "Cash")
    rows, _ = finance_stats.parse_csv("date,account,amount,type,label,tags\n2026-10-01,Cash,5,expense,Food,a;b\n2026-10-02,Nope,5,expense,,\n")
    created, problems = finance.import_rows(conn, rows)
    assert created == 1 and problems == ["Line 3: there is no account named Nope"]
    assert finance.list_transactions(conn)[0]["tags"] == ["a", "b"]


def test_backup_round_trips_accounts_transactions_and_tags(conn, tmp_path):
    a = account(conn)
    txn(conn, a, tags=["x"], description="Lunch")
    payload = finance.backup_rows(conn)
    with db.connect(tmp_path / "other.sqlite") as other:
        finance.restore_rows(other, payload)
        row = finance.list_transactions(other)[0]
        assert row["description"] == "Lunch" and row["tags"] == ["x"]


def test_purge_all_data_clears_finance(conn):
    a = account(conn)
    txn(conn, a)
    db.purge_all_data(conn)
    assert finance.list_accounts(conn) == [] and finance.list_transactions(conn) == []


def test_pages_render_with_data(conn):
    a = account(conn)
    txn(conn, a, description="Lunch")
    for body in (
        router.accounts_page(_request('/settings/finance-accounts'), conn=conn).body,
        router.transactions(_request(), conn=conn).body, router.new_transaction_modal(_request(), conn=conn).body,
        router.new_account_modal(_request(), conn=conn).body,
    ):
        assert body
    assert "Lunch" in router.transactions(_request(), conn=conn).body.decode()


def test_the_save_route_returns_a_structured_error(conn):
    a = account(conn)
    import asyncio

    class FakeForm(dict):
        def getlist(self, key):
            return []

    class Req:
        async def form(self):
            return FakeForm(date="2026-10-02", type="expense", account_uid=a, amount="nope", status="posted")

    resp = asyncio.run(router.create_transaction(Req(), x_requested_with="fetch", conn=conn))
    assert resp.status_code == 422 and b"Amount must be a number above zero" in resp.body


def test_a_tag_on_an_unlabelled_transaction_survives_adding_a_label(conn):
    a = account(conn)
    uid = txn(conn, a, tags=["transport"])
    clean, _ = finance.validate_transaction(conn, dict(date="2026-10-02", type="expense", amount="10", account_uid=a,
                                                       label="Personal", tags=["transport"]))
    finance.save_transaction(conn, clean, uid)
    assert finance.get_transaction(conn, uid)["tags"] == ["transport"]


def test_tags_are_listed_with_group_and_usage(conn):
    db.upsert_label_config(conn, {"name": "Personal", "label_group": "Myself"})
    a = account(conn)
    txn(conn, a, label="Personal", tags=["transport"])
    txn(conn, a, label="Personal", tags=["transport", "food"])
    assert finance.list_tags(conn) == [{"name": "food", "color": "gray", "icon": "", "usage": 1},
                                       {"name": "transport", "color": "gray", "icon": "", "usage": 2}]


def test_a_tag_keeps_the_colour_and_icon_chosen_for_it(conn):
    clean, error = finance.validate_tag(conn, "food", None, "green", "tag")
    assert error is None
    finance.save_tag(conn, clean)
    assert finance.tag_styles(conn) == {"food": {"color": "green", "icon": "tag"}}
    finance.save_tag(conn, finance.validate_tag(conn, "meals", "food", "red", "")[0], "food")
    assert finance.tag_styles(conn) == {"meals": {"color": "red", "icon": ""}}


def test_an_account_shows_its_abbreviation_and_falls_back_to_its_name(conn):
    clean, _ = finance.validate_account(conn, dict(name="Savings", abbreviation=" SAV ", type="savings", currency="RON", opening_balance="0", opening_date="2026-01-01"))
    uid = finance.save_account(conn, clean)
    other = account(conn, "Cash")
    txn(conn, uid, kind="transfer", to_account_uid=other)
    row = finance.list_transactions(conn)[0]
    assert (row["account_abbr"], row["to_account_abbr"]) == ("SAV", "Cash")
    assert {a["name"]: a["short"] for a in finance.list_accounts(conn)} == {"Savings": "SAV", "Cash": "Cash"}


def test_dates_and_types_are_shortened_for_the_table():
    assert finance_stats.short_date("2026-04-05") == "05 Apr"
    assert finance_stats.TYPE_ABBREVIATIONS["transfer"] == "Trf"


def test_renaming_a_tag_renames_it_on_every_transaction(conn):
    a = account(conn)
    uid = txn(conn, a, tags=["trnsport"])
    clean, error = finance.validate_tag(conn, "transport", "trnsport")
    assert error is None
    finance.save_tag(conn, clean, "trnsport")
    assert finance.get_transaction(conn, uid)["tags"] == ["transport"] and [t["name"] for t in finance.list_tags(conn)] == ["transport"]


def test_deleting_a_tag_removes_it_from_transactions(conn):
    a = account(conn)
    uid = txn(conn, a, tags=["old"])
    finance.delete_tag(conn, "old")
    assert finance.get_transaction(conn, uid)["tags"] == [] and finance.list_tags(conn) == []


def test_tags_are_free_standing_and_unique_by_name(conn):
    finance.save_tag(conn, {"name": "bus"})
    assert finance.validate_tag(conn, "Bus")[1]["field"] == "name"
    assert finance.validate_tag(conn, "Bus", "bus")[1] is None


def test_tags_that_belonged_to_a_group_become_free_standing(conn):
    conn.execute("INSERT INTO finance_tags (group_name, name) VALUES ('Myself', 'bus'), ('Work', 'bus'), ('Work', 'taxi')")
    finance.free_tags(conn)
    assert sorted(t["name"] for t in finance.list_tags(conn)) == ["bus", "taxi"]


def test_the_taxonomy_page_lists_transaction_tags(conn):
    from src.routers import taxonomy
    finance.save_tag(conn, {"name": "bus"})
    body = taxonomy.page_response(conn, _request("/settings/taxonomy"), "tags").body.decode()
    assert "bus" in body and "Transaction tags" in body


def test_accounts_live_in_settings_and_the_transactions_page_does_not_link_to_them(conn):
    from src.routers import settings as settings_router
    assert "/settings/finance-accounts" in {c["url"] for c in settings_router.HUB_CATEGORIES}
    body = router.transactions(_request(), conn=conn).body.decode()
    assert "/finance/accounts" not in body and 'href="/finance/transactions/new"' not in body and "Import CSV" not in body


def test_the_quick_add_modal_offers_a_transaction_tab_once_an_account_exists(conn):
    from src.routers import dashboard
    body = dashboard.quick_add_form(_request("/quick/add"), default_tab="transaction", conn=conn).body.decode()
    assert 'data-quick-add-tab="transaction"' in body and "No accounts yet" in body and 'id="finance-transaction-form"' not in body
    account(conn)
    body = dashboard.quick_add_form(_request("/quick/add"), default_tab="transaction", conn=conn).body.decode()
    assert 'id="finance-transaction-form"' in body and 'name="amount"' in body




def test_the_overview_page_is_gone_and_the_finance_tab_opens_transactions():
    assert router.finance_home().headers["location"] == "/finance/transactions"


def test_the_table_shows_one_month_as_income_expenses_profit_and_savings(conn):
    a = account(conn, "Bank", kind="bank", opening="0")
    s = account(conn, "Pot", kind="savings", opening="0")
    txn(conn, a, "2026-10-01", "income", "100", description="Pay")
    txn(conn, a, "2026-10-02", "expense", "30", description="Food")
    txn(conn, a, "2026-10-03", "transfer", "20", to_account_uid=s, description="Save")
    txn(conn, a, "2026-09-30", "expense", "99", description="Last month")
    ctx = router.transactions(_request(), month="2026-10", conn=conn).context
    [section] = ctx["sections"]
    assert (section["income_total"], section["expenses_total"], section["profit"], section["savings"]) == (10000, 3000, 7000, 2000)
    body = router.transactions(_request(), month="2026-10", conn=conn).body.decode()
    assert "Total income" in body and "Total expenses" in body and "Profit" in body and "Savings" in body
    assert body.index("Total income") < body.index("Total expenses") < body.index(">Profit<") < body.index(">Savings<")
    assert "Last month" not in body and ctx["prev_month"] == "2026-09" and ctx["next_month"] == "2026-11"


def test_savings_counts_money_leaving_a_savings_account_and_ignores_other_transfers(conn):
    bank, other = account(conn, "Bank", kind="bank", opening="0"), account(conn, "Other", kind="bank", opening="0")
    pot = account(conn, "Pot", kind="savings", opening="100")
    txn(conn, bank, "2026-10-03", "transfer", "20", to_account_uid=other)
    txn(conn, pot, "2026-10-04", "transfer", "5", to_account_uid=bank)
    [section] = router.transactions(_request(), month="2026-10", conn=conn).context["sections"]
    assert section["savings"] == -500


def test_currencies_get_their_own_block(conn):
    txn(conn, account(conn, "Lei", currency="RON", opening="0"), "2026-10-02", "income", "10")
    txn(conn, account(conn, "Euro", currency="EUR", opening="0"), "2026-10-02", "income", "20")
    sections = {s["currency"]: s for s in router.transactions(_request(), month="2026-10", conn=conn).context["sections"]}
    assert sections["RON"]["income_total"] == 1000 and sections["EUR"]["income_total"] == 2000


def test_the_header_has_only_the_month_mover_and_an_accounts_filter(conn):
    body = router.transactions(_request(), conn=conn).body.decode()
    header = body[body.index("page-header-narrow-actions"):body.index('id="finance-filter-form"')]
    assert "Previous month" in header and "Next month" in header
    filters = body[body.index('id="finance-filter-form"'):body.index("</form>", body.index('id="finance-filter-form"'))]
    assert 'name="account"' in filters
    for gone in ('name="range"', 'name="label"', 'name="group"', 'name="type"', 'name="q"'):
        assert gone not in body


def test_transfers_move_money_but_are_not_listed_in_the_table(conn):
    a, b = account(conn, "Bank", kind="bank", opening="0"), account(conn, "Pot", kind="savings", opening="0")
    txn(conn, a, "2026-10-02", "income", "100")
    txn(conn, a, "2026-10-03", "transfer", "40", to_account_uid=b, description="Hidden move")
    body = router.transactions(_request(), month="2026-10", conn=conn).body.decode()
    assert "Hidden move" not in body and "Transfers" not in body
    balances = {x["name"]: x["balance"] for x in finance.list_accounts(conn)}
    assert balances == {"Bank": 6000, "Pot": 4000}


def test_quick_add_has_a_type_dropdown_beside_each_title_and_a_full_width_date(conn):
    from src.routers import dashboard
    account(conn)
    body = dashboard.quick_add_form(_request("/quick/add"), default_tab="transaction", conn=conn).body.decode()
    assert "quick-add-tabs" not in body and "seg-btn" not in body.split('id="quick-add-panels"')[1].split("</section>")[0]
    for kind in ("task", "event", "contact", "label", "transaction", "note"):
        assert f'name="qa_type_{kind}"' in body
    assert 'class="field field-wide">\n            <label>Date</label>' in body
