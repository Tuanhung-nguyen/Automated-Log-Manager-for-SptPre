import unittest
from unittest.mock import patch, MagicMock
from app.tools.tool_databricks import get_databricks_job_run, get_databricks_run_output, _extract_error_window
from app.adapters.adapter_databricks import DatabricksAdapter
from app.adapters.router import get_adapter, list_supported_sources
from app.tools.policy import evaluate_policy, PolicyDecision


class TestDatabricksIntegration(unittest.TestCase):
    def test_extract_error_window_finds_traceback(self):
        log_sample = """
        [INFO] Starting Spark Job...
        [INFO] Loading dataset from bronze table...
        Traceback (most recent call last):
          File "/Workspace/Repos/Spotify/transform.py", line 42, in <module>
            df = df.withColumn("duration_min", col("duration_ms") / 60000)
        pyspark.sql.utils.AnalysisException: Column 'duration_ms' does not exist.
        [INFO] Job finished with errors.
        """
        sliced = _extract_error_window(log_sample, window_before=2, window_after=3)
        self.assertIn("AnalysisException", sliced)
        self.assertIn("DATABRICKS LOG TRUNCATED", sliced)

    @patch("requests.get")
    def test_get_databricks_job_run(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job_id": 1001,
            "run_id": 5555,
            "run_name": "Spotify_Transform_Dim_Artists",
            "state": {"life_cycle_state": "TERMINATED", "result_state": "FAILED", "state_message": "Notebook failed"},
            "tasks": [
                {
                    "task_key": "transform_artists",
                    "run_id": 5556,
                    "state": {"result_state": "FAILED", "state_message": "AnalysisException"}
                }
            ]
        }
        mock_get.return_value = mock_response

        result = get_databricks_job_run(run_id=5555, host="https://dbc-test.cloud.databricks.com", token="dapi_test")
        self.assertEqual(result["run_id"], 5555)
        self.assertEqual(result["result_state"], "FAILED")
        self.assertEqual(len(result["failed_tasks"]), 1)
        self.assertEqual(result["failed_tasks"][0]["task_key"], "transform_artists")

    @patch("requests.get")
    def test_get_databricks_run_output(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": "Task failed with exception",
            "error_trace": "pyspark.sql.utils.AnalysisException: Table not found: spotify_raw"
        }
        mock_get.return_value = mock_response

        result = get_databricks_run_output(run_id=5556, host="https://dbc-test.cloud.databricks.com", token="dapi_test")
        self.assertTrue(result["has_error"])
        self.assertIn("AnalysisException", result["log_slice"])

    @patch("app.adapters.adapter_databricks.get_databricks_job_run")
    def test_databricks_adapter_fetch_incident_context(self, mock_get_run):
        mock_get_run.return_value = {
            "run_name": "Spotify_Daily_ETL",
            "result_state": "FAILED",
            "state_message": "Cluster crashed",
            "failed_tasks": [{"task_key": "step_dim_users"}],
            "job_id": 9999,
            "start_time": 1729000000
        }

        adapter = DatabricksAdapter(host="https://dbc-test.cloud.databricks.com", token="dapi_test")
        ctx = adapter.fetch_incident_context(target_id="123456")

        self.assertEqual(ctx.component, "Databricks Spark Engine")
        self.assertIn("Databricks Job Failed", ctx.error)
        self.assertEqual(ctx.metrics["run_id"], 123456)
        self.assertEqual(ctx.metrics["failed_tasks"], ["step_dim_users"])

    def test_databricks_adapter_webhook_parsing(self):
        adapter = DatabricksAdapter()
        # Test case 1: Sự cố thất bại
        payload_fail = {
            "event_type": "JOB_RUN_FAILED",
            "run_id": 7890,
            "run_name": "Fact_Streams_Job",
            "state": "FAILED"
        }
        ctx = adapter.parse_webhook_payload(payload_fail)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.component, "Databricks Spark Engine")
        self.assertEqual(ctx.metrics["run_id"], 7890)

        # Test case 2: Sự kiện thành công -> Phải bỏ qua (None)
        payload_success = {
            "event_type": "JOB_RUN_SUCCEEDED",
            "run_id": 7891,
            "state": "SUCCESS"
        }
        ctx_success = adapter.parse_webhook_payload(payload_success)
        self.assertIsNone(ctx_success)

    def test_policy_allows_databricks_tools(self):
        # Đảm bảo policy cho phép tự động thực thi các tool READ này
        self.assertEqual(evaluate_policy("get_databricks_job_run"), PolicyDecision.ALLOW)
        self.assertEqual(evaluate_policy("get_databricks_run_output"), PolicyDecision.ALLOW)

    def test_router_includes_databricks(self):
        # Đảm bảo router đã nhận diện databricks
        self.assertIn("databricks", list_supported_sources())
        adapter = get_adapter("databricks")
        self.assertEqual(adapter.source_name, "databricks")


if __name__ == "__main__":
    unittest.main()
