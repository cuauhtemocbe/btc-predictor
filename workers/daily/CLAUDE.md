# workers/daily/ — fixed training window

- The sliding-window size is `training_window_days` in `shared/shared/config.py` (default 21, override with the `TRAINING_WINDOW_DAYS` environment variable) and is stored in `models.params["window_days"]`.
- The daily and weekly trainers use every stored `BTCUSDT` daily row and fail with the required and available row counts when there are fewer than `(window + 1) * 5` (plus `horizon - 1` for the weekly model): `required_training_days()` in `workers/daily/trainer.py`.
