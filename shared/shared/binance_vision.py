"""
Daily kline history from data.binance.vision.

Binance publishes one zip of daily klines per symbol and month, with a
``.CHECKSUM`` file next to it. This module downloads those files, verifies them,
parses them and loads them into the ``prices`` table. It uses only the standard
library for HTTP so ``shared`` gains no new dependency; tests inject a fake
``Fetcher`` instead of hitting the network.

Format gotchas (see #99): the CSVs have no header, and from 2025-01-01 the open
time is in microseconds instead of milliseconds.
"""

import hashlib
import io
import json
import logging
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from shared.db.models import Price

logger = logging.getLogger(__name__)

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
DAILY_BASE_URL = "https://data.binance.vision/data/spot/daily/klines"
# Mirror of the public API that serves market data only and is not geo-blocked.
REST_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
SOURCE = "binance_vision"
REST_SOURCE = "binance_api"

# First month with a file on data.binance.vision, per supported symbol.
# PAXGUSDT (a gold-backed token) is the gold proxy: 24/7 trading, no weekend gaps.
SYMBOL_START_MONTH: dict[str, tuple[int, int]] = {
    "BTCUSDT": (2017, 8),
    "PAXGUSDT": (2020, 8),
}

# Open times at or above this value are microseconds, below it milliseconds.
# Milliseconds reach 10**13 only in the year 2286; microseconds started at 10**15.
_MICROSECONDS_THRESHOLD = 10**14

Fetcher = Callable[[str], bytes]


class BinanceVisionError(Exception):
    """Base class for every error raised while loading Binance history."""


class HttpStatusError(BinanceVisionError):
    """The server answered with a non-success status code."""

    def __init__(self, url: str, status: int):
        super().__init__(f"HTTP {status} for {url}")
        self.url = url
        self.status = status


class DownloadError(BinanceVisionError):
    """A file could not be downloaded (network failure or repeated 5xx)."""


class MonthFileNotFoundError(BinanceVisionError):
    """A monthly file (or its checksum) does not exist (HTTP 404)."""


class ChecksumMismatchError(BinanceVisionError):
    """The SHA256 of a downloaded file differs from its .CHECKSUM."""


class CorruptArchiveError(BinanceVisionError):
    """A downloaded file is not a readable zip with a single CSV."""


class HistoryValidationError(BinanceVisionError):
    """The loaded series has missing days or days without volume."""

    def __init__(
        self, symbol: str, missing_days: list[date], zero_volume_days: list[date]
    ):
        parts = []
        if missing_days:
            parts.append("missing days: " + ", ".join(map(str, missing_days)))
        if zero_volume_days:
            parts.append("zero volume: " + ", ".join(map(str, zero_volume_days)))
        super().__init__(f"{symbol} history is invalid ({'; '.join(parts)})")
        self.symbol = symbol
        self.missing_days = missing_days
        self.zero_volume_days = zero_volume_days


def http_get(
    url: str,
    timeout: float = 30.0,
    attempts: int = 3,
    backoff_seconds: float = 2.0,
) -> bytes:
    """Download ``url`` and return the body.

    Network failures (timeouts, resets) and HTTP 5xx are retried with a growing
    pause; 4xx answers are final because retrying cannot change them.

    Raises:
        HttpStatusError: the server answered with a final error status.
        DownloadError: the file could not be downloaded after every attempt.
    """
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
                body: bytes = response.read()
                return body
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise HttpStatusError(url, exc.code) from exc
            failure: Exception = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            failure = exc
        if attempt == attempts:
            raise DownloadError(
                f"Could not download {url} after {attempts} attempts: {failure}"
            ) from failure
        logger.warning(
            "Attempt %d/%d failed for %s (%s); retrying",
            attempt,
            attempts,
            url,
            failure,
        )
        time.sleep(backoff_seconds * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def month_file_url(symbol: str, year: int, month: int) -> str:
    """URL of the monthly daily-klines zip for ``symbol``."""
    return f"{BASE_URL}/{symbol}/1d/{symbol}-1d-{year}-{month:02d}.zip"


def last_closed_month(today: date) -> tuple[int, int]:
    """The most recent fully closed calendar month before ``today``."""
    first_of_month = today.replace(day=1)
    previous = first_of_month - timedelta(days=1)
    return previous.year, previous.month


def months_between(
    start: tuple[int, int], end: tuple[int, int]
) -> list[tuple[int, int]]:
    """Every (year, month) from ``start`` to ``end`` inclusive."""
    months = []
    year, month = start
    while (year, month) <= end:
        months.append((year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def parse_open_time(raw: int) -> datetime:
    """Convert a kline open time (ms or µs since epoch) to 00:00 UTC of its day."""
    seconds = raw / 1_000_000 if raw >= _MICROSECONDS_THRESHOLD else raw / 1_000
    moment = datetime.fromtimestamp(seconds, tz=UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_klines_csv(text: str, symbol: str) -> list[dict[str, Any]]:
    """Parse header-less kline CSV text into ``Price`` column dictionaries."""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split(",")
        rows.append(
            {
                "symbol": symbol,
                "timestamp": parse_open_time(int(fields[0])),
                "open": Decimal(fields[1]),
                "high": Decimal(fields[2]),
                "low": Decimal(fields[3]),
                "close": Decimal(fields[4]),
                "volume": Decimal(fields[5]),
                "source": SOURCE,
            }
        )
    return rows


def _get_existing(fetch: Fetcher, url: str) -> bytes:
    try:
        return fetch(url)
    except HttpStatusError as exc:
        if exc.status == 404:
            raise MonthFileNotFoundError(f"File not found: {url}") from exc
        raise


def _read_archive(url: str, symbol: str, fetch: Fetcher) -> list[dict[str, Any]]:
    """Download ``url`` and its checksum, verify, unzip and parse the klines."""
    archive = _get_existing(fetch, url)
    checksum_line = _get_existing(fetch, url + ".CHECKSUM").decode().split()
    expected = checksum_line[0].lower() if checksum_line else ""
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        raise ChecksumMismatchError(
            f"Checksum mismatch for {url}: expected {expected}, got {actual}"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = bundle.namelist()
            if len(names) != 1:
                raise CorruptArchiveError(f"{url} holds {len(names)} files, expected 1")
            text = bundle.read(names[0]).decode()
    except zipfile.BadZipFile as exc:
        raise CorruptArchiveError(f"{url} is not a valid zip file") from exc
    return parse_klines_csv(text, symbol)


def fetch_month(
    symbol: str, year: int, month: int, fetch: Fetcher = http_get
) -> list[dict[str, Any]]:
    """Download, verify and parse one monthly file.

    Raises:
        MonthFileNotFoundError: the zip or its checksum does not exist.
        ChecksumMismatchError: the zip does not match its .CHECKSUM.
        CorruptArchiveError: the zip cannot be read.
    """
    return _read_archive(month_file_url(symbol, year, month), symbol, fetch)


def daily_file_url(symbol: str, day: date) -> str:
    """URL of the single-day klines zip for ``symbol``."""
    return f"{DAILY_BASE_URL}/{symbol}/1d/{symbol}-1d-{day.isoformat()}.zip"


def fetch_day_file(
    symbol: str, day: date, fetch: Fetcher = http_get
) -> list[dict[str, Any]]:
    """Download, verify and parse the daily file of ``day``.

    Raises:
        MonthFileNotFoundError: the zip or its checksum is not published (404).
        ChecksumMismatchError: the zip does not match its .CHECKSUM.
        CorruptArchiveError: the zip cannot be read.
    """
    return _read_archive(daily_file_url(symbol, day), symbol, fetch)


def fetch_day_rest(
    symbol: str, day: date, fetch: Fetcher = http_get
) -> list[dict[str, Any]]:
    """Fetch the daily bar of ``day`` from the REST klines endpoint.

    Returns an empty list if Binance has no bar for that day.

    Raises:
        BinanceVisionError: the answer is not the expected list of klines.
    """
    start_ms = int(
        datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000
    )
    url = f"{REST_KLINES_URL}?symbol={symbol}&interval=1d&startTime={start_ms}&limit=1"
    try:
        klines = json.loads(fetch(url))
        rows: list[dict[str, Any]] = [
            {
                "symbol": symbol,
                "timestamp": parse_open_time(int(kline[0])),
                "open": Decimal(kline[1]),
                "high": Decimal(kline[2]),
                "low": Decimal(kline[3]),
                "close": Decimal(kline[4]),
                "volume": Decimal(kline[5]),
                "source": REST_SOURCE,
            }
            for kline in klines
        ]
    except (ValueError, TypeError, IndexError, ArithmeticError) as exc:
        raise BinanceVisionError(f"Unexpected klines answer from {url}: {exc}") from exc
    return [row for row in rows if row["timestamp"].date() == day]


def fetch_day(
    symbol: str, day: date, fetch: Fetcher = http_get
) -> list[dict[str, Any]]:
    """Fetch one closed daily bar: the daily file, or REST if it is unpublished.

    Only a 404 on the file triggers the fallback; a checksum mismatch or corrupt
    archive is a real problem and propagates.
    """
    try:
        return fetch_day_file(symbol, day, fetch)
    except MonthFileNotFoundError:
        logger.warning(
            "%s %s: daily file not published yet, using REST klines", symbol, day
        )
        return fetch_day_rest(symbol, day, fetch)


class NoHistoryError(BinanceVisionError):
    """A symbol has no stored bars, so there is nothing to continue from."""


def ingest_new_days(
    session: Session,
    symbol: str,
    today: date | None = None,
    fetch: Fetcher = http_get,
) -> int:
    """Store every closed daily bar after the latest stored one, up to yesterday (UTC).

    The still-open day (``today``) is never requested. A missed day is picked up
    on the next run because the range starts after the latest stored bar. Rows
    are committed one day at a time; any failure stops the run.

    Returns the number of rows inserted.

    Raises:
        NoHistoryError: ``symbol`` has no stored bars (load history first).
        BinanceVisionError: a day could not be fetched from either source.
    """
    latest = session.execute(
        select(Price.timestamp)
        .where(Price.symbol == symbol)
        .order_by(Price.timestamp.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        raise NoHistoryError(
            f"{symbol} has no stored bars; run scripts/load_binance_history.py first"
        )
    yesterday = (today or datetime.now(UTC).date()) - timedelta(days=1)
    day = latest.astimezone(UTC).date() + timedelta(days=1)

    inserted = 0
    while day <= yesterday:
        rows = fetch_day(symbol, day, fetch)
        if not rows:
            raise BinanceVisionError(f"{symbol} {day}: no bar returned by Binance")
        added = insert_prices(session, rows)
        inserted += added
        logger.info("%s %s: %d new", symbol, day, added)
        day += timedelta(days=1)
    return inserted


def insert_prices(session: Session, rows: list[dict[str, Any]]) -> int:
    """Insert rows, skipping (symbol, timestamp) pairs that already exist.

    Returns the number of rows actually inserted.
    """
    if not rows:
        return 0
    statement = (
        pg_insert(Price)
        .values(rows)
        .on_conflict_do_nothing(constraint="unique_price_per_symbol")
    )
    result = cast(CursorResult[Any], session.execute(statement))
    session.commit()
    return int(result.rowcount)


def load_history(
    session: Session,
    symbol: str,
    today: date | None = None,
    fetch: Fetcher = http_get,
    start_month: tuple[int, int] | None = None,
) -> int:
    """Load daily history for ``symbol`` up to the last closed month.

    Months are committed one at a time and any error stops the load, so a bad
    file never leaves partial rows from that file. Running again is a no-op for
    months already loaded. Binance may publish the file of the month that just
    closed a few days late, so a missing file for that last month is skipped with
    a warning; a missing file in any earlier month is still an error.

    Returns the number of rows inserted.
    """
    if symbol not in SYMBOL_START_MONTH:
        raise ValueError(
            f"Unsupported symbol {symbol!r}; use {sorted(SYMBOL_START_MONTH)}"
        )
    first = start_month or SYMBOL_START_MONTH[symbol]
    last = last_closed_month(today or datetime.now(UTC).date())

    inserted = 0
    for year, month in months_between(first, last):
        try:
            rows = fetch_month(symbol, year, month, fetch)
        except MonthFileNotFoundError:
            if (year, month) != last:
                raise
            logger.warning(
                "%s %d-%02d: not published yet, skipping", symbol, year, month
            )
            continue
        added = insert_prices(session, rows)
        inserted += added
        logger.info(
            "%s %d-%02d: %d rows, %d new", symbol, year, month, len(rows), added
        )
    return inserted


def validate_history(session: Session, symbol: str) -> None:
    """Fail if the loaded series has a missing day or a day without volume.

    Only rows loaded from Binance Vision are checked; rows from other sources
    for the same symbol are ignored.

    Raises:
        HistoryValidationError: listing every offending date.
    """
    records = session.execute(
        select(Price.timestamp, Price.volume)
        .where(Price.symbol == symbol, Price.source == SOURCE)
        .order_by(Price.timestamp)
    ).all()
    if not records:
        return
    days = {timestamp.astimezone(UTC).date() for timestamp, _ in records}
    zero_volume = sorted(
        timestamp.astimezone(UTC).date() for timestamp, volume in records if volume <= 0
    )
    first, last = min(days), max(days)
    missing = [
        first + timedelta(days=offset)
        for offset in range((last - first).days + 1)
        if first + timedelta(days=offset) not in days
    ]
    if missing or zero_volume:
        raise HistoryValidationError(symbol, missing, zero_volume)


def check_reachability(fetch: Fetcher = http_get, today: date | None = None) -> str:
    """Request one small checksum file to confirm the host is reachable.

    Meant to run from the deployment environment (Railway), where the Binance
    REST API (api.binance.com) answered HTTP 451. Returns the URL that answered.

    Raises:
        HttpStatusError: e.g. 451 or 403 when the host is blocked.
    """
    year, month = last_closed_month(today or datetime.now(UTC).date())
    url = month_file_url("BTCUSDT", year, month) + ".CHECKSUM"
    fetch(url)
    return url
