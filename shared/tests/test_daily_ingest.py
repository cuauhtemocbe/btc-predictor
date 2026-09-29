"""
Gherkin scenario tests for #102: daily ingestion of closed bars from Binance.

HTTP is replaced by an in-memory ``Fetcher`` keyed by URL.
"""

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select

from shared.binance_vision import (
    REST_SOURCE,
    SOURCE,
    BinanceVisionError,
    ChecksumMismatchError,
    DownloadError,
    HttpStatusError,
    NoHistoryError,
    daily_file_url,
    fetch_day,
    fetch_day_rest,
    ingest_new_days,
)
from shared.db.models import Price

TODAY = date(2026, 3, 10)
SYMBOL = "BTCUSDT"


def _epoch_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def _kline(day: date, volume: str = "12.5") -> list[Any]:
    return [
        _epoch_ms(day) * 1000,
        "100",
        "110",
        "90",
        "105",
        volume,
        0,
        "0",
        0,
        "0",
        "0",
        "0",
    ]


def _zip_bytes(day: date, volume: str = "12.5") -> bytes:
    row = ",".join(str(field) for field in _kline(day, volume))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("data.csv", row + "\n")
    return buffer.getvalue()


class FakeBinance:
    """In-memory data.binance.vision and REST endpoint; records every request."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.rest_days: set[date] = set()
        self.down = False
        self.requests: list[str] = []

    def publish_file(
        self, day: date, symbol: str = SYMBOL, checksum: str | None = None
    ):
        url = daily_file_url(symbol, day)
        archive = _zip_bytes(day)
        self.files[url] = archive
        digest = checksum or hashlib.sha256(archive).hexdigest()
        self.files[url + ".CHECKSUM"] = f"{digest}  x.zip\n".encode()

    def __call__(self, url: str) -> bytes:
        self.requests.append(url)
        if self.down:
            raise DownloadError(f"Could not download {url} after 3 attempts: refused")
        if "data-api.binance.vision" in url:
            start = int(url.split("startTime=")[1].split("&")[0])
            day = datetime.fromtimestamp(start / 1000, tz=UTC).date()
            klines = [_kline(day)] if day in self.rest_days else []
            return json.dumps(klines).encode()
        if url not in self.files:
            raise HttpStatusError(url, 404)
        return self.files[url]


@pytest.fixture
def binance():
    return FakeBinance()


def _seed(db_session, day: date, symbol: str = SYMBOL):
    db_session.add(
        Price(
            symbol=symbol,
            timestamp=datetime(day.year, day.month, day.day, tzinfo=UTC),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=Decimal("1"),
            source=SOURCE,
        )
    )
    db_session.commit()


def _days(db_session, symbol: str = SYMBOL) -> list[date]:
    stamps = db_session.execute(
        select(Price.timestamp).where(Price.symbol == symbol).order_by(Price.timestamp)
    ).scalars()
    return [stamp.astimezone(UTC).date() for stamp in stamps]


def _count(db_session) -> int:
    return int(db_session.execute(select(func.count()).select_from(Price)).scalar_one())


class TestClosedBarOfYesterday:
    def test_yesterday_is_ingested_with_volume(self, db_session, binance):
        """Scenario: The closed daily bar of yesterday is ingested."""
        yesterday = TODAY - timedelta(days=1)
        _seed(db_session, TODAY - timedelta(days=2))
        binance.publish_file(yesterday)

        inserted = ingest_new_days(db_session, SYMBOL, TODAY, binance)

        assert inserted == 1
        assert _days(db_session)[-1] == yesterday
        row = (
            db_session.execute(select(Price).order_by(Price.timestamp.desc()))
            .scalars()
            .first()
        )
        assert row is not None
        assert row.volume == Decimal("12.5")
        assert row.source == SOURCE

    def test_every_symbol_gets_its_own_bar(self, db_session, binance):
        """Scenario: ... exactly one new bar ... per configured symbol."""
        yesterday = TODAY - timedelta(days=1)
        for symbol in ("BTCUSDT", "PAXGUSDT"):
            _seed(db_session, TODAY - timedelta(days=2), symbol)
            binance.publish_file(yesterday, symbol)

        for symbol in ("BTCUSDT", "PAXGUSDT"):
            assert ingest_new_days(db_session, symbol, TODAY, binance) == 1

        assert _days(db_session, "BTCUSDT")[-1] == yesterday
        assert _days(db_session, "PAXGUSDT")[-1] == yesterday


class TestOpenDayNeverStored:
    @pytest.mark.parametrize("hour", [0, 6, 23])
    def test_no_bar_dated_today(self, db_session, binance, hour, monkeypatch):
        """Scenario: The current, still-open day is never stored."""
        _seed(db_session, TODAY - timedelta(days=3))
        for offset in (1, 2):
            binance.publish_file(TODAY - timedelta(days=offset))
        binance.publish_file(
            TODAY
        )  # even if Binance exposed it, it must not be requested

        class _Now(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 3, 10, hour, 30, tzinfo=tz)

        monkeypatch.setattr("shared.binance_vision.datetime", _Now)
        ingest_new_days(db_session, SYMBOL, fetch=binance)

        assert TODAY not in _days(db_session)
        assert daily_file_url(SYMBOL, TODAY) not in binance.requests


class TestRestFallback:
    def test_falls_back_when_file_is_404(self, db_session, binance):
        """Scenario: Falls back to REST when the daily file is not published yet."""
        yesterday = TODAY - timedelta(days=1)
        _seed(db_session, TODAY - timedelta(days=2))
        binance.rest_days.add(yesterday)

        assert ingest_new_days(db_session, SYMBOL, TODAY, binance) == 1

        row = (
            db_session.execute(select(Price).order_by(Price.timestamp.desc()))
            .scalars()
            .first()
        )
        assert row is not None
        assert row.timestamp.astimezone(UTC).date() == yesterday
        assert row.source == REST_SOURCE
        assert row.volume == Decimal("12.5")

    def test_checksum_mismatch_does_not_fall_back(self, binance):
        """A published but corrupt file is a real error, not a source switch."""
        day = TODAY - timedelta(days=1)
        binance.publish_file(day, checksum="0" * 64)
        binance.rest_days.add(day)

        with pytest.raises(ChecksumMismatchError):
            fetch_day(SYMBOL, day, binance)
        assert not any("data-api" in url for url in binance.requests)

    def test_rest_ignores_a_bar_of_another_day(self):
        day = TODAY - timedelta(days=1)
        other = json.dumps([_kline(day + timedelta(days=1))]).encode()

        assert fetch_day_rest(SYMBOL, day, lambda url: other) == []

    def test_rest_rejects_a_malformed_answer(self):
        with pytest.raises(BinanceVisionError, match="Unexpected klines answer"):
            fetch_day_rest(SYMBOL, TODAY, lambda url: b'{"code": -1121}')


class TestIdempotence:
    def test_second_run_changes_nothing(self, db_session, binance):
        """Scenario: Running the job twice is idempotent."""
        _seed(db_session, TODAY - timedelta(days=2))
        binance.publish_file(TODAY - timedelta(days=1))
        ingest_new_days(db_session, SYMBOL, TODAY, binance)
        before = _count(db_session)

        assert ingest_new_days(db_session, SYMBOL, TODAY, binance) == 0

        assert _count(db_session) == before


class TestBackfill:
    def test_missed_days_are_stored(self, db_session, binance):
        """Scenario: A missed day is backfilled on the next run."""
        _seed(db_session, TODAY - timedelta(days=3))
        for offset in (1, 2):
            binance.publish_file(TODAY - timedelta(days=offset))

        assert ingest_new_days(db_session, SYMBOL, TODAY, binance) == 2

        assert _days(db_session) == [
            TODAY - timedelta(days=offset) for offset in (3, 2, 1)
        ]


class TestFailures:
    def test_both_sources_down_raises(self, db_session, binance):
        """Scenario: Both sources unavailable fails the job visibly."""
        _seed(db_session, TODAY - timedelta(days=2))
        binance.down = True

        with pytest.raises(DownloadError):
            ingest_new_days(db_session, SYMBOL, TODAY, binance)

    def test_missing_day_on_both_sources_raises(self, db_session, binance):
        _seed(db_session, TODAY - timedelta(days=2))

        with pytest.raises(BinanceVisionError, match="no bar returned"):
            ingest_new_days(db_session, SYMBOL, TODAY, binance)

    def test_symbol_without_history_raises(self, db_session, binance):
        with pytest.raises(NoHistoryError, match="load_binance_history"):
            ingest_new_days(db_session, SYMBOL, TODAY, binance)
