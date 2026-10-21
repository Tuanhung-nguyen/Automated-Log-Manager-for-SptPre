from pydantic import BaseModel
from .records import ExecutionRecord


class AggregatedMetrics(BaseModel):
    """
    Data Contract cho tầng Observability / Analytics:
    Tổng hợp toàn bộ chỉ số vận hành từ danh sách ExecutionRecord.
    """
    # Execution
    total_executions: int
    incident_count: int
    skipped_count: int
    success_count: int
    human_review_count: int

    # Attempts / Retry
    total_attempts: int
    retry_count: int
    average_attempts: float

    # Latency
    average_total_duration_ms: float
    average_detect_duration_ms: float
    average_llm_duration_ms: float
    average_validation_duration_ms: float

    # Errors
    error_categories: dict[str, int]


class MetricsAggregator:
    """
    Tầng Analytics / Observability (Phase 4):
    Nhận vào danh sách ExecutionRecord và tổng hợp các metrics vận hành hệ thống.
    Đảm bảo tính đơn nhiệm: Không gọi Detector, không gọi LLM, không retry.
    """

    def aggregate(
        self,
        executions: list[ExecutionRecord]
    ) -> AggregatedMetrics:

        total_executions = len(executions)

        incident_count = sum(
            1 for execution in executions
            if execution.detect_output
        )

        skipped_count = sum(
            1 for execution in executions
            if execution.final_status == "SKIPPED"
        )

        success_count = sum(
            1 for execution in executions
            if execution.final_status == "SUCCESS"
        )

        human_review_count = sum(
            1 for execution in executions
            if execution.final_status == "HUMAN_REVIEW_REQUIRED"
        )

        total_attempts = sum(
            len(execution.attempts)
            for execution in executions
        )

        retry_count = sum(
            1 for execution in executions
            if len(execution.attempts) > 1
        )

        average_attempts = (
            total_attempts / total_executions
            if total_executions > 0
            else 0.0
        )

        average_total_duration_ms = (
            sum(execution.total_duration_ms for execution in executions)
            / total_executions
            if total_executions > 0
            else 0.0
        )

        average_detect_duration_ms = (
            sum(execution.detect_duration_ms for execution in executions)
            / total_executions
            if total_executions > 0
            else 0.0
        )

        llm_durations = [
            attempt.llm_duration_ms
            for execution in executions
            for attempt in execution.attempts
            if attempt.llm_duration_ms is not None
        ]

        validation_durations = [
            attempt.validation_duration_ms
            for execution in executions
            for attempt in execution.attempts
            if attempt.validation_duration_ms is not None
        ]

        average_llm_duration_ms = (
            sum(llm_durations) / len(llm_durations)
            if llm_durations
            else 0.0
        )

        average_validation_duration_ms = (
            sum(validation_durations) / len(validation_durations)
            if validation_durations
            else 0.0
        )

        error_categories: dict[str, int] = {}

        for execution in executions:
            for attempt in execution.attempts:

                if attempt.validation_result == "FAILED":
                    if attempt.error_category:
                        category = attempt.error_category
                    else:
                        error_lower = (attempt.validation_error or "UNKNOWN").lower()
                        if "schema" in error_lower:
                            category = "Schema Error"
                        elif "semantic" in error_lower:
                            category = "Semantic Error"
                        elif "evidence" in error_lower:
                            category = "Evidence Error"
                        elif "api" in error_lower:
                            category = "LLM/API Error"
                        else:
                            category = "Other"

                    error_categories[category] = (
                        error_categories.get(category, 0) + 1
                    )

        return AggregatedMetrics(
            total_executions=total_executions,
            incident_count=incident_count,
            skipped_count=skipped_count,
            success_count=success_count,
            human_review_count=human_review_count,

            total_attempts=total_attempts,
            retry_count=retry_count,
            average_attempts=round(average_attempts, 2),

            average_total_duration_ms=round(
                average_total_duration_ms, 2
            ),

            average_detect_duration_ms=round(
                average_detect_duration_ms, 2
            ),

            average_llm_duration_ms=round(
                average_llm_duration_ms, 2
            ),

            average_validation_duration_ms=round(
                average_validation_duration_ms, 2
            ),

            error_categories=error_categories
        )
