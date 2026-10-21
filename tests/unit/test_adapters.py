import unittest
from app.adapters.base import BaseSourceAdapter
from app.adapters.router import ADAPTER_REGISTRY, get_adapter, list_supported_sources
from app.core.models import IncidentContext


class MockAirflowAdapter(BaseSourceAdapter):
    @property
    def source_name(self) -> str:
        return "airflow"

    def fetch_incident_context(self, target_id: str, **kwargs) -> IncidentContext:
        return IncidentContext(
            timestamp="2026-10-20 10:00:00",
            component="Airflow DAG",
            error=f"Task failed: {target_id}",
            log=f"Airflow task execution failed for {target_id}",
            metrics={"task_id": target_id, "source": "airflow"}
        )

    def parse_webhook_payload(self, payload: dict):
        return None

    def poll_new_failures(self, per_page: int = 5, **kwargs):
        return []


class TestAdaptersAndRegistry(unittest.TestCase):
    def test_default_registry_has_github_and_databricks(self):
        # 1. Kiểm tra danh bạ mặc định có cả github và databricks
        supported = list_supported_sources()
        self.assertIn("github", supported)
        self.assertIn("databricks", supported)

        # 2. Lấy adapter và kiểm tra
        adapter_gh = get_adapter("github")
        self.assertEqual(adapter_gh.source_name, "github")

        adapter_db = get_adapter("databricks")
        self.assertEqual(adapter_db.source_name, "databricks")

    def test_unsupported_source_raises(self):
        # 3. Yêu cầu nguồn chưa đăng ký phải báo lỗi rõ ràng
        with self.assertRaises(ValueError) as ctx:
            get_adapter("unknown_platform")
        self.assertIn("chưa được hỗ trợ", str(ctx.exception))

    def test_extensibility_by_adding_to_registry(self):
        # 4. Kiểm tra việc mở rộng: Thêm công cụ mới (Airflow) chỉ bằng 1 dòng vào ADAPTER_REGISTRY!
        ADAPTER_REGISTRY["airflow"] = MockAirflowAdapter

        self.assertIn("airflow", list_supported_sources())
        adapter = get_adapter("airflow")
        self.assertEqual(adapter.source_name, "airflow")

        ctx = adapter.fetch_incident_context("dag_daily_orders")
        self.assertEqual(ctx.component, "Airflow DAG")
        self.assertEqual(ctx.metrics["task_id"], "dag_daily_orders")

        # Dọn dẹp sau khi test
        del ADAPTER_REGISTRY["airflow"]


if __name__ == "__main__":
    unittest.main()
