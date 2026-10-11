"""Finance maths: amounts, balances, monthly totals, transfers staying out of spending, and CSV."""

from __future__ import annotations

import pytest

from src import finance_stats as fs


@pytest.mark.parametrize("text,minor", [
    ("12.50", 1250), ("12,50", 1250), ("1,234.56", 123456), ("1.234,56", 123456), ("7", 700), ("-3.5", -350),
    ("1,000", 100000), (" 0.05 ", 5),
])
def test_amounts_are_read_into_minor_units(text, minor):
    assert fs.parse_amount(text) == minor


@pytest.mark.parametrize("text", ["", "abc", "1.2.3x", "--4"])
def test_unreadable_amounts_are_rejected(text):
    assert fs.parse_amount(text) is None


def test_money_is_formatted_with_grouping_sign_and_currency():
    assert fs.format_money(123456, "RON") == "1,234.56 RON"
    assert fs.format_money(-5, "EUR") == "-0.05 EUR"
    assert fs.format_money(500, signed=True) == "+5.00"


ACCOUNT = {"uid": "a", "opening_balance": 10000, "opening_date": "2026-01-01"}
OTHER = {"uid": "b", "opening_balance": 0, "opening_date": "2026-01-01"}


def txn(day, kind, amount, account="a", to=None, label=""):
    return {"date": day, "type": kind, "amount": amount, "account_uid": account, "to_account_uid": to, "label": label}


def test_balance_is_opening_plus_every_transaction_on_the_account():
    txns = [txn("2026-02-01", "income", 5000), txn("2026-02-02", "expense", 2000),
            txn("2026-02-03", "transfer", 3000, "a", "b"), txn("2026-02-04", "transfer", 1000, "b", "a")]
    assert fs.balance_on(ACCOUNT, txns) == 10000 + 5000 - 2000 - 3000 + 1000
    assert fs.balance_on(OTHER, txns) == 3000 - 1000


def test_balance_ignores_transactions_before_the_opening_date_and_after_the_asked_day():
    txns = [txn("2025-12-31", "income", 999), txn("2026-02-01", "income", 100), txn("2026-03-01", "income", 100)]
    assert fs.balance_on(ACCOUNT, txns, "2026-02-15") == 10100


def test_a_transfer_is_never_income_or_spending():
    txns = [txn("2026-02-01", "transfer", 5000, "a", "b"), txn("2026-02-02", "income", 700), txn("2026-02-03", "expense", 200)]
    assert fs.totals(txns) == {"income": 700, "expenses": 200, "net": 500}


def test_spending_by_label_groups_unlabelled_and_sorts_largest_first():
    rows = fs.spending_by_label([txn("d", "expense", 100, label="Food"), txn("d", "expense", 300, label="Rent"),
                                 txn("d", "expense", 100, label="Food"), txn("d", "expense", 50)])
    assert [(r["label"], r["amount"]) for r in rows] == [("Rent", 300), ("Food", 200), ("", 50)]
    assert round(sum(r["share"] for r in rows), 6) == 1


def test_balance_trend_reports_month_end_balances_across_both_accounts():
    txns = [txn("2026-01-15", "income", 1000), txn("2026-02-10", "transfer", 4000, "a", "b")]
    trend = fs.balance_trend([ACCOUNT, OTHER], txns, ["2026-01", "2026-02"])
    assert [p["balance"] for p in trend] == [11000, 11000]
    assert [p["balance"] for p in fs.balance_trend([ACCOUNT], txns, ["2026-01", "2026-02"])] == [11000, 7000]


def test_month_helpers_cross_year_boundaries():
    assert fs.month_add("2026-11", 3) == "2027-02" and fs.month_add("2026-01", -1) == "2025-12"
    assert fs.month_end("2026-02") == "2026-02-28" and fs.months_between("2026-11", "2027-01") == ["2026-11", "2026-12", "2027-01"]


def test_chart_geometry_handles_empty_flat_and_single_point_series():
    assert fs.line_chart([])["dots"] == []
    flat = fs.line_chart([{"balance": 5, "month": "a"}, {"balance": 5, "month": "b"}])
    assert len(flat["dots"]) == 2 and flat["dots"][0]["y"] == flat["dots"][1]["y"]
    assert len(fs.line_chart([{"balance": 1, "month": "a"}])["dots"]) == 1
    arcs = fs.doughnut([{"share": 1.0}])
    assert len(arcs) == 1 and arcs[0]["path"].startswith("M ")


def test_csv_round_trips_through_export_and_import():
    rows = [{"date": "2026-02-01", "description": "Lunch, with tip", "account_name": "Cash", "type": "expense",
             "amount": 1250, "label": "Food", "tags": ["out", "work"], "to_account_name": ""}]
    parsed, problems = fs.parse_csv(fs.to_csv(rows))
    assert problems == [] and parsed[0]["description"] == "Lunch, with tip" and parsed[0]["amount"] == 1250
    assert parsed[0]["tags"] == "out;work" and parsed[0]["account"] == "Cash"


def test_csv_import_reports_bad_lines_and_keeps_good_ones():
    text = "date,account,amount,type\n2026-02-01,Cash,5,income\nnope,Cash,5,income\n2026-02-02,Cash,x,expense\n2026-02-03,Cash,5,gift\n"
    rows, problems = fs.parse_csv(text)
    assert len(rows) == 1 and len(problems) == 3 and problems[0].startswith("Line 3")


def test_csv_without_the_required_columns_is_refused():
    assert fs.parse_csv("a,b\n1,2\n") == ([], ["The file needs at least the columns date, account and amount."])


def test_csv_import_infers_the_type_from_the_sign_when_missing():
    rows, _ = fs.parse_csv("date,account,amount\n2026-02-01,Cash,-5\n2026-02-02,Cash,5\n")
    assert [(r["type"], r["amount"]) for r in rows] == [("expense", 500), ("income", 500)]
