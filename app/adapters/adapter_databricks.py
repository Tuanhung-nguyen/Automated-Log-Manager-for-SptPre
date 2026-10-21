from typing import List, Optional, Dict, Any
from app.adapters.base import BaseSourceAdapter
from app.core.models import IncidentContext
from app.tools.tool_databricks import get_databricks_job_run
from app.config import settings


class DatabricksAdapter(BaseSourceAdapter):
    """
    Adapter chuyên biệt dành cho Databricks Workspace & Jobs.
    Chịu trách nhiệm giao tiếp với Databricks API và chuẩn hóa thành IncidentContext.
    """

    def __init__(self, host: Optional[str] = None, token: Optional[str] = None):
        self.host = host or settings.DATABRICKS_HOST
        self.token = token or settings.DATABRICKS_TOKEN

    @property
    def source_name(self) -> str:
        return "databricks"

    def fetch_incident_context(self, target_id: str, **kwargs) -> IncidentContext:
        """
        Dành cho CLI on-demand: lấy trạng thái và log của Databricks Job Run theo run_id.
        """
        run_id = int(target_id)
        host = kwargs.get("host", self.host)
        token = kwargs.get("token", self.token)

        run_info = get_databricks_job_run(run_id=run_id, host=host, token=token)
        run_name = run_info.get("run_name", "Databricks Job")
        result_state = run_info.get("result_state", "UNKNOWN")
        state_message = run_info.get("state_message", "")
        failed_tasks = run_info.get("failed_tasks", [])

        failed_task_keys = [t["task_key"] for t in failed_tasks] if failed_tasks else []
        failed_tasks_str = ", ".join(failed_task_keys) if failed_task_keys else "Main Run"

        context = IncidentContext(
            timestamp=str(run_info.get("start_time", "")),
            component="Databricks Spark Engine",
            error=f"Databricks Job Failed ({run_name}) - State: {result_state}",
            log=(
                f"Databricks Job Run ID: {run_id} failed with state '{result_state}'. "
                f"Failed tasks: [{failed_tasks_str}]. "
                f"Message: {state_message}. "
                f"Please investigate run output and traceback."
            ),
            metrics={
                "run_id": run_id,
                "job_id": run_info.get("job_id"),
                "failed_tasks": failed_task_keys,
                "workspace": self.host,
                "source": self.source_name
            }
        )
        return context

    def parse_webhook_payload(self, payload: Dict[str, Any]) -> Optional[IncidentContext]:
        """
        Dành cho Databricks Webhook:
        Nhận gói tin JSON khi Databricks Job / Notification Destination bắn về.
        Hỗ trợ cả chuẩn Databricks Nested Payload:
        {
          "event_type": "jobs.on_failure",
          "run": {"run_id": 12345},
          "job": {"job_id": 6789, "name": "SptPre"}
        }
        lẫn chuẩn Flat Payload: {"run_id": 12345, "state": "FAILED"}
        """
        run_obj = payload.get("run") if isinstance(payload.get("run"), dict) else {}
        job_obj = payload.get("job") if isinstance(payload.get("job"), dict) else {}

        event_type = payload.get("event_type") or payload.get("event") or ""
        state = payload.get("state") or payload.get("status") or run_obj.get("state") or ""

        run_id = (
            payload.get("run_id")
            or payload.get("runId")
            or run_obj.get("run_id")
            or run_obj.get("runId")
        )

        # Kiểm tra xem có phải là sự cố thất bại hay không (jobs.on_failure, tasks.on_failure, FAILED, INTERNAL_ERROR)
        is_failure = (
            "FAIL" in str(event_type).upper()
            or "FAIL" in str(state).upper()
            or "ERROR" in str(event_type).upper()
            or "ERROR" in str(state).upper()
        )

        if not is_failure or not run_id:
            # Chạy thành công hoặc không phải sự cố -> Bỏ qua
            return None

        job_name = (
            payload.get("job_name")
            or payload.get("run_name")
            or job_obj.get("name")
            or run_obj.get("run_name")
            or "Databricks Job"
        )
        job_id = payload.get("job_id") or job_obj.get("job_id") or run_obj.get("job_id")

        context = IncidentContext(
            timestamp=str(payload.get("timestamp") or run_obj.get("start_time") or ""),
            component="Databricks Spark Engine",
            error=f"Databricks Webhook Alert: {job_name} FAILED",
            log=(
                f"Webhook notification: Databricks Job '{job_name}' (Run ID: {run_id}) "
                f"terminated with failure. Event: {event_type}. State: {state}."
            ),
            metrics={
                "run_id": int(run_id),
                "job_id": job_id,
                "workspace": self.host,
                "source": "databricks_webhook"
            }
        )
        return context

    def poll_new_failures(self, per_page: int = 5, **kwargs) -> List[IncidentContext]:
        """(Tùy chọn) Quét danh sách runs gần nhất trên Databricks nếu dùng polling."""
        return []
