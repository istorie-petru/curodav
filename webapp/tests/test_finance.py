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


def test_a_label_and_tags_are_stored_with_the_transaction(conn):
    a = account(conn)
    db.upsert_label_config(conn, {"name": "Personal", "label_group": "Myself"})
    uid = txn(conn, a, label="Personal", tags=["transport", "bus"])
    row = finance.get_transaction(conn, uid)
    assert row["label"] == "Personal" and row["tags"] == ["bus", "transport"]
    assert finance.tag_names(conn) == ["bus", "transport"]


def test_filters_narrow_by_search_account_type_label_and_dates(conn):
    a, b = account(conn, "Cash"), account(conn, "Bank")
    txn(conn, a, "2026-10-01", "expense", "5", description="Coffee beans", label="Food")
    txn(conn, a, "2026-09-01", "income", "9", description="Salary")
    txn(conn, b, "2026-10-03", "expense", "7", description="Train", label="Travel")
    names = lambda f: sorted(t["description"] for t in finance.list_transactions(conn, f))
    assert names({"q": "coffee"}) == ["Coffee beans"]
    assert names({"account_uid": b}) == ["Train"]
    assert names({"type": "income"}) == ["Salary"]
    assert names({"label": "Food"}) == ["Coffee beans"]
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
    txn(conn, a, label="Food", tags=["x"], description="Lunch")
    payload = finance.backup_rows(conn)
    with db.connect(tmp_path / "other.sqlite") as other:
        finance.restore_rows(other, payload)
        row = finance.list_transactions(other)[0]
        assert row["description"] == "Lunch" and row["label"] == "Food" and row["tags"] == ["x"]


def test_purge_all_data_clears_finance(conn):
    a = account(conn)
    txn(conn, a)
    db.purge_all_data(conn)
    assert finance.list_accounts(conn) == [] and finance.list_transactions(conn) == []


def test_period_presets_use_the_injected_today():
    today = clock.today()
    assert router.date_range("month", today) == ("2026-10-01", "2026-10-31")
    assert router.date_range("last_month", today) == ("2026-09-01", "2026-09-30")
    assert router.date_range("6m", today) == ("2026-05-01", "2026-10-31")
    assert router.date_range("all", today) == ("", "")


def test_overview_counts_transfers_in_neither_income_nor_spending(conn):
    a, b = account(conn, "A", opening="0"), account(conn, "B", opening="0")
    txn(conn, a, kind="income", amount="100")
    txn(conn, a, kind="expense", amount="30", label="Food")
    txn(conn, a, kind="transfer", amount="40", to_account_uid=b)
    [section] = router._overview_sections(conn, "2026-10-01", "2026-10-31", "")
    assert section["totals"] == {"income": 10000, "expenses": 3000, "net": 7000}
    assert section["cash"] == 7000 and [p["label"] for p in section["pies"][0]["slices"]] == ["Food"] and len(section["pies"]) == 1


def test_overview_keeps_currencies_apart(conn):
    txn(conn, account(conn, "Lei", currency="RON", opening="0"), kind="income", amount="10")
    txn(conn, account(conn, "Euro", currency="EUR", opening="0"), kind="income", amount="20")
    sections = {s["currency"]: s for s in router._overview_sections(conn, "2026-10-01", "2026-10-31", "")}
    assert sections["RON"]["totals"]["income"] == 1000 and sections["EUR"]["totals"]["income"] == 2000


def test_pages_render_with_data(conn):
    a = account(conn)
    txn(conn, a, description="Lunch", label="Food")
    for body in (
        router.overview(_request(), conn=conn).body, router.accounts_page(_request('/settings/finance-accounts'), conn=conn).body,
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


def test_doughnut_slices_get_distinct_colours_even_when_labels_share_one(conn):
    rows = [{"label": "Food"}, {"label": "Rent"}, {"label": ""}]
    router._assign_colors(conn, rows)
    assert len({r["color"] for r in rows[:2]}) == 2 and rows[2]["color"] == "gray"


def test_tags_already_picked_stay_when_the_label_changes(conn):
    db.upsert_label_config(conn, {"name": "Personal", "label_group": "Myself"})
    ctx = router.tag_field(_request(), label="Personal", tags=["transport"], conn=conn).context
    assert ctx["tag_selected"] == ["transport"] and [t["uid"] for t in ctx["tag_items"]] == ["transport"]


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


def test_every_label_offers_every_tag(conn):
    db.upsert_label_config(conn, {"name": "Personal", "label_group": "Myself"})
    finance.save_tag(conn, {"name": "bus"})
    assert router._tag_context(conn, "Personal", [])["tag_items"] == router._tag_context(conn, "", [])["tag_items"] == [{"uid": "bus", "name": "bus"}]


def test_tags_that_belonged_to_a_group_become_free_standing(conn):
    conn.execute("INSERT INTO finance_tags (group_name, name) VALUES ('Myself', 'bus'), ('Work', 'bus'), ('Work', 'taxi')")
    finance.free_tags(conn)
    assert sorted(t["name"] for t in finance.list_tags(conn)) == ["bus", "taxi"]


def test_the_taxonomy_page_lists_transaction_tags(conn):
    from src.routers import taxonomy
    finance.save_tag(conn, {"name": "bus"})
    body = taxonomy.page_response(conn, _request("/settings/taxonomy"), "tags").body.decode()
    assert "bus" in body and "Transaction tags" in body


def test_accounts_live_in_settings_and_the_finance_header_does_not_link_to_them(conn):
    from src.routers import settings as settings_router
    assert "/settings/finance-accounts" in {c["url"] for c in settings_router.HUB_CATEGORIES}
    assert all(link["url"] != "/settings/finance-accounts" for link in router._header_links("overview"))
    body = router.transactions(_request(), conn=conn).body.decode()
    assert "/finance/accounts" not in body and 'href="/finance/transactions/new"' not in body and "Import CSV" not in body


def test_the_quick_add_modal_offers_a_transaction_tab_once_an_account_exists(conn):
    from src.routers import dashboard
    body = dashboard.quick_add_form(_request("/quick/add"), default_tab="transaction", conn=conn).body.decode()
    assert 'data-quick-add-tab="transaction"' in body and "No accounts yet" in body and 'id="finance-transaction-form"' not in body
    account(conn)
    body = dashboard.quick_add_form(_request("/quick/add"), default_tab="transaction", conn=conn).body.decode()
    assert 'id="finance-transaction-form"' in body and 'name="amount"' in body


def test_sort_links_and_filters_refresh_in_place(conn):
    a = account(conn)
    txn(conn, a)
    body = router.transactions(_request(), conn=conn).body.decode()
    assert 'id="finance-transactions-region" data-smart-region' in body and "data-smart-form" in body
    assert body.count("data-smart-link") >= 3


def test_transactions_filter_by_a_custom_date_range(conn):
    a = account(conn)
    txn(conn, a, "2026-09-01", description="Early")
    txn(conn, a, "2026-10-05", description="Inside")
    txn(conn, a, "2026-11-20", description="Late")
    body = router.transactions(_request(), range="custom", date_from="2026-10-01", date_to="2026-10-31", conn=conn).body.decode()
    assert "Inside" in body and "Early" not in body and "Late" not in body
    assert "Early" in router.transactions(_request(), range="all", conn=conn).body.decode()


def test_the_period_and_label_filters_live_in_the_header_bar(conn):
    ctx = router.transactions(_request(), conn=conn)
    body = ctx.body.decode()
    header = body[body.index("page-header-narrow-actions"):body.index("finance-filter-form\" class")]
    assert 'name="range"' in header and 'name="label"' in header
