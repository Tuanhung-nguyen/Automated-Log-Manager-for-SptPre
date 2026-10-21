import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
from app.core import IncidentContext, AnalysisResult
from app.observability import ExecutionRecord, AggregatedMetrics, MetricsAggregator
from app.evaluation import BENCHMARK_CASES, BenchmarkEvaluator, EvaluationResult
from app.pipeline import (
    IncidentPipeline,
    AnalysisRunner,
    IncidentAnalyzer,
    RetryController,
    AgentRunner,
)
from app.llm import LLMClient


# =====================================================================
# MOCK ANALYZERS ĐỂ TEST 3 CASE OBSERVABILITY CỦA PHASE 4
# =====================================================================
class MockSuccessFirstAttemptAnalyzer:
    """Case 2: Thành công ngay từ lần 1 (1 attempt duy nhất)"""
    def analyze(self, context, feedback=None):
        return """
        {
            "component": "Spark",
            "error_type": "YARN memory limit exceeded",
            "severity": "HIGH",
            "facts": [
                "Container killed by YARN for exceeding memory limit."
            ],
            "inferences": ["Executor reached memory limit"],
            "possible_causes": ["Memory limit too low"],
            "recommendation": "Increase spark.executor.memory",
            "confidence": 0.7
        }
        """


class MockFailThenSuccessAnalyzer:
    """Case 3: Attempt 1 fail validation -> Nhận feedback -> Attempt 2 thành công"""
    def __init__(self):
        self.attempt = 0

    def analyze(self, context, feedback=None):
        self.attempt += 1

        # Attempt 1: Thiếu trường bắt buộc (Schema Error)
        if self.attempt == 1:
            return '{"component": "Spark", "error_type": "ExecutorLostFailure"}'

        # Attempt 2: Sửa lỗi thành công
        return """
        {
            "component": "Spark",
            "error_type": "YARN memory limit exceeded",
            "severity": "HIGH",
            "facts": [
                "Container killed by YARN for exceeding memory limit."
            ],
            "inferences": ["Executor reached memory limit"],
            "possible_causes": ["Memory limit too low"],
            "recommendation": "Increase spark.executor.memory",
            "confidence": 0.7
        }
        """


# =====================================================================
# 3 TEST CASES KIỂM CHỨNG OBSERVABILITY & EXECUTION RECORD
# =====================================================================
def test_case_1_normal_log():
    print("=" * 80)
    print(" TEST 1: NORMAL LOG -> SKIPPED -> attempts = []")
    print("=" * 80)

    context = IncidentContext(
        timestamp="2026-09-17 14:00:00",
        component="Spark",
        error="None",
        log="Application finished successfully. Total 1,000,000 records processed."
    )

    runner = AnalysisRunner(
        analyzer=MockSuccessFirstAttemptAnalyzer(),
        retry_controller=RetryController(max_attempts=3)
    )
    pipeline = IncidentPipeline(runner=runner)

    result: AnalysisResult = pipeline.run(context)
    rec: ExecutionRecord = result.execution_record

    print(f"\nResult Status    : {result.status}")
    print(f"Execution ID     : {rec.execution_id}")
    print(f"Detect Output    : {rec.detect_output}")
    print(f"Detect Duration  : {rec.detect_duration_ms} ms")
    print(f"Attempts Count   : {len(rec.attempts)}")
    print(f"Total Duration   : {rec.total_duration_ms} ms")

    # Kiểm tra assertions
    assert result.status == "SKIPPED"
    assert rec.final_status == "SKIPPED"
    assert rec.detect_output is False
    assert len(rec.attempts) == 0
    print("\n=> TEST 1 PASSED: Fast-filter SKIPPED chính xác, attempts rỗng!")
    return rec


def test_case_2_success_first_attempt():
    print("\n" + "=" * 80)
    print(" TEST 2: INCIDENT + LLM THÀNH CÔNG LẦN ĐẦU -> attempts = [attempt 1]")
    print("=" * 80)

    context = IncidentContext(
        timestamp="2026-09-17 14:20:31",
        component="Spark",
        error="ExecutorLostFailure",
        log="Container killed by YARN for exceeding memory limit."
    )

    runner = AnalysisRunner(
        analyzer=MockSuccessFirstAttemptAnalyzer(),
        retry_controller=RetryController(max_attempts=3)
    )
    pipeline = IncidentPipeline(runner=runner)

    result: AnalysisResult = pipeline.run(context)
    rec: ExecutionRecord = result.execution_record

    print(f"\nResult Status    : {result.status}")
    print(f"Execution ID     : {rec.execution_id}")
    print(f"Detect Output    : {rec.detect_output}")
    print(f"Attempts Count   : {len(rec.attempts)}")
    for att in rec.attempts:
        print(f"  • Attempt {att.attempt}: status={att.status}, ValResult={att.validation_result}, LLM={att.llm_duration_ms}ms, Val={att.validation_duration_ms}ms")
    print(f"Total Duration   : {rec.total_duration_ms} ms")

    # Kiểm tra assertions
    assert result.status == "SUCCESS"
    assert rec.final_status == "SUCCESS"
    assert rec.detect_output is True
    assert len(rec.attempts) == 1
    assert rec.attempts[0].attempt == 1
    assert rec.attempts[0].status == "SUCCESS"
    assert rec.attempts[0].validation_result == "PASSED"
    assert rec.attempts[0].validation_error is None
    print("\n=> TEST 2 PASSED: 1 Attempt duy nhất thành công, ExecutionRecord đầy đủ!")
    return rec


def test_case_3_fail_then_retry_success():
    print("\n" + "=" * 80)
    print(" TEST 3: INCIDENT + FAIL -> RETRY -> SUCCESS -> attempts = [att 1, att 2]")
    print("=" * 80)

    context = IncidentContext(
        timestamp="2026-09-17 14:20:31",
        component="Spark",
        error="ExecutorLostFailure",
        log="Container killed by YARN for exceeding memory limit."
    )

    runner = AnalysisRunner(
        analyzer=MockFailThenSuccessAnalyzer(),
        retry_controller=RetryController(max_attempts=3)
    )
    pipeline = IncidentPipeline(runner=runner)

    result: AnalysisResult = pipeline.run(context)
    rec: ExecutionRecord = result.execution_record

    print(f"\nResult Status    : {result.status}")
    print(f"Execution ID     : {rec.execution_id}")
    print(f"Attempts Count   : {len(rec.attempts)}")
    for att in rec.attempts:
        print(f"\n  [ATTEMPT {att.attempt}]:")
        print(f"   - Status           : {att.status}")
        print(f"   - Val Result       : {att.validation_result}")
        print(f"   - Val Error        : {att.validation_error}")
        print(f"   - Feedback To Next : {att.feedback}")
        print(f"   - Total Attempt Ms : {att.duration_ms} ms")

    print(f"\nTotal Pipeline Duration: {rec.total_duration_ms} ms")

    # Kiểm tra assertions
    assert result.status == "SUCCESS"
    assert rec.final_status == "SUCCESS"
    assert len(rec.attempts) == 2

    # Attempt 1 phải FAILED
    att1 = rec.attempts[0]
    assert att1.attempt == 1
    assert att1.status == "FAILED"
    assert att1.validation_result == "FAILED"
    assert att1.validation_error is not None

    # Attempt 2 phải SUCCESS và nhận feedback từ Attempt 1
    att2 = rec.attempts[1]
    assert att2.attempt == 2
    assert att2.status == "SUCCESS"
    assert att2.validation_result == "PASSED"
    assert att2.feedback is not None  # Có feedback truyền từ attempt 1 sang

    print("\n=> TEST 3 PASSED: Lưu trọn vẹn lịch sử retry, feedback và kết quả từng attempt!")
    return rec


# =====================================================================
# PHASE 5: AGENT TOOL CALLING PIPELINE DEMOS (INVESTIGATION & APPROVAL)
# =====================================================================


class MockAgentInvestigateLLMClient:
    """Mock LLM mô phỏng thông minh cho Agent điều tra sự cố qua 2 công cụ (status & logs)."""
    def __init__(self):
        self.step = 0

    def generate(self, prompt: str) -> str:
        self.step += 1
        if self.step == 1:
            # Bước 1: AI quyết định kiểm tra trạng thái pipeline
            return json.dumps({
                "action": "tool_call",
                "tool_name": "get_pipeline_status",
                "arguments": {"pipeline_id": "pipe_orders_etl"}
            })
        elif self.step == 2:
            # Bước 2: AI nhận thấy pipeline FAILED, quyết định đọc log chi tiết
            return json.dumps({
                "action": "tool_call",
                "tool_name": "get_pipeline_logs",
                "arguments": {"pipeline_id": "pipe_orders_etl", "lines": 20}
            })
        else:
            # Bước 3: Đã đủ bằng chứng log, AI đưa ra kết luận phân tích cuối cùng
            return json.dumps({
                "action": "final_answer",
                "analysis": {
                    "component": "Spark",
                    "error_type": "OutOfMemoryError: Java heap space",
                    "severity": "CRITICAL",
                    "facts": [
                        "Job failed at step transform_daily_orders",
                        "Task failed with non-zero exit code (1)",
                        "OutOfMemoryError: Java heap space in executor 3"
                    ],
                    "inferences": [
                        "Spark executor ran out of heap memory during large daily orders transformation"
                    ],
                    "possible_causes": [
                        "Data skew in daily orders dataset",
                        "Executor memory setting too low"
                    ],
                    "recommendation": "Increase spark.executor.memory to 8G and investigate data skew key",
                    "confidence": 0.98
                }
            })


def run_phase5_agent_pipeline_demo():
    print("\n" + "=" * 80)
    print("   PHASE 5: AGENT TOOL CALLING PIPELINE (INTEGRATION DEMO)")
    print("=" * 80)
    print("Kịch bản: Pipeline dữ liệu 'pipe_orders_etl' gặp sự cố.")
    print("Mục tiêu: Agent tự chủ gọi Tool tra cứu -> Kiểm tra Policy -> Tổng hợp RCA.")

    # 1. Chuẩn bị ngữ cảnh sự cố sơ bộ
    context = IncidentContext(
        timestamp="2026-10-10 15:45:00",
        component="ETL Pipeline",
        error="Pipeline failure alert",
        log="Job pipe_orders_etl failed on step transform_daily_orders. Please investigate."
    )

    # 2. Khởi tạo AgentRunner và IncidentPipeline
    agent_client = MockAgentInvestigateLLMClient()
    agent_runner = AgentRunner(client=agent_client, max_iterations=4)
    pipeline = IncidentPipeline(runner=agent_runner)

    # 3. Kích hoạt toàn bộ Pipeline
    result: AnalysisResult = pipeline.run(context)
    rec: ExecutionRecord = result.execution_record

    print("\n" + "-" * 80)
    print("                KẾT QUẢ THỰC THI PIPELINE VỚI AGENT RUNNER")
    print("-" * 80)
    print(f"Pipeline Status      : {result.status}")
    print(f"Execution ID         : {rec.execution_id}")
    print(f"Detector Output      : {rec.detect_output} (Duration: {rec.detect_duration_ms} ms)")
    print(f"Total Duration       : {rec.total_duration_ms} ms")
    print(f"Số lượng Tool đã gọi : {len(rec.tool_calls)}")

    for idx, tc in enumerate(rec.tool_calls, 1):
        print(f"\n  [TOOL CALL {idx}]:")
        print(f"   • Tên tool       : {tc['tool_name']}")
        print(f"   • Tham số truyền : {tc['arguments']}")
        print(f"   • Trạng thái     : {tc['result'].get('status', 'OK')}")

    print("\n" + "-" * 80)
    print("                BÁO CÁO PHÂN TÍCH CUỐI CÙNG TỪ AGENT (RCA)")
    print("-" * 80)
    analysis = result.analysis
    print(f"• Thành phần gặp sự cố: {analysis.component}")
    print(f"• Loại lỗi xác định   : {analysis.error_type}")
    print(f"• Mức độ nghiêm trọng : {analysis.severity}")
    print(f"• Bằng chứng thực tế  : {analysis.facts}")
    print(f"• Suy luận của Agent  : {analysis.inferences}")
    print(f"• Đề xuất khắc phục   : {analysis.recommendation}")
    print(f"• Độ tự tin           : {analysis.confidence * 100}%")

    # Kiểm tra assertions
    assert result.status == "SUCCESS"
    assert len(rec.tool_calls) == 2
    assert rec.tool_calls[0]["tool_name"] == "get_pipeline_status"
    assert rec.tool_calls[1]["tool_name"] == "get_pipeline_logs"
    assert analysis.error_type == "OutOfMemoryError: Java heap space"

    print("\n=> DEMO PHASE 5 PASSED: Agent Pipeline hoàn toàn tự chủ điều tra và lập RCA! 🚀")
    return rec


def main():
    print("=" * 80)
    print("           HỆ THỐNG PHÂN TÍCH SỰ CỐ DATA ENGINEERING THÔNG MINH")
    print("=" * 80)

    # -----------------------------------------------------------------
    # PHẦN 1: PHASE 4 - KIỂM CHỨNG OBSERVABILITY & RETRY HISTORIES
    # -----------------------------------------------------------------
    print("\n[PHẦN 1] KIỂM CHỨNG OBSERVABILITY & RETRY TELEMETRY (PHASE 4)")
    rec1 = test_case_1_normal_log()
    rec2 = test_case_2_success_first_attempt()
    rec3 = test_case_3_fail_then_retry_success()

    print("\n--- TỔNG HỢP METRICS HỆ THỐNG TỪ 3 EXECUTION RECORDS ---")
    aggregator = MetricsAggregator()
    metrics: AggregatedMetrics = aggregator.aggregate([rec1, rec2, rec3])
    print(f"• Total Executions : {metrics.total_executions}")
    print(f"• Incident Count   : {metrics.incident_count} | Skipped: {metrics.skipped_count}")
    print(f"• Total Attempts   : {metrics.total_attempts} | Retries: {metrics.retry_count}")
    print(f"• Success Rate     : {metrics.success_count}/{metrics.incident_count}")

    # -----------------------------------------------------------------
    # PHẦN 2: PHASE 5 - AGENT PIPELINE VỚI TOOL CALLING VÀ POLICY
    # -----------------------------------------------------------------
    print("\n[PHẦN 2] KIỂM CHỨNG AGENT TOOL CALLING PIPELINE (PHASE 5)")
    rec_agent = run_phase5_agent_pipeline_demo()

    print("\n" + "=" * 80)
    print("  TẤT CẢ CÁC GIAI ĐOẠN (PHASE 4 & PHASE 5) ĐÃ TÍCH HỢP VÀ PASS 100%! 🎉")
    print("=" * 80)


def run_benchmark_evaluation():
    print("\n" + "=" * 80)
    print("   PHASE 4: GROUND TRUTH EVALUATION VỚI REAL LLM (QWEN3:8B OLLAMA)")
    print("=" * 80)

    # 1. Khởi tạo Pipeline tích hợp LLM thật (timeout 300s, temp 0.0)
    llm_client = LLMClient(model="qwen3:8b", timeout=300, temperature=0.0)
    analyzer = IncidentAnalyzer(llm_client=llm_client)
    runner = AnalysisRunner(analyzer=analyzer, retry_controller=RetryController(max_attempts=3))
    pipeline = IncidentPipeline(runner=runner)

    evaluator = BenchmarkEvaluator()
    evaluation_results: list[EvaluationResult] = []
    execution_records: list[ExecutionRecord] = []

    for case in BENCHMARK_CASES:
        print("\n" + "-" * 80)
        print(f"Đang xử lý: [{case.case_id}] {case.description}")
        print("-" * 80)

        # Chạy pipeline thật
        result = pipeline.run(case.context)
        if result.execution_record:
            execution_records.append(result.execution_record)

        # Chấm điểm tự động so với Ground Truth
        eval_res = evaluator.evaluate_case(case, result)
        evaluation_results.append(eval_res)

        print(f"\n=> KẾT QUẢ ĐÁNH GIÁ [{case.case_id}]:")
        print(f"  • Detector Correct  : {eval_res.detector_correct}")
        print(f"  • Error Type Correct: {eval_res.error_type_correct}")
        print(f"  • Facts Correct     : {eval_res.facts_correct}")
        print(f"  • Overall Pass      : {eval_res.overall_pass}")

    # 2. Tổng hợp báo cáo chất lượng (Accuracy Report)
    summary = evaluator.aggregate_benchmark_results(evaluation_results)

    print("\n" + "=" * 80)
    print("           TỔNG HỢP KẾT QUẢ ĐÁNH GIÁ (SYNTHETIC BENCHMARK 7 CASES)")
    print("=" * 80)
    print(f"Tổng số case      : {summary['total_cases']}")
    print(f"Detector          : {summary['detector_score']} (Accuracy: {summary['detector_accuracy'] * 100}%)")
    print(f"Error Type        : {summary['error_type_score']} (Accuracy: {summary['error_type_accuracy'] * 100}%)")
    print(f"Facts / Evidence  : {summary['facts_score']} (Accuracy: {summary['facts_accuracy'] * 100}%)")
    print(f"Overall Pass      : {summary['overall_score']} (Pass Rate: {summary['overall_pass_rate'] * 100}%)")
    print(f"Ghi chú           : {summary['note']}")
    print("=" * 80)

    # 3. Tổng hợp báo cáo vận hành (Operational Metrics)
    if execution_records:
        aggregator = MetricsAggregator()
        ops_metrics = aggregator.aggregate(execution_records)
        print("\n" + "=" * 80)
        print("           THỐNG KÊ VẬN HÀNH THỰC TẾ TRÊN 7 BENCHMARK CASES")
        print("=" * 80)
        print(f"Tổng executions       : {ops_metrics.total_executions}")
        print(f"Incident count        : {ops_metrics.incident_count} | Skipped: {ops_metrics.skipped_count}")
        print(f"Total attempts        : {ops_metrics.total_attempts} | Retries: {ops_metrics.retry_count}")
        print(f"Thời gian trung bình  : {ops_metrics.average_total_duration_ms} ms")
        print(f"LLM Latency trung bình: {ops_metrics.average_llm_duration_ms} ms")
        print(f"Val Latency trung bình: {ops_metrics.average_validation_duration_ms} ms")
        print(f"Error categories      : {ops_metrics.error_categories}")
        print("=" * 80)


if __name__ == "__main__":
    main()

