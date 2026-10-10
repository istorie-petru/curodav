"""The table model (formulas, structure, sorting, paste and export), run under node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODEL_JS = Path(__file__).resolve().parent.parent / "src" / "static" / "notebook" / "notebook_table_model.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(expression: str):
    script = f"const M=require(process.argv[1]); console.log(JSON.stringify({expression}))"
    out = subprocess.run(["node", "-e", script, str(MODEL_JS)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def texts(grid, merges=None):
    return run(f"M.evaluate({json.dumps(grid)}, {json.dumps(merges or [])}).map(r=>r.map(c=>c.text))")


class TestFormulas:
    def test_arithmetic_and_references(self):
        assert texts([["2", "3", "=A1*B1+1"]])[0][2] == "7"

    @pytest.mark.parametrize("formula, expected", [
        ("=SUM(A1:A3)", "6"), ("=AVERAGE(A1:A3)", "2"), ("=MIN(A1:A3)", "1"), ("=MAX(A1:A3)", "3"),
        ("=COUNT(A1:A3)", "3"), ("=ROUND(10/3, 2)", "3.33"), ("=-A1+2*(A2+A3)", "9"),
    ])
    def test_functions(self, formula, expected):
        assert texts([["1"], ["2"], ["3"], [formula]])[3][0] == expected

    def test_above_and_left_sum_the_run_of_numbers_next_to_the_cell(self):
        grid = [["Name", "x"], ["a", "1"], ["b", "2"], ["Total", "=SUM(above)"], ["", ""]]
        assert texts(grid)[3][1] == "3"
        assert texts([["note", "1", "2", "=SUM(left)"]])[0][3] == "3"

    def test_text_cells_are_ignored_by_functions_but_break_arithmetic(self):
        assert texts([["x"], ["4"], ["=SUM(A1:A2)"], ["=A1+1"]])[2][0] == "4"
        assert texts([["x"], ["=A1+1"]])[1][0] == "#VALUE!"

    @pytest.mark.parametrize("formula, error", [
        ("=1/0", "#DIV/0!"), ("=AVERAGE(B1:B2)", "#DIV/0!"), ("=A1+", "#ERR"), ("=FOO(1)", "#NAME?"),
        ("=Z99", "#REF!"), ("=A1", "#CYCLE"),
    ])
    def test_errors_are_short_codes(self, formula, error):
        assert texts([[formula, "", ""], ["", "", ""]])[0][0] == error

    def test_a_formula_in_html_is_still_a_formula(self):
        assert texts([["<b>=1+1</b>"]])[0][0] == "2"

    def test_numbers_with_separators_and_percent_are_numbers(self):
        assert texts([["1,000", "50%", "=A1+B1"]])[0][2] == "1000.5"


class TestStructure:
    def model(self, content, merges=None):
        return {"content": content, "merges": merges or [], "align": {}, "colors": {}}

    def test_inserting_a_row_shifts_references_below_it(self):
        out = run(f"M.insertRow({json.dumps(self.model([['1'], ['2'], ['=SUM(A1:A2)']]))}, 1)")
        assert out["content"][3][0] == "=SUM(A1:A3)"

    def test_deleting_a_referenced_row_gives_a_ref_error_and_shrinks_ranges(self):
        out = run(f"M.deleteRow({json.dumps(self.model([['1'], ['2'], ['3'], ['=A2+SUM(A1:A3)']]))}, 1)")
        assert out["content"][2][0] == "=#REF!+SUM(A1:A2)"

    def test_column_changes_shift_references_and_alignment(self):
        model = self.model([["1", "2", "=B1"]])
        model["align"] = {"1": "right"}
        out = run(f"M.insertCol({json.dumps(model)}, 0)")
        assert out["content"][0] == ["", "1", "2", "=C1"] and out["align"] == {"2": "right"}

    def test_merges_grow_and_shrink_with_rows(self):
        merged = self.model([["a", "b"], ["c", "d"], ["e", "f"]], [{"r": 0, "c": 0, "rs": 2, "cs": 1}])
        assert run(f"M.insertRow({json.dumps(merged)}, 1)")["merges"] == [{"r": 0, "c": 0, "rs": 3, "cs": 1}]
        assert run(f"M.deleteRow({json.dumps(merged)}, 1)")["merges"] == []
        assert run(f"M.insertRow({json.dumps(merged)}, 0)")["merges"] == [{"r": 1, "c": 0, "rs": 2, "cs": 1}]

    def test_merge_and_split(self):
        assert run("M.merge([], 0, 0, 1, 2)") == [{"r": 0, "c": 0, "rs": 2, "cs": 3}]
        assert run("M.split(M.merge([], 0, 0, 1, 2), 1, 1, 1, 1)") == []

    def test_a_merged_cell_hides_the_cells_it_covers_from_formulas(self):
        grid = [["1", "9"], ["2", "9"], ["=SUM(A1:B2)", ""]]
        merged = [{"r": 0, "c": 1, "rs": 2, "cs": 1}]
        assert texts(grid, merged)[2][0] == "12"


class TestSortingAndPaste:
    def test_rows_sort_numerically_and_empties_go_last(self):
        grid = [["h"], ["10"], ["2"], [""], ["33"]]
        order = run(f"M.sortedOrder(M.evaluate({json.dumps(grid)}, []), 0, 'asc', 1)")
        assert order == [0, 2, 1, 4, 3]
        assert run(f"M.sortedOrder(M.evaluate({json.dumps(grid)}, []), 0, 'desc', 1)")[1:3] == [4, 1]

    def test_sorting_is_off_when_there_are_formulas_or_merges(self):
        assert run("M.canSort({content: [['1'], ['2']], merges: []})") is True
        assert run("M.canSort({content: [['=1']], merges: []})") is False
        assert run("M.canSort({content: [['1']], merges: [{r:0,c:0,rs:1,cs:2}]})") is False

    def test_numeric_columns_are_detected_ignoring_the_header(self):
        values = f"M.evaluate({json.dumps([['n', 't'], ['1', 'a'], ['2', 'b']])}, [])"
        assert run(f"M.isNumericColumn({values}, 0, 1)") is True
        assert run(f"M.isNumericColumn({values}, 1, 1)") is False

    def test_spreadsheet_and_markdown_paste(self):
        assert run("M.tsvToGrid('a\\tb\\n1\\t=A2+1\\n')") == [["a", "b"], ["1", "=A2+1"]]
        assert run("M.markdownTableToGrid('| a | b |\\n|---|---|\\n| 1 | 2 |')") == [["a", "b"], ["1", "2"]]
        assert run("M.markdownTableToGrid('just text')") is None

    def test_export_uses_computed_values(self):
        values = f"M.evaluate({json.dumps([['x', 'y'], ['1', '=A2*2']])}, [])"
        assert run(f"M.toMarkdown({values})") == "| x | y |\n| --- | --- |\n| 1 | 2 |"
        assert run(f"M.toCsv({values})") == "x,y\n1,2"


class TestTextAndConditions:
    def test_text_and_numbers_join_with_the_ampersand(self):
        grid = [["10", "7"], ['="Government team won by " & (A1-B1) & " points"', ""]]
        assert texts(grid)[1][0] == "Government team won by 3 points"

    @pytest.mark.parametrize("formula, expected", [
        ('=IF(A1>B1, "Gov", "Opp")', "Gov"), ('=IF(A1<B1, "Gov", "Opp")', "Opp"), ('=IF(A1<B1, "Gov")', ""),
        ('=IF(AND(A1>5, B1<8), "both", "no")', "both"), ('=IF(OR(A1<5, B1<5), "x", "y")', "y"),
        ('=IF(NOT(A1=B1), "differ", "same")', "differ"), ("=A1>=10", "TRUE"), ("=A1<>10", "FALSE"),
        ('=IF(A1=10, "ten", "no")', "ten"), ('="a"="A"', "TRUE"),
    ])
    def test_conditions_and_comparisons(self, formula, expected):
        assert texts([["10", "7", formula]])[0][2] == expected

    def test_an_empty_cell_joins_as_nothing_and_text_in_a_condition_is_an_error(self):
        assert texts([["", '="[" & A1 & "]"']])[0][1] == "[]"
        assert texts([["x", '=IF(A1, 1, 2)']])[0][1] == "#VALUE!"

    def test_quoted_text_is_not_treated_as_references_when_rows_move(self):
        out = run("""M.insertRow({content: [['1'], ['="A1 is " & A1']], merges: [], align: {}, colors: {}}, 0)""")
        assert out["content"][2][0] == '="A1 is " & A2'

    def test_a_quote_inside_text_is_doubled(self):
        assert texts([['="say ""hi"""']])[0][0] == 'say "hi"'


def test_a_formula_comes_back_from_a_save_with_its_operators_unescaped():
    escaped = '="Call " &amp; "Ana" &amp; IF(1 &lt;&gt; 2, "!", "")'
    assert texts([[escaped]])[0][0] == "Call Ana!"
