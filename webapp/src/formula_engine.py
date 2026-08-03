"""A small, purpose-built formula language for database columns (Phase 7
of the projects/tags rework) -- NOT a general expression language. Scoped
deliberately: arithmetic (+ - * / with parens and unary minus), plain
numbers, column references, and a fixed set of aggregate functions (SUM,
AVG, WEIGHTAVG, MIN, MAX, COUNT). No IF/comparisons/booleans, no
user-defined functions, no string operations. This covers the driving use
case (grade tracking -- "media aritmetica ponderata"/weighted average)
and ordinary per-row arithmetic (e.g. `grade * weight`) without building
a real language with all the surface area that implies. If a future need
outgrows this, it should be a deliberate decision to extend the grammar,
not something this module tries to guess in advance.

Two evaluation contexts, both going through the same grammar:

  - **Row formulas** (a `formula`-type column): bare identifiers resolve
    to *that row's own* value for the named column. `grade * weight`
    means "this row's grade times this row's weight."
  - **Summary formulas** (an optional per-column footer, any column type):
    no single "current row" exists, so bare identifiers are a formula
    error there -- only aggregate functions make sense, e.g.
    `WEIGHTAVG(grade, weight)` for a weighted-average final grade, or
    `AVG(grade)` for a plain mean.

Column references use bracket syntax `[Column Name]` (spaces allowed) or
a bare identifier when the name has no spaces/special characters --
`grade` and `[grade]` are equivalent, `[Final Grade]` is required for a
name with a space in it, since a bare identifier is a single token with
no whitespace.

Errors (unknown column, wrong arg count, division by zero, malformed
expression) never raise out to the caller -- `evaluate()` always returns
`(value, error)`, one of which is None, mirroring how this app already
treats a bad recurrence rule or a bad CalDAV response: degrade to "no
value," don't crash the page rendering a whole database over one bad
formula in one column.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

# --------------------------------------------------------------------- #
# Tokenizer
# --------------------------------------------------------------------- #


@dataclass
class Token:
    kind: str  # 'num' | 'ident' | 'op' | 'lparen' | 'rparen' | 'comma' | 'end'
    value: str


def tokenize(expr: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(expr)
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c == "[":
            j = expr.find("]", i + 1)
            if j == -1:
                raise FormulaError(f"unterminated '[' in column reference at position {i}")
            tokens.append(Token("ident", expr[i + 1 : j]))
            i = j + 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and expr[i + 1].isdigit()):
            j = i
            seen_dot = False
            while j < n and (expr[j].isdigit() or (expr[j] == "." and not seen_dot)):
                if expr[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(Token("num", expr[i:j]))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (expr[j].isalnum() or expr[j] in "_ "):
                # Bare identifiers may contain internal spaces too (e.g.
                # `total score`) as long as they're not adjacent to an
                # operator/paren -- greedily consume, trailing spaces are
                # trimmed below. This matches "column names are free text"
                # (both database_columns.name and this reference syntax).
                j += 1
            name = expr[i:j].rstrip()
            tokens.append(Token("ident", name))
            i += len(expr[i:j])
            continue
        if c in "+-*/":
            tokens.append(Token("op", c))
            i += 1
            continue
        if c == "(":
            tokens.append(Token("lparen", c))
            i += 1
            continue
        if c == ")":
            tokens.append(Token("rparen", c))
            i += 1
            continue
        if c == ",":
            tokens.append(Token("comma", c))
            i += 1
            continue
        raise FormulaError(f"unexpected character {c!r} at position {i}")
    tokens.append(Token("end", ""))
    return tokens


# --------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------- #


@dataclass
class Num:
    value: float


@dataclass
class ColumnRef:
    name: str


@dataclass
class Neg:
    expr: "Node"


@dataclass
class BinOp:
    op: str
    left: "Node"
    right: "Node"


@dataclass
class FuncCall:
    name: str
    args: list["Node"]


Node = Union[Num, ColumnRef, Neg, BinOp, FuncCall]

AGGREGATE_FUNCTIONS = {"SUM", "AVG", "MIN", "MAX", "COUNT", "WEIGHTAVG"}
_ARG_COUNTS = {"SUM": 1, "AVG": 1, "MIN": 1, "MAX": 1, "COUNT": 1, "WEIGHTAVG": 2}


class FormulaError(Exception):
    pass


class _Parser:
    """Recursive-descent parser for: expr := term (('+'|'-') term)*,
    term := factor (('*'|'/') factor)*, factor := NUM | funccall | '(' expr
    ')' | '-' factor | IDENT. Standard operator-precedence shape -- the
    only thing specific to this language is that a bare IDENT followed by
    '(' is a function call (must be one of AGGREGATE_FUNCTIONS), otherwise
    it's a column reference."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, kind: str) -> Token:
        tok = self._peek()
        if tok.kind != kind:
            raise FormulaError(f"expected {kind}, got {tok.kind} ({tok.value!r})")
        return self._advance()

    def parse(self) -> Node:
        node = self._expr()
        self._expect("end")
        return node

    def _expr(self) -> Node:
        node = self._term()
        while self._peek().kind == "op" and self._peek().value in "+-":
            op = self._advance().value
            node = BinOp(op, node, self._term())
        return node

    def _term(self) -> Node:
        node = self._factor()
        while self._peek().kind == "op" and self._peek().value in "*/":
            op = self._advance().value
            node = BinOp(op, node, self._factor())
        return node

    def _factor(self) -> Node:
        tok = self._peek()
        if tok.kind == "op" and tok.value == "-":
            self._advance()
            return Neg(self._factor())
        if tok.kind == "num":
            self._advance()
            return Num(float(tok.value))
        if tok.kind == "lparen":
            self._advance()
            node = self._expr()
            self._expect("rparen")
            return node
        if tok.kind == "ident":
            name = tok.value
            self._advance()
            upper = name.upper().strip()
            if upper in AGGREGATE_FUNCTIONS and self._peek().kind == "lparen":
                self._advance()
                args: list[Node] = []
                if self._peek().kind != "rparen":
                    args.append(self._expr())
                    while self._peek().kind == "comma":
                        self._advance()
                        args.append(self._expr())
                self._expect("rparen")
                expected = _ARG_COUNTS[upper]
                if len(args) != expected:
                    raise FormulaError(f"{upper} expects {expected} argument(s), got {len(args)}")
                return FuncCall(upper, args)
            return ColumnRef(name.strip())
        raise FormulaError(f"unexpected token {tok.kind} ({tok.value!r})")


def parse(expr: str) -> Node:
    return _Parser(tokenize(expr)).parse()


# --------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------- #


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _column_values(name: str, all_rows: list[dict]) -> list[float]:
    """Every numeric value in `name` across all_rows, skipping rows where
    it's missing/non-numeric -- aggregate functions ignore blanks rather
    than treating them as zero, so an ungraded assignment doesn't drag a
    weighted average toward zero just because it's not filled in yet."""
    out = []
    for row in all_rows:
        v = _as_float(row.get(name))
        if v is not None:
            out.append(v)
    return out


def _eval(node: Node, row: dict | None, all_rows: list[dict]) -> float:
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Neg):
        return -_eval(node.expr, row, all_rows)
    if isinstance(node, BinOp):
        left = _eval(node.left, row, all_rows)
        right = _eval(node.right, row, all_rows)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0:
                raise FormulaError("division by zero")
            return left / right
        raise FormulaError(f"unknown operator {node.op!r}")
    if isinstance(node, ColumnRef):
        if row is None:
            raise FormulaError(
                f"'{node.name}' is a bare column reference, only valid in a row formula -- "
                "a summary formula has no single row, use an aggregate function like SUM(...)"
            )
        value = _as_float(row.get(node.name))
        if value is None:
            raise FormulaError(f"column '{node.name}' has no numeric value in this row")
        return value
    if isinstance(node, FuncCall):
        if node.name == "WEIGHTAVG":
            value_ref, weight_ref = node.args
            if not isinstance(value_ref, ColumnRef) or not isinstance(weight_ref, ColumnRef):
                raise FormulaError("WEIGHTAVG's arguments must be plain column references")
            total_weight = 0.0
            total = 0.0
            for r in all_rows:
                v = _as_float(r.get(value_ref.name))
                w = _as_float(r.get(weight_ref.name))
                if v is not None and w is not None:
                    total += v * w
                    total_weight += w
            if total_weight == 0:
                raise FormulaError("WEIGHTAVG: total weight is zero")
            return total / total_weight
        # SUM/AVG/MIN/MAX/COUNT -- single column-reference argument.
        (arg,) = node.args
        if not isinstance(arg, ColumnRef):
            raise FormulaError(f"{node.name} expects a plain column reference, e.g. {node.name}(grade)")
        values = _column_values(arg.name, all_rows)
        if node.name == "COUNT":
            return float(len(values))
        if not values:
            raise FormulaError(f"{node.name}({arg.name}): no numeric values to aggregate")
        if node.name == "SUM":
            return sum(values)
        if node.name == "AVG":
            return sum(values) / len(values)
        if node.name == "MIN":
            return min(values)
        if node.name == "MAX":
            return max(values)
        raise FormulaError(f"unknown function {node.name!r}")
    raise FormulaError(f"unknown node type {type(node)!r}")


def evaluate(expr: str, row: dict | None, all_rows: list[dict]) -> tuple[float | None, str | None]:
    """Evaluates `expr` (a formula string) against `row` (the current
    row's column-name -> raw-value dict, or None for a summary formula)
    and `all_rows` (every row's column-name -> raw-value dict, for
    aggregate functions). Returns (value, error) -- exactly one is None.
    Never raises: a malformed formula, an unknown column, or a runtime
    error (division by zero, empty aggregate) all come back as an error
    string instead, so one bad formula can't take down the whole page."""
    if not expr or not expr.strip():
        return None, "empty formula"
    try:
        ast = parse(expr)
        return _eval(ast, row, all_rows), None
    except FormulaError as e:
        return None, str(e)
    except (ZeroDivisionError, RecursionError) as e:
        return None, str(e)
