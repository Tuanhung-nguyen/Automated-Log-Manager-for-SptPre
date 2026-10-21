import time
from typing import Optional, Callable
from app.core import (
    IncidentContext,
    AnalysisResult,
    HumanReviewRecord,
    ErrorCategory,
    ToolCall,
)
from app.observability.records import AttemptRecord
from app.llm import LLMClient
from app.tools.loop import run_tool_loop


class AgentRunner:
    """
    AgentRunner (Phase 5 - Agentic Tool Calling Runner):
    Điều phối phân tích sự cố bằng Agent Tool Loop:
    - AI tự động chọn và gọi các tools điều tra (status, logs)
    - Tuân thủ Policy & Human Approval (ALLOW / REQUIRE_APPROVAL / DENY)
    - Tổng hợp kết quả thành IncidentAnalysis
    - Ghi nhận telemetry (tool_calls, duration) cho Observability
    """

    def __init__(
        self,
        client: Optional[LLMClient] = None,
        max_iterations: int = 4,
        approval_callback: Optional[Callable[[ToolCall], bool]] = None
    ):
        self.client = client or LLMClient(model="qwen3:8b", timeout=600, temperature=0.0)
        self.max_iterations = max_iterations
        self.approval_callback = approval_callback

    def run(
        self,
        context: IncidentContext
    ) -> tuple[AnalysisResult, list[AttemptRecord], list[dict]]:
        t_start = time.perf_counter()

        # Tạo context text tổng hợp từ IncidentContext
        context_text = f"""
Component: {context.component}
Error sơ bộ: {context.error}
Log sơ bộ: {context.log}
Timestamp: {context.timestamp}
"""
        if context.metrics:
            context_text += f"Metrics: {context.metrics}\n"

        # Kích hoạt Agent Tool Loop
        loop_output = run_tool_loop(
            context=context_text,
            client=self.client,
            max_iterations=self.max_iterations,
            approval_callback=self.approval_callback
        )

        duration_ms = (time.perf_counter() - t_start) * 1000

        # Chuyển đổi lịch sử tools thành định dạng telemetry
        tool_telemetry = []
        for tc, tr in loop_output.get("tool_history", []):
            tool_telemetry.append({
                "tool_name": tc.tool_name,
                "arguments": tc.arguments,
                "result": tr.result
            })

        # Đóng gói AttemptRecord phục vụ metrics
        attempt_record = AttemptRecord(
            attempt=1,
            llm_output=None,
            llm_duration_ms=round(duration_ms, 2),
            validation_result="PASSED" if loop_output.get("success") else "FAILED",
            validation_error=None if loop_output.get("success") else "Agent tool loop did not produce final analysis",
            error_category=None if loop_output.get("success") else "Agent Loop Error",
            validation_duration_ms=0.0,
            feedback=None,
            status="SUCCESS" if loop_output.get("success") else "FAILED",
            duration_ms=round(duration_ms, 2)
        )

        if loop_output.get("success") and loop_output.get("analysis"):
            analysis = loop_output["analysis"]
            result = AnalysisResult(
                status="SUCCESS",
                analysis=analysis
            )
        else:
            human_review = HumanReviewRecord(
                status="HUMAN_REVIEW_REQUIRED",
                attempts=loop_output.get("iterations", self.max_iterations),
                reason="Agent tool loop could not reach final analysis within max iterations",
                error_category=ErrorCategory.UNKNOWN_ERROR,
                context=context
            )
            result = AnalysisResult(
                status="HUMAN_REVIEW_REQUIRED",
                human_review=human_review
            )

        return result, [attempt_record], tool_telemetry
