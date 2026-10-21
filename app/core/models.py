from pydantic import BaseModel, Field, model_validator
from typing import Optional, Literal, Any
from .exceptions import ErrorCategory


class IncidentContext(BaseModel):
    """
    Data Contract cho INPUT của AI.
    Đại diện cho thông tin ngữ cảnh sự cố được thu thập từ pipeline/hệ thống.
    """
    timestamp: str
    component: str
    error: str
    log: str
    metrics: Optional[dict] = None


class IncidentAnalysis(BaseModel):
    """
    Data Contract cho OUTPUT của AI khi phân tích thành công.
    Đại diện cho phân tích, suy luận và khuyến nghị do AI tạo ra.
    """
    component: str
    error_type: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    facts: list[str] = Field(description="Các sự thật trích xuất trực tiếp từ context/log")
    inferences: list[str] = Field(description="Suy luận từ facts")
    possible_causes: list[str]
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0, description="Độ tự tin từ 0.0 đến 1.0")


class HumanReviewRecord(BaseModel):
    """
    Data Contract cho FALLBACK / ESCALATION khi AI thất bại hoặc hết số lần retry.
    Chuyển giao cho kỹ sư con người xử lý mà không làm sập pipeline.
    """
    status: Literal["HUMAN_REVIEW_REQUIRED"] = "HUMAN_REVIEW_REQUIRED"
    attempts: int
    reason: str
    error_category: ErrorCategory
    validation_error: Optional[str] = None
    last_llm_response: Optional[str] = None
    context: IncidentContext


class AnalysisResult(BaseModel):
    """
    Unified Output Contract (Wrapper Result) cho toàn bộ pipeline:
    Tách biệt trạng thái xử lý khỏi nội dung chi tiết và đảm bảo tính nhất quán (Consistency).
    Bao gồm cả execution_record phục vụ Observability & Metrics (Phase 4).
    """
    status: Literal["SUCCESS", "HUMAN_REVIEW_REQUIRED", "SKIPPED"]
    analysis: Optional[IncidentAnalysis] = None
    human_review: Optional[HumanReviewRecord] = None
    execution_record: Optional[Any] = None

    @model_validator(mode='after')
    def validate_status_and_payload_consistency(self) -> 'AnalysisResult':
        if self.status == "SUCCESS" and self.analysis is None:
            raise ValueError("Invalid AnalysisResult: status là 'SUCCESS' thì bắt buộc phải có 'analysis' payload.")

        if self.status == "HUMAN_REVIEW_REQUIRED" and self.human_review is None:
            raise ValueError("Invalid AnalysisResult: status là 'HUMAN_REVIEW_REQUIRED' thì bắt buộc phải có 'human_review' payload.")

        return self


class ToolCall(BaseModel):
    """
    Contract cho đề xuất gọi Tool từ LLM (Phase 5).
    Nếu LLM cần thông tin, trả về tool_name và arguments tương ứng.
    Nếu không cần gọi tool, tool_name là None.
    """
    tool_name: Optional[str] = None
    arguments: dict = Field(default_factory=dict)


class ToolResult(BaseModel):
    """
    Contract cho kết quả trả về từ việc thực thi Tool (Phase 5).
    """
    tool_name: str
    result: dict
