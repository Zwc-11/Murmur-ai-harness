"""AST-level misconception mutations used by the episode generator."""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

NodePredicate = Callable[[ast.AST], bool]
NodeRewrite = Callable[[ast.AST], ast.AST]


class _FirstReplacement(ast.NodeTransformer):
    def __init__(self, predicate: NodePredicate, rewrite: NodeRewrite) -> None:
        self._predicate = predicate
        self._rewrite = rewrite
        self.changed = False

    def generic_visit(self, node: ast.AST) -> Any:
        if not self.changed and self._predicate(node):
            self.changed = True
            return ast.copy_location(self._rewrite(node), node)
        return super().generic_visit(node)


def _replace_first(source: str, predicate: NodePredicate, rewrite: NodeRewrite) -> str:
    tree = ast.parse(source)
    transformer = _FirstReplacement(predicate, rewrite)
    transformed = transformer.visit(tree)
    if not transformer.changed:
        raise ValueError("mutation target not found")
    ast.fix_missing_locations(transformed)
    return ast.unparse(transformed) + "\n"


def _comparison(before: type[ast.cmpop], after: type[ast.cmpop]) -> Callable[[str], str]:
    def apply(source: str) -> str:
        def rewrite(node: ast.AST) -> ast.AST:
            comparison = node
            assert isinstance(comparison, ast.Compare)
            comparison.ops[0] = after()
            return comparison

        return _replace_first(
            source,
            lambda node: isinstance(node, ast.Compare)
            and isinstance(node.ops[0], before),
            rewrite,
        )

    return apply


def _binary(before: type[ast.operator], after: type[ast.operator]) -> Callable[[str], str]:
    def apply(source: str) -> str:
        def rewrite(node: ast.AST) -> ast.AST:
            operation = node
            assert isinstance(operation, ast.BinOp)
            operation.op = after()
            return operation

        return _replace_first(
            source,
            lambda node: isinstance(node, ast.BinOp) and isinstance(node.op, before),
            rewrite,
        )

    return apply


def _boolean(before: type[ast.boolop], after: type[ast.boolop]) -> Callable[[str], str]:
    def apply(source: str) -> str:
        def rewrite(node: ast.AST) -> ast.AST:
            operation = node
            assert isinstance(operation, ast.BoolOp)
            operation.op = after()
            return operation

        return _replace_first(
            source,
            lambda node: isinstance(node, ast.BoolOp) and isinstance(node.op, before),
            rewrite,
        )

    return apply


def _call(before: str, after: str) -> Callable[[str], str]:
    def apply(source: str) -> str:
        def rewrite(node: ast.AST) -> ast.AST:
            call = node
            assert isinstance(call, ast.Call)
            function = call.func
            if isinstance(function, ast.Name):
                function.id = after
            else:
                assert isinstance(function, ast.Attribute)
                function.attr = after
            return call

        return _replace_first(
            source,
            lambda node: isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id == before
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == before
            ),
            rewrite,
        )

    return apply


def _constant(before: object, after: object) -> Callable[[str], str]:
    return lambda source: _replace_first(
        source,
        lambda node: isinstance(node, ast.Constant) and node.value == before,
        lambda node: ast.Constant(after),
    )


def _return_name(before: str, replacement: ast.expr) -> Callable[[str], str]:
    return lambda source: _replace_first(
        source,
        lambda node: isinstance(node, ast.Return)
        and isinstance(node.value, ast.Name)
        and node.value.id == before,
        lambda node: ast.Return(value=replacement),
    )


def _call_to_first_argument(name: str) -> Callable[[str], str]:
    return lambda source: _replace_first(
        source,
        lambda node: isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name,
        lambda node: node.args[0],  # type: ignore[attr-defined]
    )


def _subscript_index(after: int) -> Callable[[str], str]:
    return lambda source: _replace_first(
        source,
        lambda node: isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == 0,
        lambda node: ast.Subscript(
            value=node.value,  # type: ignore[attr-defined]
            slice=ast.Constant(after),
            ctx=ast.Load(),
        ),
    )


def _alias_slice(source: str) -> str:
    return _replace_first(
        source,
        lambda node: isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice),
        lambda node: ast.Name(id=node.value.id, ctx=ast.Load()),  # type: ignore[attr-defined]
    )


@dataclass(frozen=True, slots=True)
class Mutation:
    name: str
    family: str
    task_id: str
    apply: Callable[[str], str]


MUTATIONS = (
    Mutation(
        "lower_boundary_inclusive",
        "boundary_off_by_one",
        "classify_range",
        _comparison(ast.Lt, ast.LtE),
    ),
    Mutation(
        "upper_boundary_inclusive",
        "boundary_off_by_one",
        "classify_range",
        _comparison(ast.Gt, ast.GtE),
    ),
    Mutation(
        "below_labeled_above",
        "wrong_label",
        "classify_range",
        _constant("below", "above"),
    ),
    Mutation(
        "above_labeled_below",
        "wrong_label",
        "classify_range",
        _constant("above", "below"),
    ),
    Mutation("discount_added", "arithmetic_direction", "discount_price", _binary(ast.Sub, ast.Add)),
    Mutation(
        "floor_division",
        "rounding_precision",
        "discount_price",
        _binary(ast.Div, ast.FloorDiv),
    ),
    Mutation("percent_base_ten", "unit_confusion", "discount_price", _constant(100, 10)),
    Mutation(
        "rounding_removed",
        "rounding_precision",
        "discount_price",
        _call_to_first_argument("round"),
    ),
    Mutation("strip_left_only", "trim_policy", "normalize_slug", _call("strip", "lstrip")),
    Mutation("uppercase_slug", "casing", "normalize_slug", _call("lower", "upper")),
    Mutation("underscore_separator", "separator", "normalize_slug", _constant("-", "_")),
    Mutation("ascii_encoding", "encoding", "normalize_slug", _constant("utf-8", "ascii")),
    Mutation(
        "minimum_as_maximum",
        "aggregation_selection",
        "summarize_values",
        _call("min", "max"),
    ),
    Mutation(
        "maximum_as_minimum",
        "aggregation_selection",
        "summarize_values",
        _call("max", "min"),
    ),
    Mutation("sum_as_length", "aggregation_selection", "summarize_values", _call("sum", "len")),
    Mutation("length_as_sum", "aggregation_selection", "summarize_values", _call("len", "sum")),
    Mutation(
        "none_check_inverted",
        "none_handling",
        "optional_value",
        _comparison(ast.Is, ast.IsNot),
    ),
    Mutation("false_treated_as_none", "none_handling", "optional_value", _constant(None, False)),
    Mutation(
        "default_dropped",
        "none_handling",
        "optional_value",
        _return_name("default", ast.Constant("")),
    ),
    Mutation("zero_excluded", "boundary_off_by_one", "select_values", _comparison(ast.GtE, ast.Gt)),
    Mutation(
        "limit_included",
        "boundary_off_by_one",
        "select_values",
        _comparison(ast.Lt, ast.LtE),
    ),
    Mutation("bounds_use_or", "boolean_logic", "select_values", _boolean(ast.And, ast.Or)),
    Mutation("last_match_returned", "selection_order", "select_values", _subscript_index(-1)),
    Mutation("copy_aliases_input", "aliasing", "copy_then_append", _alias_slice),
)

MUTATION_BY_NAME = {mutation.name: mutation for mutation in MUTATIONS}
