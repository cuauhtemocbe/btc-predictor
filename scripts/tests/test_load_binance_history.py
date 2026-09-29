"""Tests for the ``scripts/load_binance_history.py`` command-line entry point."""

import pytest

from scripts import load_binance_history
from shared.binance_vision import (
    ChecksumMismatchError,
    HistoryValidationError,
    HttpStatusError,
)


@pytest.fixture
def calls(monkeypatch):
    """Replace loader collaborators with recorders; the DB is never touched."""
    recorded = {"load": [], "validate": []}
    monkeypatch.setattr(
        load_binance_history,
        "load_history",
        lambda session, symbol: recorded["load"].append(symbol) or 5,
    )
    monkeypatch.setattr(
        load_binance_history,
        "validate_history",
        lambda session, symbol: recorded["validate"].append(symbol),
    )
    monkeypatch.setattr(load_binance_history, "SessionLocal", lambda: _FakeSession())
    return recorded


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_loads_and_validates_every_symbol_by_default(calls):
    assert load_binance_history.main([]) == 0

    assert calls["load"] == ["BTCUSDT", "PAXGUSDT"]
    assert calls["validate"] == ["BTCUSDT", "PAXGUSDT"]


def test_symbols_option_limits_the_load(calls):
    assert load_binance_history.main(["--symbols", "PAXGUSDT"]) == 0

    assert calls["load"] == ["PAXGUSDT"]


def test_check_only_probes_the_host_and_writes_nothing(calls, monkeypatch):
    monkeypatch.setattr(
        load_binance_history, "check_reachability", lambda: "https://x/y.CHECKSUM"
    )

    assert load_binance_history.main(["--check"]) == 0

    assert calls["load"] == []


def test_blocked_host_fails_the_check(monkeypatch):
    def blocked():
        raise HttpStatusError("https://x/y", 451)

    monkeypatch.setattr(load_binance_history, "check_reachability", blocked)

    assert load_binance_history.main(["--check"]) == 1


def test_load_error_gives_exit_code_1(monkeypatch):
    def failing(session, symbol):
        raise ChecksumMismatchError("bad checksum for BTCUSDT-1d-2025-01.zip")

    monkeypatch.setattr(load_binance_history, "load_history", failing)
    monkeypatch.setattr(load_binance_history, "SessionLocal", lambda: _FakeSession())

    assert load_binance_history.main([]) == 1


def test_validation_error_gives_exit_code_1(calls, monkeypatch):
    def invalid(session, symbol):
        raise HistoryValidationError(symbol, [], [])

    monkeypatch.setattr(load_binance_history, "validate_history", invalid)

    assert load_binance_history.main([]) == 1
