from typing import Dict, Type
from app.adapters.base import BaseSourceAdapter
from app.adapters.adapter_github import GitHubAdapter
from app.adapters.adapter_databricks import DatabricksAdapter


# =====================================================================
# DANH BẠ ĐĂNG KÝ CÔNG KHAI CÁC ADAPTERS (TƯỜNG MINH, DỄ TRA CỨU)
# =====================================================================
ADAPTER_REGISTRY: Dict[str, Type[BaseSourceAdapter]] = {
    "github": GitHubAdapter,
    "databricks": DatabricksAdapter,
    # "airflow": AirflowAdapter,
}


def get_adapter(source_name: str, **kwargs) -> BaseSourceAdapter:
    """Tra cứu và khởi tạo adapter tương ứng theo tên nguồn."""
    key = source_name.lower().strip()
    adapter_cls = ADAPTER_REGISTRY.get(key)
    if not adapter_cls:
        supported = ", ".join(ADAPTER_REGISTRY.keys())
        raise ValueError(
            f"Nguồn '{source_name}' chưa được hỗ trợ. "
            f"Các nguồn hiện có trong hệ thống: [{supported}]"
        )
    return adapter_cls(**kwargs)


def list_supported_sources() -> list[str]:
    """Danh sách các nguồn đang được hỗ trợ."""
    return list(ADAPTER_REGISTRY.keys())
