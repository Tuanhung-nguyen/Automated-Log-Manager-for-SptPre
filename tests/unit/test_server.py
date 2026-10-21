import unittest
import json
import threading
from http.server import HTTPServer
import urllib.request
from unittest.mock import patch, MagicMock

from app.adapters.router import ADAPTER_REGISTRY
from app.adapters.base import BaseSourceAdapter
from app.core.models import IncidentContext, AnalysisResult
from server import GenericWebhookHandler





class TestGenericWebhookServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Chạy server ở port tạm thời 8765 trên một thread riêng để test
        cls.port = 8765
        cls.server = HTTPServer(("localhost", cls.port), GenericWebhookHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_healthcheck(self):
        url = f"http://localhost:{self.port}/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "UP")
            self.assertIn("github", data["supported_sources"])

    def test_unsupported_source_returns_400(self):
        url = f"http://localhost:{self.port}/webhook/unknown_tool"
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as resp:
                pass
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            data = json.loads(e.read().decode("utf-8"))
            self.assertEqual(data["status"], "ERROR")

    def test_github_webhook_ignored_when_success(self):
        url = f"http://localhost:{self.port}/webhook/github"
        payload = {
            "workflow_run": {
                "id": 12345,
                "conclusion": "success"
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "IGNORED")

    @patch("server.pipeline.run")
    def test_dynamic_extensibility_with_databricks_webhook(self, mock_pipeline_run):
        # Giả lập pipeline trả về kết quả thành công
        mock_pipeline_run.return_value = MagicMock(status="SUCCESS")

        url = f"http://localhost:{self.port}/webhook/databricks"
        payload = {"event_type": "JOB_RUN_FAILED", "run_id": 999, "run_name": "Dim_Artists_Job"}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "PROCESSED")
            self.assertEqual(data["source"], "databricks")
            mock_pipeline_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
