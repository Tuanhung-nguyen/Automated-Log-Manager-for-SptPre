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
        Hỗ trợ cả sự cố THẤT BẠI lẫn chạy THÀNH CÔNG.
        """
        run_obj = payload.get("run") if isinstance(payload.get("run"), dict) else {}
        job_obj = payload.get("job") if isinstance(payload.get("job"), dict) else {}
        state_obj = run_obj.get("state") if isinstance(run_obj.get("state"), dict) else {}

        event_type = payload.get("event_type") or payload.get("event") or ""
        state = (
            payload.get("state")
            or payload.get("status")
            or state_obj.get("result_state")
            or state_obj.get("life_cycle_state")
            or run_obj.get("state")
            or ""
        )

        run_id = (
            payload.get("run_id")
            or payload.get("runId")
            or run_obj.get("run_id")
            or run_obj.get("runId")
        )

        if not run_id:
            return None

        job_name = (
            payload.get("job_name")
            or payload.get("run_name")
            or job_obj.get("name")
            or run_obj.get("run_name")
            or "Databricks Job"
        )
        job_id = payload.get("job_id") or job_obj.get("job_id") or run_obj.get("job_id")

        state_str = str(state).upper()
        event_str = str(event_type).upper()

        is_failure = (
            "FAIL" in event_str
            or "FAIL" in state_str
            or "ERROR" in event_str
            or "ERROR" in state_str
        )

        # Tự động nhận diện project_name: từ payload webhook -> tags của job -> tiền tố tên job -> default
        project_name = (
            payload.get("project_name")
            or payload.get("project")
            or job_obj.get("tags", {}).get("project")
            or job_obj.get("tags", {}).get("project_name")
            or run_obj.get("job_tags", {}).get("project")
            or (job_name.split("_")[0] if "_" in job_name else job_name)
            or getattr(settings, "DEFAULT_PROJECT_NAME", "default")
        )

        duration_sec = 0.0
        exec_duration = run_obj.get("execution_duration") or payload.get("execution_duration")
        if exec_duration:
            duration_sec = round(float(exec_duration) / 1000.0, 2)
        elif run_obj.get("end_time") and run_obj.get("start_time"):
            duration_sec = round((float(run_obj["end_time"]) - float(run_obj["start_time"])) / 1000.0, 2)

        subtasks = run_obj.get("tasks") or payload.get("tasks") or []
        failed_task_keys = [
            t.get("task_key") for t in subtasks
            if isinstance(t, dict) and str(t.get("state", {}).get("result_state", "")).upper() in ("FAILED", "INTERNAL_ERROR")
        ]

        if is_failure:
            return IncidentContext(
                timestamp=str(payload.get("timestamp") or run_obj.get("start_time") or ""),
                component="Databricks Spark Engine",
                error=f"Databricks Webhook Alert: {job_name} FAILED",
                log=(
                    f"Webhook notification: Databricks Job '{job_name}' (Run ID: {run_id}) "
                    f"terminated with failure. Event: {event_type}. State: {state}."
                ),
                metrics={
                    "run_id": int(run_id) if str(run_id).isdigit() else run_id,
                    "job_id": job_id,
                    "job_name": job_name,
                    "project_name": project_name,
                    "status": "FAILED",
                    "duration_sec": duration_sec,
                    "workspace": self.host,
                    "source": "databricks_webhook",
                    "tasks": subtasks,
                    "failed_tasks": failed_task_keys
                }
            )
        else:
            return IncidentContext(
                timestamp=str(payload.get("timestamp") or run_obj.get("start_time") or ""),
                component="Databricks Spark Engine",
                error=None,
                log=(
                    f"Webhook notification: Databricks Job '{job_name}' (Run ID: {run_id}) "
                    f"completed successfully. Event: {event_type}. State: {state}."
                ),
                metrics={
                    "run_id": int(run_id) if str(run_id).isdigit() else run_id,
                    "job_id": job_id,
                    "job_name": job_name,
                    "project_name": project_name,
                    "status": "SUCCESS",
                    "duration_sec": duration_sec,
                    "workspace": self.host,
                    "source": "databricks_webhook",
                    "tasks": subtasks
                }
            )

    def poll_new_failures(self, per_page: int = 5, **kwargs) -> List[IncidentContext]:
        """(Tùy chọn) Quét danh sách runs gần nhất trên Databricks nếu dùng polling."""
        return []


