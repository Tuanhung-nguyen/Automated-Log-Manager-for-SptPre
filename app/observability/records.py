from pydantic import BaseModel
from typing import Optional
from app.core.models import IncidentContext


class AttemptRecord(BaseModel):
    """
    Micro-level Observability:
    Lưu lại thông số chi tiết của từng attempt trong vòng lặp retry.
    """
    attempt: int

    # LLM
    llm_output: Optional[str] = None
    llm_duration_ms: Optional[float] = None

    # Validator
    validation_result: Optional[str] = None
    validation_error: Optional[str] = None
    error_category: Optional[str] = None
    validation_duration_ms: Optional[float] = None

    # Retry
    feedback: Optional[str] = None

    # Attempt
    status: str
    duration_ms: float


class ExecutionRecord(BaseModel):
    """
    Macro-level Observability:
    Lưu lại toàn bộ vết thực thi toàn trình của một lần chạy pipeline.
    """
    execution_id: str
    timestamp: str

    original_log: IncidentContext

    # Detector chạy 1 lần
    detect_output: bool
    detect_duration_ms: float

    # Analysis có thể có nhiều attempt
    attempts: list[AttemptRecord]

    # Tool calls & results trong Agent loop (Phase 5)
    tool_calls: list[dict] = []

    # Final
    final_status: str
    final_result: Optional[str] = None
    total_duration_ms: float
