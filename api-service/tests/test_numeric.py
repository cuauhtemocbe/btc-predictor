from decimal import Decimal

import pytest

from api.numeric import required_float


def test_required_float_converts_a_decimal() -> None:
    assert required_float(Decimal("12.50"), "error_abs") == 12.5


def test_required_float_keeps_a_zero_value() -> None:
    assert required_float(Decimal("0"), "pnl_simulated") == 0.0


def test_required_float_names_the_null_column() -> None:
    with pytest.raises(ValueError, match="error_pct is NULL"):
        required_float(None, "error_pct")
