import unittest
from unittest.mock import MagicMock, patch
import tempfile
from pathlib import Path

from app.monitor.state import StateTracker
from app.monitor.poller import GitHubWorkflowPoller
from app.core.models import AnalysisResult


class TestGitHubWorkflowPoller(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.temp_state_file = Path(self.tmpdir.name) / "seen_runs.json"
        self.tracker = StateTracker(state_file_path=str(self.temp_state_file))
        self.mock_pipeline = MagicMock()
        from app.core.models import IncidentAnalysis
        mock_analysis = IncidentAnalysis(
            component="GitHub Actions Ingestion",
            error_type="CONNECTION_ERROR",
            severity="HIGH",
            facts=["DNS failure"],
            inferences=["Invalid host URL"],
            possible_causes=["Typo in Databricks URL"],
            recommendation="Fix host URL in secrets",
            confidence=0.9
        )
        self.mock_pipeline.run.return_value = AnalysisResult(
            status="SUCCESS",
            analysis=mock_analysis
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    @patch("app.monitor.poller.get_github_workflow_runs")
    def test_poll_once_detects_new_failure(self, mock_get_runs):
        # Giả lập GitHub trả về 2 workflow runs: 1 success, 1 failure
        mock_get_runs.return_value = {
            "workflow_runs": [
                {
                    "id": 111,
                    "name": "ETL Ingestion",
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": "2026-10-15T10:00:00Z",
                    "html_url": "https://github.com/test/run/111"
                },
                {
                    "id": 222,
                    "name": "ETL Ingestion",
                    "status": "completed",
                    "conclusion": "failure",
                    "created_at": "2026-10-15T10:05:00Z",
                    "html_url": "https://github.com/test/run/222"
                }
            ]
        }

        poller = GitHubWorkflowPoller(
            pipeline=self.mock_pipeline,
            state_tracker=self.tracker,
            owner="test_owner",
            repo="test_repo"
        )

        # Lần quét 1: Chưa thấy 222 -> Phải gọi pipeline.run
        results = poller.poll_once()
        self.assertEqual(len(results), 1)
        self.mock_pipeline.run.assert_called_once()
        self.assertTrue(self.tracker.is_seen(222))

        # Lần quét 2: Đã thấy 222 rồi -> Không được gọi lại pipeline.run
        self.mock_pipeline.run.reset_mock()
        results_second = poller.poll_once()
        self.assertEqual(len(results_second), 0)
        self.mock_pipeline.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
