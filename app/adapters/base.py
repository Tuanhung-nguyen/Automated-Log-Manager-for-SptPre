from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from app.core.models import IncidentContext


class BaseSourceAdapter(ABC):
    """
    Interface chuẩn cho mọi nguồn dữ liệu/công cụ trong pipeline (GitHub, Databricks, Airflow, v.v.).
    Mỗi công cụ khi tích hợp vào hệ thống đều phải tuân thủ chuẩn này.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Tên định danh của nguồn (ví dụ: 'github', 'databricks', 'airflow')."""
        pass

    @abstractmethod
    def fetch_incident_context(self, target_id: str, **kwargs) -> IncidentContext:
        """
        Lấy thông tin và log của một sự cố cụ thể dựa trên ID (run_id, job_id, task_id).
        Đóng gói dữ liệu thô thành IncidentContext chuẩn của hệ thống (dành cho CLI On-Demand).
        """
        pass

    @abstractmethod
    def parse_webhook_payload(self, payload: Dict[str, Any]) -> Optional[IncidentContext]:
        """
        Tiếp nhận và bóc tách gói tin JSON thô do công cụ tự động bắn về qua Webhook.
        - Nếu sự cố là THẤT BẠI (failure) -> Đóng gói và trả về IncidentContext chuẩn.
        - Nếu chạy THÀNH CÔNG (success) hoặc không phải sự cố -> Trả về None để bỏ qua.
        """
        pass

    @abstractmethod
    def poll_new_failures(self, per_page: int = 5, **kwargs) -> List[IncidentContext]:
        """
        Quét danh sách các lần chạy gần nhất để tìm các sự cố thất bại mới.
        """
        pass
