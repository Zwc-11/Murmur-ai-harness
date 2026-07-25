"""Deterministic seed tasks for generator auditing."""

from __future__ import annotations

from envs.independent_evidence.schema import Case, TaskDefinition

TASKS = (
    TaskDefinition(
        task_id="classify_range",
        prompt="Classify a value as below, inside, or above the inclusive bounds.",
        source="""\
def solve(value, lower, upper):
    if value < lower:
        return "below"
    if value > upper:
        return "above"
    return "inside"
""",
        cases=tuple(
            Case(args)
            for args in ((-1, 0, 10), (0, 0, 10), (5, 0, 10), (10, 0, 10), (11, 0, 10))
        ),
        mutations=(
            "lower_boundary_inclusive",
            "upper_boundary_inclusive",
            "below_labeled_above",
            "above_labeled_below",
        ),
    ),
    TaskDefinition(
        task_id="discount_price",
        prompt="Apply a percentage discount and round the price to two decimals.",
        source="""\
def solve(price, percent):
    return round(price * (100 - percent) / 100, 2)
""",
        cases=tuple(
            Case(args)
            for args in (
                (0, 25),
                (100, 0),
                (100, 25),
                (19.99, 15),
                (3.5, 33),
            )
        ),
        mutations=(
            "discount_added",
            "floor_division",
            "percent_base_ten",
            "rounding_removed",
        ),
    ),
    TaskDefinition(
        task_id="normalize_slug",
        prompt="Normalize UTF-8 text by trimming, lowercasing, and replacing spaces with hyphens.",
        source="""\
def solve(text):
    encoded = text.encode("utf-8").decode("utf-8")
    return encoded.strip().lower().replace(" ", "-")
""",
        cases=tuple(
            Case((value,))
            for value in ("", "123", "hello", "Hello World", "trail ", " café ")
        ),
        mutations=(
            "strip_left_only",
            "uppercase_slug",
            "underscore_separator",
            "ascii_encoding",
        ),
    ),
    TaskDefinition(
        task_id="summarize_values",
        prompt="Return the minimum, maximum, sum, and count of non-empty values.",
        source="""\
def solve(values):
    if not values:
        return None
    return min(values), max(values), sum(values), len(values)
""",
        cases=tuple(
            Case((values,))
            for values in ([], [1], [2, 5], [-3, 4, 8], [1, 1, 1])
        ),
        mutations=("minimum_as_maximum", "maximum_as_minimum", "sum_as_length", "length_as_sum"),
    ),
    TaskDefinition(
        task_id="optional_value",
        prompt="Return the default for None; otherwise return the value as text.",
        source="""\
def solve(value, default):
    if value is None:
        return default
    return str(value)
""",
        cases=tuple(
            Case(args)
            for args in (
                (None, "missing"),
                (None, "None"),
                (3, "3"),
                (7, "missing"),
                (False, "missing"),
            )
        ),
        mutations=("none_check_inverted", "false_treated_as_none", "default_dropped"),
    ),
    TaskDefinition(
        task_id="select_values",
        prompt="Return the first non-negative value below the exclusive limit.",
        source="""\
def solve(values, limit):
    selected = [value for value in values if value >= 0 and value < limit]
    return selected[0] if selected else None
""",
        cases=tuple(
            Case(args)
            for args in (
                ([], 3),
                ([-1, 1], 3),
                ([0, 1], 3),
                ([3, 1], 3),
                ([1, 2], 3),
                ([-2, 5], 3),
            )
        ),
        mutations=(
            "zero_excluded",
            "limit_included",
            "bounds_use_or",
            "last_match_returned",
        ),
    ),
    TaskDefinition(
        task_id="copy_then_append",
        prompt="Append zero to a copy and return both the copy and untouched input.",
        source="""\
def solve(values):
    copied = values[:]
    if values:
        copied.append(0)
    return copied, values
""",
        cases=tuple(Case((values,)) for values in ([], [1], [1, 2], [-1])),
        mutations=("copy_aliases_input",),
    ),
)

TASK_BY_ID = {task.task_id: task for task in TASKS}
