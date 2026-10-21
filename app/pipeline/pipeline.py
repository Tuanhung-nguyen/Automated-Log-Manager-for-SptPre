import sys
import uuid
import time
from datetime import datetime, timezone
from typing import Any
from app.core.models import IncidentContext, AnalysisResult
from app.observability.records import ExecutionRecord
from app.pipeline.detector import detect_incident
from app.pipeline.runner import AnalysisRunner

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class IncidentPipeline:
    """
    End-to-End Incident Analysis Pipeline (Phase 4 - Observability & Metrics):
    1. Tiếp nhận IncidentContext (log hệ thống).
    2. Bấm giờ toàn trình và đo Detector:
       - Nếu KHÔNG phát hiện sự cố -> Trả về AnalysisResult(status="SKIPPED") kèm ExecutionRecord.
       - Nếu CÓ sự cố -> Kích hoạt AnalysisRunner (thu thập từng AttemptRecord) -> Đóng gói ExecutionRecord hoàn chỉnh.
    """

    def __init__(self, runner: Any):
        self.runner = runner

    def run(self, context: IncidentContext) -> AnalysisResult:
        pipeline_start = time.perf_counter()
        execution_id = f"exec_{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        print("\n[PIPELINE] Bắt đầu xử lý IncidentContext...")

        # 1. Bước lọc nhanh qua Detector
        det_start = time.perf_counter()
        is_incident = detect_incident(context)
        detect_duration_ms = (time.perf_counter() - det_start) * 1000

        if not is_incident:
            print("[PIPELINE] Detector: Không phát hiện sự cố trong log/error -> SKIPPED (Bỏ qua LLM).")
            total_duration_ms = (time.perf_counter() - pipeline_start) * 1000

            record = ExecutionRecord(
                execution_id=execution_id,
                timestamp=timestamp,
                original_log=context,
                detect_output=False,
                detect_duration_ms=round(detect_duration_ms, 2),
                attempts=[],
                tool_calls=[],
                final_status="SKIPPED",
                final_result=None,
                total_duration_ms=round(total_duration_ms, 2)
            )
            return AnalysisResult(
                status="SKIPPED",
                execution_record=record
            )

        # 2. Có sự cố -> Chuyển giao cho Runner (AnalysisRunner hoặc AgentRunner)
        runner_name = self.runner.__class__.__name__
        print(f"[PIPELINE] Detector: Phát hiện dấu hiệu sự cố! Chuyển tiếp sang {runner_name}...")
        runner_output = self.runner.run(context)
        if len(runner_output) == 3:
            result, attempts, tool_calls = runner_output
        else:
            result, attempts = runner_output
            tool_calls = []

        total_duration_ms = (time.perf_counter() - pipeline_start) * 1000

        final_result_str = None
        if result.status == "SUCCESS" and result.analysis:
            final_result_str = result.analysis.error_type
        elif result.status == "HUMAN_REVIEW_REQUIRED" and result.human_review:
            final_result_str = result.human_review.reason

        record = ExecutionRecord(
            execution_id=execution_id,
            timestamp=timestamp,
            original_log=context,
            detect_output=True,
            detect_duration_ms=round(detect_duration_ms, 2),
            attempts=attempts,
            tool_calls=tool_calls,
            final_status=result.status,
            final_result=final_result_str,
            total_duration_ms=round(total_duration_ms, 2)
        )
        result.execution_record = record
        return result
