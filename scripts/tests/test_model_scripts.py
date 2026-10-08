"""
Tests for the operational model CLIs (#160).

Covers:
- scripts/activate_model.py: argument parsing, activation, error exit codes
- scripts/list_models.py: table output, active marker, no-active warning
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from scripts import activate_model, list_models
from shared.db.crud import get_all_models
from shared.db.models import Model


def _save_model(
    session: Session,
    name: str,
    *,
    active: bool = False,
    version: str = "v1",
    params: dict[str, Any] | None = None,
) -> Model:
    """Insert one model record and return it."""
    record = Model(
        name=name,
        version=version,
        params={} if params is None else params,
        artifact=b"",
        trained_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        train_from=date(2025, 1, 1),
        train_to=date(2026, 1, 1),
        timeframe="1d",
        is_active=active,
    )
    session.add(record)
    session.commit()
    return record


def _active_ids(session: Session) -> list[int]:
    session.expire_all()  # the activation runs bulk UPDATEs
    return sorted(m.id for m in get_all_models(session) if m.is_active)


@pytest.fixture
def patch_session(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> Callable[[Any], None]:
    """Return a function that points a script module's SessionLocal at the test DB."""

    def _patch(module: Any) -> None:
        monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    return _patch


class TestActivateModel:
    def test_model_id_is_required(self, patch_session: Callable[[Any], None]) -> None:
        patch_session(activate_model)
        with pytest.raises(SystemExit) as exc:
            activate_model.main([])
        assert exc.value.code == 2

    def test_activates_only_the_given_model(
        self, db_session: Session, patch_session: Callable[[Any], None]
    ) -> None:
        patch_session(activate_model)
        # The activation replaces the active model with the same name and timeframe
        _save_model(db_session, "linear", active=True, version="v1")
        target = _save_model(db_session, "linear", version="v2")

        assert activate_model.main([f"--model-id={target.id}"]) == 0

        assert _active_ids(db_session) == [target.id]

    def test_unknown_id_returns_1_with_hint(
        self,
        db_session: Session,
        patch_session: Callable[[Any], None],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        patch_session(activate_model)
        keep = _save_model(db_session, "linear_v1", active=True)

        with caplog.at_level("ERROR"):
            assert activate_model.main(["--model-id=999999"]) == 1

        assert "list_models.py" in caplog.text
        assert _active_ids(db_session) == [keep.id]

    def test_unexpected_exception_returns_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patch_session: Callable[[Any], None],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        patch_session(activate_model)

        def boom(session: Session, model_id: int) -> Model:
            raise RuntimeError("database down")

        monkeypatch.setattr(activate_model, "activate_model", boom)

        with caplog.at_level("ERROR"):
            assert activate_model.main(["--model-id=1"]) == 1

        assert "UNEXPECTED ERROR: database down" in caplog.text

    def test_warns_when_model_is_not_linear(
        self,
        db_session: Session,
        patch_session: Callable[[Any], None],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        patch_session(activate_model)
        xgb = _save_model(
            db_session, "xgboost_v1", params={"validation_error_pct": 1.5}
        )

        with caplog.at_level("INFO"):
            assert activate_model.main([f"--model-id={xgb.id}"]) == 0

        assert "only train 'linear'" in caplog.text
        assert "Val Error: 1.5%" in caplog.text

    def test_no_warning_for_linear_model(
        self,
        db_session: Session,
        patch_session: Callable[[Any], None],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        patch_session(activate_model)
        linear = _save_model(db_session, "linear_v1")

        with caplog.at_level("INFO"):
            assert activate_model.main([f"--model-id={linear.id}"]) == 0

        assert "only train 'linear'" not in caplog.text


class TestListModels:
    def test_format_validation_error(self) -> None:
        with_error = list_models.format_validation_error(
            {"validation_error_pct": 1.234}
        )
        assert with_error == "1.23%"
        assert list_models.format_validation_error({}) == "N/A"

    def test_empty_table(
        self, patch_session: Callable[[Any], None], capsys: pytest.CaptureFixture[str]
    ) -> None:
        patch_session(list_models)

        assert list_models.main([]) == 0

        out = capsys.readouterr().out
        assert "No models found in database." in out
        assert "python -m workers.daily.trainer" in out

    def test_rows_show_active_marker_and_validation_error(
        self,
        db_session: Session,
        patch_session: Callable[[Any], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        patch_session(list_models)
        _save_model(db_session, "linear_v1", params={"validation_error_pct": 2.5})
        _save_model(
            db_session, "xgboost_v1", active=True, params={"validation_error_pct": 1.0}
        )
        _save_model(db_session, "arima_v1")

        assert list_models.main() == 0

        out = capsys.readouterr().out
        rows = {
            line.split()[1]: line
            for line in out.splitlines()
            if line.split() and line.split()[0].isdigit()
        }
        assert "No " in rows["linear_v1"]
        assert "2.50%" in rows["linear_v1"]
        assert "✓ Yes" in rows["xgboost_v1"]
        assert "1.00%" in rows["xgboost_v1"]
        assert "N/A" in rows["arima_v1"]
        assert "Total: 3 model(s)" in out
        assert "xgboost_v1" in out.split("Currently active model:")[1]
        assert "No active model" not in out

    def test_warns_when_no_model_is_active(
        self,
        db_session: Session,
        patch_session: Callable[[Any], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        patch_session(list_models)
        _save_model(db_session, "linear_v1")

        assert list_models.main([]) == 0

        out = capsys.readouterr().out
        assert "WARNING: No active model!" in out
        assert "activate_model.py --model-id=X" in out

    def test_unexpected_exception_returns_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patch_session: Callable[[Any], None],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        patch_session(list_models)

        def boom(session: Session) -> list[Model]:
            raise RuntimeError("database down")

        monkeypatch.setattr(list_models, "get_all_models", boom)

        with caplog.at_level("ERROR"):
            assert list_models.main([]) == 1

        assert "UNEXPECTED ERROR: database down" in caplog.text
