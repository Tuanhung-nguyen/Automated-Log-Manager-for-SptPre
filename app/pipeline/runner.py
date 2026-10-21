import time
from app.core.models import (
    IncidentContext,
    IncidentAnalysis,
    HumanReviewRecord,
    AnalysisResult,
)
from app.core.exceptions import (
    JSONParseError,
    SchemaValidationError,
    SemanticValidationError,
    EvidenceValidationError,
    LLMAPIError,
    PipelineError,
    ErrorCategory,
)
from app.observability.records import AttemptRecord
from app.pipeline.analyzer import IncidentAnalyzer
from app.pipeline.retry import RetryController
from app.validation.validator import (
    validate_llm_response,
    validate_semantics,
    build_feedback,
)


class AnalysisRunner:
    """
    AnalysisRunner điều phối toàn bộ flow phân tích sự cố:
    Phân loại lỗi thông minh (Smart Retry Decision):
    - Lỗi do LLM (JSON, Schema, Semantic, Evidence) -> RETRY kèm Feedback
    - Lỗi mạng / API (LLMAPIError) -> RETRY mạng (không gửi feedback sai JSON)
    - Lỗi bất ngờ (Unknown Exception / Python bug) -> DỪNG NGAY (Fatal)
    """

    def __init__(
        self,
        analyzer: IncidentAnalyzer,
        retry_controller: RetryController
    ):
        self.analyzer = analyzer
        self.retry_controller = retry_controller

    def run(
        self,
        context: IncidentContext
    ) -> tuple[AnalysisResult, list[AttemptRecord]]:
        feedback = None
        last_error = None
        last_response = None
        attempts: list[AttemptRecord] = []

        for attempt in range(1, self.retry_controller.max_attempts + 1):
            t_attempt_start = time.perf_counter()
            print(f"\n[ANALYSIS] Attempt {attempt}/{self.retry_controller.max_attempts}")

            t_llm_start = None
            t_val_start = None
            llm_output = None
            llm_duration_ms = None
            validation_result = None
            validation_error = None
            validation_duration_ms = None
            attempt_status = "FAILED"
            current_feedback = feedback

            try:
                # 1. Gọi LLM Analyzer (có thể kèm feedback từ lần thử trước)
                t_llm_start = time.perf_counter()
                raw_response = self.analyzer.analyze(
                    context,
                    feedback=feedback
                )
                llm_duration_ms = (time.perf_counter() - t_llm_start) * 1000
                llm_output = raw_response
                last_response = raw_response

                # 2. Validate cú pháp JSON & Schema Pydantic
                t_val_start = time.perf_counter()
                analysis = validate_llm_response(raw_response)

                # 3. Validate logic Semantic & khớp Evidence với Context
                validate_semantics(context, analysis)
                validation_duration_ms = (time.perf_counter() - t_val_start) * 1000
                validation_result = "PASSED"
                attempt_status = "SUCCESS"

                attempt_duration_ms = (time.perf_counter() - t_attempt_start) * 1000
                attempts.append(
                    AttemptRecord(
                        attempt=attempt,
                        llm_output=llm_output,
                        llm_duration_ms=round(llm_duration_ms, 2) if llm_duration_ms is not None else None,
                        validation_result=validation_result,
                        validation_error=None,
                        validation_duration_ms=round(validation_duration_ms, 2) if validation_duration_ms is not None else None,
                        feedback=current_feedback,
                        status=attempt_status,
                        duration_ms=round(attempt_duration_ms, 2)
                    )
                )

                # 4. Khi vượt qua toàn bộ Guardrails -> Trả về AnalysisResult SUCCESS và attempts
                print("[ANALYSIS] Validation passed.")
                return AnalysisResult(
                    status="SUCCESS",
                    analysis=analysis
                ), attempts

            # NHÁNH 1: Lỗi do LLM sinh sai -> RETRY kèm Feedback cụ thể
            except (JSONParseError, SchemaValidationError, SemanticValidationError, EvidenceValidationError) as e:
                val_duration = (time.perf_counter() - t_val_start) * 1000 if t_val_start is not None else None
                validation_result = "FAILED"
                validation_error = str(e)
                attempt_status = "FAILED"
                last_error = e
                print(f"[RETRYABLE - {e.category.value}] {e}")
                feedback = build_feedback(e)

                attempt_duration_ms = (time.perf_counter() - t_attempt_start) * 1000
                attempts.append(
                    AttemptRecord(
                        attempt=attempt,
                        llm_output=llm_output,
                        llm_duration_ms=round(llm_duration_ms, 2) if llm_duration_ms is not None else None,
                        validation_result=validation_result,
                        validation_error=validation_error,
                        error_category=e.category.value,
                        validation_duration_ms=round(val_duration, 2) if val_duration is not None else None,
                        feedback=current_feedback,
                        status=attempt_status,
                        duration_ms=round(attempt_duration_ms, 2)
                    )
                )

            # NHÁNH 2: Lỗi mạng / Ollama API -> RETRY kết nối (không tạo feedback validation)
            except LLMAPIError as e:
                llm_duration_ms = (time.perf_counter() - t_llm_start) * 1000 if t_llm_start is not None else None
                validation_result = None
                validation_error = str(e)
                attempt_status = "FAILED"
                last_error = e
                print(f"[RETRYABLE - {e.category.value}] {e}. Thử kết nối lại...")
                feedback = None  # Không gửi feedback validation vì LLM chưa kịp sinh output

                attempt_duration_ms = (time.perf_counter() - t_attempt_start) * 1000
                attempts.append(
                    AttemptRecord(
                        attempt=attempt,
                        llm_output=None,
                        llm_duration_ms=round(llm_duration_ms, 2) if llm_duration_ms is not None else None,
                        validation_result=None,
                        validation_error=validation_error,
                        error_category=e.category.value,
                        validation_duration_ms=None,
                        feedback=current_feedback,
                        status=attempt_status,
                        duration_ms=round(attempt_duration_ms, 2)
                    )
                )

            # NHÁNH 3: Lỗi code Python / Bug không lường trước -> DỪNG NGAY LẬP TỨC
            except Exception as e:
                print(f"[FATAL - UNKNOWN] Phát hiện lỗi nội bộ: {e}")
                raise e

        # Hết số lần retry mà vẫn không thành công -> Chuyển sang HumanReviewRecord
        print(f"\n[ANALYSIS] Đã thử {self.retry_controller.max_attempts} lần không thành công. Chuyển sang Human Review.")

        error_category = (
            last_error.category
            if isinstance(last_error, PipelineError)
            else ErrorCategory.UNKNOWN_ERROR
        )
        validation_error_str = str(last_error) if last_error else None

        human_review = HumanReviewRecord(
            status="HUMAN_REVIEW_REQUIRED",
            attempts=self.retry_controller.max_attempts,
            reason=f"LLM validation failed after {self.retry_controller.max_attempts} attempts",
            error_category=error_category,
            validation_error=validation_error_str,
            last_llm_response=last_response,
            context=context
        )

        return AnalysisResult(
            status="HUMAN_REVIEW_REQUIRED",
            human_review=human_review
        ), attempts
