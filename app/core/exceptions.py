from enum import Enum


class ErrorCategory(str, Enum):
    """
    Phân loại lỗi trong pipeline AI for Data Engineering:
    Giúp hệ thống xác định rõ nguyên nhân lỗi và quyết định hành vi xử lý tương ứng
    (vd: lỗi nào nên retry, lỗi nào cần dừng lại ngay lập tức).
    """
    API_ERROR = "LLM/API Error"
    JSON_PARSE_ERROR = "JSON Parse Error"
    SCHEMA_ERROR = "Schema Error"
    SEMANTIC_ERROR = "Semantic Error"
    EVIDENCE_ERROR = "Evidence Error"
    UNKNOWN_ERROR = "Unknown Error"
    RETRY_EXHAUSTED = "Retry Exhausted"


class PipelineError(Exception):
    """Base Exception cho tất cả các lỗi được định nghĩa trong pipeline."""
    def __init__(self, message: str, category: ErrorCategory):
        super().__init__(message)
        self.message = message
        self.category = category


class LLMAPIError(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, ErrorCategory.API_ERROR)


class JSONParseError(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, ErrorCategory.JSON_PARSE_ERROR)


class SchemaValidationError(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, ErrorCategory.SCHEMA_ERROR)


class SemanticValidationError(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, ErrorCategory.SEMANTIC_ERROR)


class EvidenceValidationError(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, ErrorCategory.EVIDENCE_ERROR)


class RetryExhaustedError(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, ErrorCategory.RETRY_EXHAUSTED)
