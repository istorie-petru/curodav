"""Tests for formula_engine.py (Phase 7's custom-database formula
language). Covers: tokenizing/parsing edge cases, arithmetic precedence,
row-formula column references (including bracketed names with spaces),
every aggregate function, WEIGHTAVG specifically (the driving use case --
weighted grade averages), and that every failure mode degrades to
(None, error) instead of raising."""

from __future__ import annotations

from src import formula_engine as fe


class TestArithmetic:
    def test_simple_addition(self):
        value, err = fe.evaluate("1 + 2", None, [])
        assert err is None
        assert value == 3

    def test_operator_precedence(self):
        value, err = fe.evaluate("2 + 3 * 4", None, [])
        assert value == 14

    def test_parentheses_override_precedence(self):
        value, err = fe.evaluate("(2 + 3) * 4", None, [])
        assert value == 20

    def test_unary_minus(self):
        value, err = fe.evaluate("-5 + 3", None, [])
        assert value == -2

    def test_division(self):
        value, err = fe.evaluate("10 / 4", None, [])
        assert value == 2.5

    def test_division_by_zero_is_a_formula_error_not_a_crash(self):
        value, err = fe.evaluate("1 / 0", None, [])
        assert value is None
        assert "zero" in err.lower()

    def test_decimal_numbers(self):
        value, err = fe.evaluate("1.5 * 2", None, [])
        assert value == 3.0

    def test_nested_parens(self):
        value, err = fe.evaluate("((1 + 2) * (3 + 4))", None, [])
        assert value == 21


class TestColumnReferences:
    def test_bare_identifier_no_spaces(self):
        value, err = fe.evaluate("grade * 2", {"grade": 5}, [])
        assert value == 10

    def test_bracketed_identifier_with_spaces(self):
        value, err = fe.evaluate("[Final Grade] * 2", {"Final Grade": 5}, [])
        assert err is None
        assert value == 10

    def test_row_formula_references_two_columns(self):
        row = {"grade": 8, "weight": 0.5}
        value, err = fe.evaluate("grade * weight", row, [])
        assert value == 4.0

    def test_missing_column_is_an_error(self):
        value, err = fe.evaluate("grade * 2", {}, [])
        assert value is None
        assert "grade" in err

    def test_non_numeric_column_value_is_an_error(self):
        value, err = fe.evaluate("grade * 2", {"grade": "not a number"}, [])
        assert value is None

    def test_bare_column_ref_in_summary_context_is_an_error(self):
        # row=None means "summary formula" -- no single row to resolve
        # a bare reference against.
        value, err = fe.evaluate("grade", None, [{"grade": 5}])
        assert value is None
        assert "summary" in err.lower() or "bare" in err.lower()


class TestAggregateFunctions:
    ROWS = [{"grade": 10, "weight": 2}, {"grade": 6, "weight": 1}, {"grade": 8, "weight": 1}]

    def test_sum(self):
        value, err = fe.evaluate("SUM(grade)", None, self.ROWS)
        assert value == 24

    def test_avg(self):
        value, err = fe.evaluate("AVG(grade)", None, self.ROWS)
        assert value == 8

    def test_min_max(self):
        assert fe.evaluate("MIN(grade)", None, self.ROWS)[0] == 6
        assert fe.evaluate("MAX(grade)", None, self.ROWS)[0] == 10

    def test_count_ignores_missing_values(self):
        rows = [{"grade": 5}, {"grade": None}, {"grade": ""}, {"grade": 7}]
        value, err = fe.evaluate("COUNT(grade)", None, rows)
        assert value == 2

    def test_sum_ignores_non_numeric_and_missing(self):
        rows = [{"grade": 5}, {"grade": "n/a"}, {}, {"grade": 3}]
        value, err = fe.evaluate("SUM(grade)", None, rows)
        assert value == 8

    def test_aggregate_over_empty_column_is_an_error_except_count(self):
        value, err = fe.evaluate("AVG(grade)", None, [{}])
        assert value is None
        assert fe.evaluate("COUNT(grade)", None, [{}])[0] == 0

    def test_wrong_arg_count_is_an_error(self):
        value, err = fe.evaluate("SUM(grade, weight)", None, self.ROWS)
        assert value is None
        assert "argument" in err.lower()

    def test_aggregate_arg_must_be_a_plain_column_reference(self):
        value, err = fe.evaluate("SUM(grade * 2)", None, self.ROWS)
        assert value is None


class TestWeightedAverage:
    """The driving use case: 'media aritmetica ponderata' -- a weighted
    grade average."""

    def test_basic_weighted_average(self):
        rows = [{"grade": 10, "weight": 2}, {"grade": 6, "weight": 1}]
        # (10*2 + 6*1) / (2+1) = 26/3
        value, err = fe.evaluate("WEIGHTAVG(grade, weight)", None, rows)
        assert err is None
        assert round(value, 4) == round(26 / 3, 4)

    def test_rows_missing_either_value_are_excluded(self):
        rows = [
            {"grade": 10, "weight": 2},
            {"grade": 6},  # no weight -- excluded
            {"weight": 5},  # no grade -- excluded
        ]
        value, err = fe.evaluate("WEIGHTAVG(grade, weight)", None, rows)
        assert value == 10  # only the first row counts

    def test_zero_total_weight_is_an_error(self):
        rows = [{"grade": 10, "weight": 0}]
        value, err = fe.evaluate("WEIGHTAVG(grade, weight)", None, rows)
        assert value is None
        assert "weight" in err.lower()

    def test_requires_plain_column_references(self):
        value, err = fe.evaluate("WEIGHTAVG(grade * 2, weight)", None, [{"grade": 1, "weight": 1}])
        assert value is None

    def test_used_as_a_summary_formula_matches_manual_calculation(self):
        # A realistic grade-tracking table: 3 assignments with different
        # credit weights.
        rows = [
            {"assignment": "Midterm", "grade": 85, "weight": 30},
            {"assignment": "Final", "grade": 90, "weight": 50},
            {"assignment": "Homework", "grade": 70, "weight": 20},
        ]
        value, err = fe.evaluate("WEIGHTAVG(grade, weight)", None, rows)
        expected = (85 * 30 + 90 * 50 + 70 * 20) / (30 + 50 + 20)
        assert round(value, 6) == round(expected, 6)


class TestRobustness:
    def test_empty_formula(self):
        value, err = fe.evaluate("", None, [])
        assert value is None and err

    def test_malformed_syntax_does_not_raise(self):
        value, err = fe.evaluate("1 + + 2", None, [])
        assert value is None and err

    def test_unbalanced_parens_does_not_raise(self):
        value, err = fe.evaluate("(1 + 2", None, [])
        assert value is None and err

    def test_unknown_function_treated_as_column_reference(self):
        # "FOO(" isn't a recognized aggregate name, so FOO is parsed as a
        # column reference and "(" is then a syntax error (no operator
        # between two factors) -- still must not raise.
        value, err = fe.evaluate("FOO(grade)", {"FOO": 1, "grade": 2}, [])
        assert value is None and err

    def test_unterminated_bracket_does_not_raise(self):
        value, err = fe.evaluate("[grade * 2", None, [])
        assert value is None and err

    def test_garbage_character_does_not_raise(self):
        value, err = fe.evaluate("1 $ 2", None, [])
        assert value is None and err
