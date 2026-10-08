"""Tests for the fetch_price job entry point (exit codes and per-symbol isolation)."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from shared.binance_vision import SYMBOL_START_MONTH, BinanceVisionError, DownloadError
from workers.fetch_price.main import main


def _run(side_effect: Callable[..., int] | BaseException) -> tuple[int, MagicMock]:
    with (
        patch("workers.fetch_price.main.SessionLocal") as session_cls,
        patch("workers.fetch_price.main.ingest_new_days", side_effect=side_effect) as ingest,
    ):
        session_cls.return_value.__enter__.return_value = MagicMock()
        return main(), ingest


def test_success_ingests_every_symbol_and_exits_zero() -> None:
    code, ingest = _run(lambda session, symbol: 1)

    assert code == 0
    assert [call.args[1] for call in ingest.call_args_list] == sorted(SYMBOL_START_MONTH)


def test_failure_exits_nonzero_logs_cause_and_still_tries_other_symbols(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def flaky(session: Any, symbol: str) -> int:
        if symbol == "BTCUSDT":
            raise DownloadError("both sources down")
        return 0

    code, ingest = _run(flaky)

    assert code == 1
    assert ingest.call_count == len(SYMBOL_START_MONTH)
    assert "both sources down" in caplog.text


def test_unexpected_error_exits_nonzero() -> None:
    code, _ = _run(RuntimeError("boom"))

    assert code == 1


def test_binance_error_exits_nonzero() -> None:
    code, _ = _run(BinanceVisionError("bad answer"))

    assert code == 1
