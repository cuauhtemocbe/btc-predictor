"""
Gherkin scenario tests for #101: load historical daily prices from
data.binance.vision.

HTTP is replaced by an in-memory ``Fetcher``. The reachability scenario is a
manual check from the Railway environment (``--check`` in the loader script);
its logic is unit-tested here with a fake host.
"""

import hashlib
import io
import urllib.error
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.message import Message

import pytest
from sqlalchemy import func, select

from shared.binance_vision import (
    ChecksumMismatchError,
    CorruptArchiveError,
    DownloadError,
    HistoryValidationError,
    HttpStatusError,
    MonthFileNotFoundError,
    check_reachability,
    fetch_month,
    http_get,
    insert_prices,
    last_closed_month,
    load_history,
    month_file_url,
    months_between,
    parse_klines_csv,
    parse_open_time,
    validate_history,
)
from shared.db.models import Price

DAY_MS = 86_400_000


def _epoch_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def _csv_for_month(year: int, month: int, volume: str = "12.5") -> str:
    """One kline row per calendar day, in ms before 2025 and µs from 2025."""
    day = date(year, month, 1)
    lines = []
    while day.month == month:
        open_time = _epoch_ms(day)
        if year >= 2025:
            open_time *= 1000
        close = 100 + day.toordinal() % 50
        prices = f"{close},{close + 5},{close - 5},{close + 1}"
        lines.append(f"{open_time},{prices},{volume},0,0,0,0,0,0")
        day += timedelta(days=1)
    return "\n".join(lines) + "\n"


def _zip_bytes(csv_text: str, name: str = "data.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, csv_text)
    return buffer.getvalue()


class FakeBinanceVision:
    """In-memory data.binance.vision keyed by URL; records every request."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.requests: list[str] = []

    def add_month(
        self, symbol, year, month, csv_text=None, archive=None, checksum=None
    ):
        url = month_file_url(symbol, year, month)
        archive = archive or _zip_bytes(csv_text or _csv_for_month(year, month))
        self.files[url] = archive
        digest = checksum or hashlib.sha256(archive).hexdigest()
        self.files[url + ".CHECKSUM"] = f"{digest}  {url.rsplit('/', 1)[1]}\n".encode()

    def add_range(self, symbol, start, end):
        for year, month in months_between(start, end):
            self.add_month(symbol, year, month)

    def __call__(self, url: str) -> bytes:
        self.requests.append(url)
        if url not in self.files:
            raise HttpStatusError(url, 404)
        return self.files[url]


@pytest.fixture
def vision():
    return FakeBinanceVision()


def _count(db_session, symbol=None) -> int:
    query = select(func.count()).select_from(Price)
    if symbol:
        query = query.where(Price.symbol == symbol)
    return int(db_session.execute(query).scalar_one())


class TestTimestampParsing:
    """Scenario Outline: ms and µs timestamps map to the same UTC date."""

    @pytest.mark.parametrize(
        ("open_time", "utc_date"),
        [
            (1500000000000, date(2017, 7, 14)),
            (1748736000000000, date(2025, 6, 1)),
        ],
    )
    def test_open_time_maps_to_midnight_utc(self, open_time, utc_date):
        assert parse_open_time(open_time) == datetime(
            utc_date.year, utc_date.month, utc_date.day, tzinfo=UTC
        )

    def test_same_instant_in_ms_and_us_gives_same_timestamp(self):
        millis = 1748736000000
        assert parse_open_time(millis) == parse_open_time(millis * 1000)


class TestFullHistoryLoad:
    """Scenario: Full history of BTC loads without gaps."""

    def test_every_day_has_exactly_one_row_with_volume(self, db_session, vision):
        vision.add_range("BTCUSDT", (2024, 11), (2025, 2))

        load_history(
            db_session,
            "BTCUSDT",
            today=date(2025, 3, 15),
            fetch=vision,
            start_month=(2024, 11),
        )

        rows = (
            db_session.execute(
                select(Price).where(Price.symbol == "BTCUSDT").order_by(Price.timestamp)
            )
            .scalars()
            .all()
        )
        days = [row.timestamp.astimezone(UTC).date() for row in rows]
        expected_days = (date(2025, 2, 28) - date(2024, 11, 1)).days + 1
        assert len(days) == expected_days == len(set(days))
        assert days[0] == date(2024, 11, 1)
        assert days[-1] == date(2025, 2, 28)
        assert all(row.volume > 0 for row in rows)
        assert {row.source for row in rows} == {"binance_vision"}
        validate_history(db_session, "BTCUSDT")  # no gaps

    def test_stops_at_last_closed_month(self, db_session, vision):
        vision.add_range("BTCUSDT", (2025, 1), (2025, 3))

        load_history(
            db_session,
            "BTCUSDT",
            today=date(2025, 3, 10),
            fetch=vision,
            start_month=(2025, 1),
        )

        requested = {url for url in vision.requests if not url.endswith(".CHECKSUM")}
        assert month_file_url("BTCUSDT", 2025, 3) not in requested
        assert month_file_url("BTCUSDT", 2025, 2) in requested

    def test_unsupported_symbol_is_rejected(self, db_session, vision):
        with pytest.raises(ValueError, match="Unsupported symbol"):
            load_history(db_session, "ETHUSDT", fetch=vision)


class TestChecksumVerification:
    """Scenario: A file with a wrong checksum is rejected."""

    def test_wrong_checksum_inserts_nothing_and_names_the_file(
        self, db_session, vision
    ):
        vision.add_month("BTCUSDT", 2025, 1, checksum="0" * 64)

        with pytest.raises(ChecksumMismatchError) as error:
            load_history(
                db_session,
                "BTCUSDT",
                today=date(2025, 2, 10),
                fetch=vision,
                start_month=(2025, 1),
            )

        assert "BTCUSDT-1d-2025-01.zip" in str(error.value)
        assert _count(db_session) == 0

    def test_bad_month_stops_load_but_keeps_earlier_months(self, db_session, vision):
        vision.add_month("BTCUSDT", 2024, 12)
        vision.add_month("BTCUSDT", 2025, 1, checksum="f" * 64)

        with pytest.raises(ChecksumMismatchError):
            load_history(
                db_session,
                "BTCUSDT",
                today=date(2025, 2, 10),
                fetch=vision,
                start_month=(2024, 12),
            )

        assert _count(db_session, "BTCUSDT") == 31  # December only


class TestMissingAndCorruptFiles:
    """ZOMBIES: a missing month or a corrupt zip stops the load with a clear error."""

    def test_missing_month_file_raises_clear_error(self, db_session, vision):
        vision.add_month("BTCUSDT", 2025, 2)  # January is missing, February is last
        with pytest.raises(MonthFileNotFoundError, match="BTCUSDT-1d-2025-01.zip"):
            load_history(
                db_session,
                "BTCUSDT",
                today=date(2025, 3, 10),
                fetch=vision,
                start_month=(2025, 1),
            )
        assert _count(db_session) == 0

    def test_last_closed_month_not_published_yet_is_skipped(self, db_session, vision):
        vision.add_month("BTCUSDT", 2025, 1)  # February is not published yet

        inserted = load_history(
            db_session,
            "BTCUSDT",
            today=date(2025, 3, 2),
            fetch=vision,
            start_month=(2025, 1),
        )

        assert inserted == _count(db_session, "BTCUSDT") == 31

    def test_missing_checksum_file_raises_clear_error(self, vision):
        vision.add_month("BTCUSDT", 2025, 1)
        del vision.files[month_file_url("BTCUSDT", 2025, 1) + ".CHECKSUM"]

        with pytest.raises(MonthFileNotFoundError, match="CHECKSUM"):
            fetch_month("BTCUSDT", 2025, 1, vision)

    def test_blocked_host_surfaces_the_http_status(self):
        def blocked(url):
            raise HttpStatusError(url, 451)

        with pytest.raises(HttpStatusError) as error:
            fetch_month("BTCUSDT", 2025, 1, blocked)
        assert error.value.status == 451

    def test_corrupt_zip_raises_clear_error(self, db_session, vision):
        vision.add_month("BTCUSDT", 2025, 1, archive=b"this is not a zip")

        with pytest.raises(CorruptArchiveError, match="BTCUSDT-1d-2025-01.zip"):
            load_history(
                db_session,
                "BTCUSDT",
                today=date(2025, 2, 10),
                fetch=vision,
                start_month=(2025, 1),
            )
        assert _count(db_session) == 0

    def test_zip_with_several_files_is_corrupt(self, vision):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("a.csv", _csv_for_month(2025, 1))
            bundle.writestr("b.csv", _csv_for_month(2025, 1))
        vision.add_month("BTCUSDT", 2025, 1, archive=buffer.getvalue())

        with pytest.raises(CorruptArchiveError, match="expected 1"):
            fetch_month("BTCUSDT", 2025, 1, vision)


class TestIdempotentLoad:
    """Scenario: Loading twice does not duplicate rows."""

    def test_second_load_leaves_row_count_unchanged(self, db_session, vision):
        vision.add_range("BTCUSDT", (2025, 1), (2025, 2))
        kwargs = {"today": date(2025, 3, 5), "fetch": vision, "start_month": (2025, 1)}

        first = load_history(db_session, "BTCUSDT", **kwargs)
        count_after_first = _count(db_session, "BTCUSDT")
        second = load_history(db_session, "BTCUSDT", **kwargs)

        assert first == count_after_first == 31 + 28
        assert second == 0
        assert _count(db_session, "BTCUSDT") == count_after_first


class TestGoldSymbol:
    """Scenario: Gold history loads under its own symbol."""

    def test_paxg_rows_use_own_symbol_and_leave_btc_untouched(self, db_session, vision):
        vision.add_range("BTCUSDT", (2020, 8), (2020, 9))
        vision.add_range("PAXGUSDT", (2020, 8), (2020, 9))
        today = date(2020, 10, 5)

        load_history(
            db_session, "BTCUSDT", today=today, fetch=vision, start_month=(2020, 8)
        )
        btc_before = _count(db_session, "BTCUSDT")
        load_history(db_session, "PAXGUSDT", today=today, fetch=vision)

        first_paxg = db_session.execute(
            select(func.min(Price.timestamp)).where(Price.symbol == "PAXGUSDT")
        ).scalar_one()
        assert first_paxg.astimezone(UTC).date() == date(2020, 8, 1)
        assert _count(db_session, "PAXGUSDT") == 31 + 30
        assert _count(db_session, "BTCUSDT") == btc_before

    def test_default_start_month_per_symbol(self, db_session, vision):
        load_history_calls = []

        def spy(url):
            load_history_calls.append(url)
            return vision(url)

        with pytest.raises(MonthFileNotFoundError):
            load_history(db_session, "PAXGUSDT", today=date(2021, 1, 5), fetch=spy)
        assert load_history_calls[0] == month_file_url("PAXGUSDT", 2020, 8)


class TestContinuityValidation:
    """Scenario: A gap in the loaded series is detected."""

    def _load_with_gap(self, db_session, gap: date):
        csv_lines = [
            line
            for line in _csv_for_month(2024, 3).splitlines()
            if int(line.split(",")[0]) != _epoch_ms(gap)
        ]
        vision = FakeBinanceVision()
        vision.add_month("BTCUSDT", 2024, 3, csv_text="\n".join(csv_lines) + "\n")
        load_history(
            db_session,
            "BTCUSDT",
            today=date(2024, 4, 5),
            fetch=vision,
            start_month=(2024, 3),
        )

    def test_missing_day_is_reported(self, db_session):
        self._load_with_gap(db_session, date(2024, 3, 10))

        with pytest.raises(HistoryValidationError) as error:
            validate_history(db_session, "BTCUSDT")

        assert error.value.missing_days == [date(2024, 3, 10)]
        assert "2024-03-10" in str(error.value)

    def test_zero_volume_day_is_reported(self, db_session, vision):
        csv_text = _csv_for_month(2024, 3).replace(",12.5,", ",0,", 1)
        vision.add_month("BTCUSDT", 2024, 3, csv_text=csv_text)
        load_history(
            db_session,
            "BTCUSDT",
            today=date(2024, 4, 5),
            fetch=vision,
            start_month=(2024, 3),
        )

        with pytest.raises(HistoryValidationError) as error:
            validate_history(db_session, "BTCUSDT")

        assert error.value.zero_volume_days == [date(2024, 3, 1)]

    def test_empty_series_is_valid(self, db_session):
        validate_history(db_session, "BTCUSDT")

    def test_rows_from_other_sources_are_ignored(self, db_session, vision):
        vision.add_month("BTCUSDT", 2024, 3)
        load_history(
            db_session,
            "BTCUSDT",
            today=date(2024, 4, 5),
            fetch=vision,
            start_month=(2024, 3),
        )
        db_session.add(
            Price(
                symbol="BTCUSDT",
                timestamp=datetime(2024, 3, 1, 4, tzinfo=UTC),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=0,
                source="coingecko",
            )
        )
        db_session.commit()

        validate_history(db_session, "BTCUSDT")  # zero-volume foreign row ignored

    def test_validation_is_per_symbol(self, db_session):
        self._load_with_gap(db_session, date(2024, 3, 10))
        validate_history(db_session, "PAXGUSDT")  # nothing loaded for it


class TestReachability:
    """Scenario: Reachability from the deployment environment is verified.

    The real check runs on Railway (``--check``); here the decision logic is
    tested against a fake host.
    """

    def test_reachable_host_returns_the_requested_url(self, vision):
        url = month_file_url("BTCUSDT", 2025, 5) + ".CHECKSUM"
        vision.files[url] = b"abc  file.zip"

        assert check_reachability(vision, today=date(2025, 6, 20)) == url

    @pytest.mark.parametrize("status", [451, 403])
    def test_blocked_host_raises_with_status(self, status):
        def blocked(url):
            raise HttpStatusError(url, status)

        with pytest.raises(HttpStatusError) as error:
            check_reachability(blocked, today=date(2025, 6, 20))
        assert error.value.status == status


class TestCalendarHelpers:
    @pytest.mark.parametrize(
        ("today", "expected"),
        [
            (date(2025, 3, 10), (2025, 2)),
            (date(2025, 1, 1), (2024, 12)),
            (date(2025, 3, 1), (2025, 2)),
        ],
    )
    def test_last_closed_month(self, today, expected):
        assert last_closed_month(today) == expected

    def test_months_between_crosses_year_boundary(self):
        assert months_between((2024, 11), (2025, 2)) == [
            (2024, 11),
            (2024, 12),
            (2025, 1),
            (2025, 2),
        ]

    def test_months_between_is_empty_when_start_is_after_end(self):
        assert months_between((2025, 3), (2025, 2)) == []


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"payload"


class TestHttpGet:
    """Transient network failures are retried; final answers are not."""

    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        self.pauses: list[float] = []
        monkeypatch.setattr("time.sleep", self.pauses.append)

    def test_returns_the_response_body(self, monkeypatch):
        monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout: _Response())

        assert http_get("https://example.test/file") == b"payload"

    @pytest.mark.parametrize("status", [404, 451])
    def test_client_errors_are_final_and_not_retried(self, monkeypatch, status):
        calls = []

        def failing(url, timeout):
            calls.append(url)
            raise urllib.error.HTTPError(url, status, "err", Message(), None)

        monkeypatch.setattr("urllib.request.urlopen", failing)

        with pytest.raises(HttpStatusError) as error:
            http_get("https://example.test/file")
        assert error.value.status == status
        assert len(calls) == 1

    def test_timeout_is_retried_and_then_succeeds(self, monkeypatch):
        outcomes = iter(
            [urllib.error.URLError("handshake timed out"), TimeoutError(), _Response()]
        )

        def flaky(url, timeout):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr("urllib.request.urlopen", flaky)

        assert http_get("https://example.test/file") == b"payload"
        assert self.pauses == [2.0, 4.0]

    def test_server_error_is_retried(self, monkeypatch):
        outcomes = iter(
            [urllib.error.HTTPError("u", 503, "busy", Message(), None), _Response()]
        )

        def flaky(url, timeout):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr("urllib.request.urlopen", flaky)

        assert http_get("https://example.test/file") == b"payload"

    def test_gives_up_after_every_attempt_with_a_clear_error(self, monkeypatch):
        def down(url, timeout):
            raise urllib.error.URLError("handshake timed out")

        monkeypatch.setattr("urllib.request.urlopen", down)

        with pytest.raises(DownloadError, match="after 3 attempts.*handshake"):
            http_get("https://example.test/file")
        assert len(self.pauses) == 2  # no pause after the last attempt


class TestParsingEdgeCases:
    def test_blank_lines_are_ignored(self):
        csv_text = "\n1500000000000,1,2,0.5,1.5,10,0,0,0,0,0,0\n\n"

        rows = parse_klines_csv(csv_text, "BTCUSDT")

        assert len(rows) == 1
        assert rows[0]["close"] == Decimal("1.5")

    def test_inserting_no_rows_is_a_no_op(self, db_session):
        assert insert_prices(db_session, []) == 0
