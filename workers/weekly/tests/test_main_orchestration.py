"""
Tests for the weekly job orchestrator (workers/weekly/__main__.py, issue #64).

Covers Gherkin acceptance criteria:
1. Weekly job stops when evaluation fails
2. Weekly job succeeds only when every stage succeeds
Plus, symmetric with the daily orchestrator: stopping on trainer failure,
preserving the original failure code, and treating an uncaught exception
as a failure.

Stage dependency: evaluator -> trainer -> predictor
"""

from unittest.mock import patch

from workers.weekly import __main__ as orchestrator
from workers.weekly import evaluator, predictor, trainer


class TestWeeklyOrchestration:
    def test_stops_when_evaluator_fails(self) -> None:
        """
        Given the weekly evaluator returns a non-zero exit code
        When the weekly orchestrator runs
        Then the weekly trainer and predictor are not executed
        And the orchestrator returns a non-zero exit code
        """
        with (
            patch.object(evaluator, "main", return_value=1) as mock_eval,
            patch.object(trainer, "main") as mock_train,
            patch.object(predictor, "main") as mock_predict,
        ):
            exit_code = orchestrator.main()

        assert exit_code != 0
        mock_eval.assert_called_once()
        mock_train.assert_not_called()
        mock_predict.assert_not_called()

    def test_stops_when_trainer_fails(self) -> None:
        """
        Given the weekly evaluator completes successfully
        And the weekly trainer returns a non-zero exit code
        When the weekly orchestrator runs
        Then the predictor is not executed
        And the orchestrator returns a non-zero exit code
        """
        with (
            patch.object(evaluator, "main", return_value=0),
            patch.object(trainer, "main", return_value=1),
            patch.object(predictor, "main") as mock_predict,
        ):
            exit_code = orchestrator.main()

        assert exit_code != 0
        mock_predict.assert_not_called()

    def test_succeeds_only_when_every_stage_succeeds(self) -> None:
        """
        Given the weekly evaluator, trainer, and predictor all complete
        successfully
        When the weekly orchestrator runs
        Then the orchestrator returns exit code zero
        """
        with (
            patch.object(evaluator, "main", return_value=0) as mock_eval,
            patch.object(trainer, "main", return_value=0) as mock_train,
            patch.object(predictor, "main", return_value=0) as mock_predict,
        ):
            exit_code = orchestrator.main()

        assert exit_code == 0
        mock_eval.assert_called_once()
        mock_train.assert_called_once()
        mock_predict.assert_called_once()

    def test_preserves_the_original_failure_code(self) -> None:
        """
        Given a job stage fails with a specific non-zero exit code
        When the orchestrator stops because of that failure
        Then it returns the same non-zero exit code
        """
        with (
            patch.object(evaluator, "main", return_value=7),
            patch.object(trainer, "main") as mock_train,
            patch.object(predictor, "main") as mock_predict,
        ):
            exit_code = orchestrator.main()

        assert exit_code == 7
        mock_train.assert_not_called()
        mock_predict.assert_not_called()

    def test_unexpected_exception_in_evaluator_stops_the_pipeline(self) -> None:
        """
        Given the weekly evaluator raises an unexpected exception instead
        of returning normally
        When the weekly orchestrator runs
        Then the trainer and predictor are not executed
        And the orchestrator reports failure
        """
        with (
            patch.object(evaluator, "main", side_effect=RuntimeError("boom")),
            patch.object(trainer, "main") as mock_train,
            patch.object(predictor, "main") as mock_predict,
        ):
            exit_code = orchestrator.main()

        assert exit_code != 0
        mock_train.assert_not_called()
        mock_predict.assert_not_called()
