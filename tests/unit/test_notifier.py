import unittest
import tempfile
from pathlib import Path
from app.core.models import AnalysisResult, IncidentAnalysis, IncidentContext
from app.observability.records import ExecutionRecord
from app.monitor.notifier import AlertNotifier


class TestAlertNotifier(unittest.TestCase):
    def test_format_and_send_alert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_log_file = Path(tmpdir) / "alerts.log"
            notifier = AlertNotifier(log_file_path=str(temp_log_file))

            # Giả lập AnalysisResult hoàn chỉnh
            analysis = IncidentAnalysis(
                component="GitHub Actions Ingestion",
                error_type="CONNECTION_ERROR",
                severity="HIGH",
                facts=["DNS host resolution failed: databricks%0a", "Terminal exit code 1"],
                inferences=["Newline character in databricks host config"],
                possible_causes=["Secret variable contains trailing newline"],
                recommendation="Strip trailing newline in DATABRICKS_HOST secret",
                confidence=0.95
            )

            context = IncidentContext(
                timestamp="2026-10-18 09:00:00",
                component="GitHub Actions Ingestion",
                error="Workflow Run Failed: ingest-spotify-personal",
                log="Workflow failure",
                metrics={
                    "run_id": 33149238175,
                    "repository": "Tuanhung-nguyen/Spotify_Premium",
                    "html_url": "https://github.com/Tuanhung-nguyen/Spotify_Premium/actions/runs/33149238175"
                }
            )

            rec = ExecutionRecord(
                execution_id="exec_test_123",
                timestamp="2026-10-18T09:00:00Z",
                original_log=context,
                detect_output=True,
                detect_duration_ms=1.5,
                attempts=[],
                tool_calls=[],
                final_status="SUCCESS",
                final_result="CONNECTION_ERROR",
                total_duration_ms=2500.0
            )

            result = AnalysisResult(
                status="SUCCESS",
                analysis=analysis,
                execution_record=rec
            )

            # 1. Kiểm tra format message
            msg = notifier.format_alert_message(result)
            self.assertIn("CẢNH BÁO SỰ CỐ PIPELINE", msg)
            self.assertIn("CONNECTION_ERROR", msg)
            self.assertIn("33149238175", msg)
            self.assertIn("Strip trailing newline", msg)

            # 2. Gửi cảnh báo và kiểm tra file log (Mock Telegram để không gọi mạng khi test)
            with unittest.mock.patch.object(notifier, "_send_telegram") as mock_tg:
                notifier.send_alert(result)
                mock_tg.assert_called_once()

            self.assertTrue(temp_log_file.exists())
            content = temp_log_file.read_text(encoding="utf-8")
            self.assertIn("CONNECTION_ERROR", content)
            self.assertIn("33149238175", content)


if __name__ == "__main__":
    unittest.main()
