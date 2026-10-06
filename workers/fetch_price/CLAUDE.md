# workers/fetch_price/ — Binance Vision ingest

- **Stored data:** one closed UTC daily bar per symbol in `prices` (`symbol`, `timestamp` = 00:00 UTC open, OHLCV, `source`), UNIQUE on `(symbol, timestamp)`.
- **History:** `scripts/load_binance_history.py` loads the monthly files once (`BTCUSDT` from 2017-08, `PAXGUSDT` from 2020-08), verifying each SHA256 checksum.
- **Daily ingest:** `fetch-price` (00:05 UTC) reads the `daily/` file of each symbol and falls back to REST if the file is not published yet, which is the usual case at that hour (it logs a warning). It backfills missed days and never stores the still-open day.
- The REST fallback uses `data-api.binance.vision` because the Binance REST API is geo-blocked from Railway (HTTP 451). Why Binance Vision is the only source: Design Decision 5 in the root `CLAUDE.md`.
