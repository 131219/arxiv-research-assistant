from datetime import datetime
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "lambda"
    / "manifest_parser"
    / "lambda_function.py"
)

spec = importlib.util.spec_from_file_location(
    "manifest_parser_lambda",
    MODULE_PATH,
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

resolve_target_month = module.resolve_target_month


def test_explicit_year_and_month_are_preserved():
    assert resolve_target_month(
        {
            "year": 2026,
            "month": 6,
        }
    ) == (2026, 6)


def test_explicit_year_and_month_accept_strings():
    assert resolve_target_month(
        {
            "year": "2026",
            "month": "8",
        }
    ) == (2026, 8)


def test_only_year_is_rejected():
    with pytest.raises(
        ValueError,
        match="year and month must either both be provided or both be omitted",
    ):
        resolve_target_month(
            {
                "year": 2026,
            }
        )


def test_only_month_is_rejected():
    with pytest.raises(
        ValueError,
        match="year and month must either both be provided or both be omitted",
    ):
        resolve_target_month(
            {
                "month": 6,
            }
        )


def test_invalid_month_is_rejected():
    with pytest.raises(
        ValueError,
        match="month must be between 1 and 12",
    ):
        resolve_target_month(
            {
                "year": 2026,
                "month": 13,
            }
        )


def test_scheduler_uses_previous_month():
    now = datetime.fromisoformat(
        "2026-09-01T09:00:00+00:00"
    )

    assert resolve_target_month({}, now=now) == (2026, 8)


def test_scheduler_handles_january_year_rollover():
    now = datetime.fromisoformat(
        "2027-01-01T10:00:00+00:00"
    )

    assert resolve_target_month({}, now=now) == (2026, 12)
