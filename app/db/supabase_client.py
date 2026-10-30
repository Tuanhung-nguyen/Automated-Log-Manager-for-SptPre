import sys
import logging
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from app.config import settings

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

logger = logging.getLogger("app.db.supabase")


class SupabaseClient:
    """
    Client giao tiếp với Supabase qua PostgREST HTTP REST API:
    - Quản lý 3 bảng cốt lõi: pipeline_runs, log_events, ai_diagnoses.
    - Hoạt động nhẹ nhàng (Zero extra heavy dependencies).
    - Thiết kế chịu lỗi: Nếu DB tạm thời không kết nối được, in cảnh báo và không làm sập pipeline.
    """

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None, timeout: int = 10):
        self.url = (url or settings.SUPABASE_URL or "").rstrip("/")
        self.key = key or settings.SUPABASE_KEY
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.key)

    def _get_headers(self, upsert: bool = False) -> Dict[str, str]:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        if upsert:
            headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        return headers

    def upsert_pipeline_run(
        self,
        run_id: str,
        pipeline_name: str,
        project_name: str = "default",
        pipeline_id: Optional[str] = None,
        source: str = "databricks",
        status: str = "RUNNING",
        triggered_by: str = "scheduler",
        start_time: Optional[Any] = None,
        end_time: Optional[Any] = None,
        duration_sec: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Ghi nhận hoặc cập nhật trạng thái lần chạy vào bảng pipeline_runs."""
        if not self.is_configured:
            return False

        endpoint = f"{self.url}/rest/v1/pipeline_runs"
        payload = {
            "run_id": str(run_id),
            "project_name": project_name,
            "pipeline_name": pipeline_name,
            "pipeline_id": str(pipeline_id) if pipeline_id else None,
            "source": source,
            "status": status,
            "triggered_by": triggered_by,
            "duration_sec": duration_sec,
            "metadata": metadata or {}
        }
        if start_time:
            payload["start_time"] = start_time if isinstance(start_time, str) else start_time.isoformat()
        if end_time:
            payload["end_time"] = end_time if isinstance(end_time, str) else end_time.isoformat()

        try:
            resp = requests.post(endpoint, headers=self._get_headers(upsert=True), json=payload, timeout=self.timeout)
            if resp.status_code in (200, 201):
                return True
            print(f"⚠️ [SUPABASE WARN] Không thể lưu pipeline_run: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            print(f"⚠️ [SUPABASE ERROR] Kết nối lưu pipeline_run thất bại: {e}")
            return False

    def insert_log_event(
        self,
        run_id: str,
        message: str,
        level: str = "INFO",
        task_name: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timestamp: Optional[Any] = None
    ) -> bool:
        """Ghi nhận một sự kiện log vào bảng log_events."""
        if not self.is_configured:
            return False

        endpoint = f"{self.url}/rest/v1/log_events"
        data = {
            "run_id": str(run_id),
            "level": level.upper(),
            "task_name": task_name,
            "message": message,
            "payload": payload or {}
        }
        if timestamp:
            data["timestamp"] = timestamp if isinstance(timestamp, str) else timestamp.isoformat()
        else:
            data["timestamp"] = datetime.now(timezone.utc).isoformat()

        try:
            resp = requests.post(endpoint, headers=self._get_headers(), json=data, timeout=self.timeout)
            if resp.status_code in (200, 201):
                return True
            print(f"⚠️ [SUPABASE WARN] Không thể lưu log_event: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            print(f"⚠️ [SUPABASE ERROR] Kết nối lưu log_event thất bại: {e}")
            return False

    def upsert_ai_diagnosis(
        self,
        run_id: str,
        error_type: str,
        severity: str,
        confidence: float,
        root_cause: str,
        recommendation: str,
        facts: Optional[List[str]] = None,
        possible_causes: Optional[List[str]] = None,
        tools_used: Optional[List[Dict[str, Any]]] = None,
        iterations: int = 1,
        tokens_used: int = 0,
        duration_ms: float = 0.0
    ) -> bool:
        """Ghi nhận kết quả phân tích sự cố chuyên sâu của AI vào bảng ai_diagnoses."""
        if not self.is_configured:
            return False

        endpoint = f"{self.url}/rest/v1/ai_diagnoses"
        payload = {
            "run_id": str(run_id),
            "error_type": error_type,
            "severity": severity,
            "confidence": confidence,
            "root_cause": root_cause,
            "recommendation": recommendation,
            "facts": facts or [],
            "possible_causes": possible_causes or [],
            "tools_used": tools_used or [],
            "iterations": iterations,
            "tokens_used": tokens_used,
            "duration_ms": duration_ms
        }

        try:
            resp = requests.post(endpoint, headers=self._get_headers(upsert=True), json=payload, timeout=self.timeout)
            if resp.status_code in (200, 201):
                print(f"💾 [SUPABASE] Đã lưu kết quả phân tích RCA cho Run ID '{run_id}' vào Supabase!")
                return True
            print(f"⚠️ [SUPABASE WARN] Không thể lưu ai_diagnosis: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            print(f"⚠️ [SUPABASE ERROR] Kết nối lưu ai_diagnosis thất bại: {e}")
            return False


_global_db_client: Optional[SupabaseClient] = None


def get_db() -> SupabaseClient:
    """Singleton getter cho SupabaseClient."""
    global _global_db_client
    if _global_db_client is None:
        _global_db_client = SupabaseClient()
    return _global_db_client
