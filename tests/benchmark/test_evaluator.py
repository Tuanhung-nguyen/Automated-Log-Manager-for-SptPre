import sys
from pathlib import Path

# Thêm project root vào sys.path để có thể chạy trực tiếp python tests/benchmark/test_evaluator.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
from app.core import IncidentContext, AnalysisResult
from app.evaluation import BENCHMARK_CASES, BenchmarkEvaluator, EvaluationResult
from app.pipeline import RetryController, AnalysisRunner, IncidentPipeline


CASE_RESPONSES = {
    "CASE_01": """
    {
        "component": "Spark",
        "error_type": "YARN memory limit exceeded",
        "severity": "HIGH",
        "facts": ["Container killed by YARN for exceeding memory limit.", "Container memory used: 8192 MB"],
        "inferences": ["Executor reached physical memory limit"],
        "possible_causes": ["Memory limit too low"],
        "recommendation": "Increase spark.executor.memory",
        "confidence": 0.7
    }
    """,
    "CASE_02": """
    {
        "component": "Kafka Consumer",
        "error_type": "Kafka consumer lag increasing",
        "severity": "MEDIUM",
        "facts": ["Current lag: 250000 messages.", "producer rate is 3500 msg/s"],
        "inferences": ["Consumer cannot keep up with producer rate"],
        "possible_causes": ["Slow downstream processing"],
        "recommendation": "Scale consumer group instances",
        "confidence": 0.7
    }
    """,
    "CASE_03": """
    {
        "component": "Application Database",
        "error_type": "Database connection pool exhausted",
        "severity": "HIGH",
        "facts": ["Connection pool is exhausted", "Active connections: 100", "Requests waiting: 47"],
        "inferences": ["Database connection limit reached"],
        "possible_causes": ["Connection leak or traffic spike"],
        "recommendation": "Increase maximum pool size",
        "confidence": 0.7
    }
    """,
    "CASE_04": """
    {
        "component": "ETL Pipeline",
        "error_type": "Pipeline execution timeout",
        "severity": "MEDIUM",
        "facts": ["Pipeline exceeded configured execution timeout", "Actual execution time: 47 minutes"],
        "inferences": ["Job took longer than the 30 minutes threshold"],
        "possible_causes": ["Data volume increase"],
        "recommendation": "Optimize pipeline stages or increase timeout",
        "confidence": 0.7
    }
    """,
    "CASE_05": """
    {
        "component": "Spark Worker",
        "error_type": "No space left on device (Disk full)",
        "severity": "CRITICAL",
        "facts": ["Failed to write shuffle data", "No space left on device", "Disk usage: 99%"],
        "inferences": ["Disk space exhausted during shuffle"],
        "possible_causes": ["Insufficient worker disk volume"],
        "recommendation": "Clean up disk and add more storage",
        "confidence": 0.7
    }
    """,
    "CASE_06": """
    {
        "component": "Data Ingestion",
        "error_type": "Schema validation failed",
        "severity": "HIGH",
        "facts": ["Schema validation failed for column user_id", "Expected type: integer, received type: string"],
        "inferences": ["Type mismatch during ingestion"],
        "possible_causes": ["Upstream format change"],
        "recommendation": "Fix source data format or update schema",
        "confidence": 0.7
    }
    """,
    "CASE_08": """
    {
        "component": "Databricks Workspace Integration",
        "error_type": "ConnectionError",
        "severity": "HIGH",
        "facts": ["dbc-725afd95-6af4.cloud.databricks.com%0a", "NameResolutionError", "/api/2.0/workspace/mkdirs"],
        "inferences": ["Databricks workspace host contains invalid characters causing DNS failure"],
        "possible_causes": ["Newline character %0a in Databricks host configuration"],
        "recommendation": "Remove trailing newline from DATABRICKS_HOST secret",
        "confidence": 0.9
    }
    """
}


class MockBenchmarkAnalyzer:
    def __init__(self, case_id: str):
        self.case_id = case_id

    def analyze(self, context, feedback=None):
        return CASE_RESPONSES.get(self.case_id, "{}")


def test_benchmark_evaluator():
    print("=" * 80)
    print("   PHASE 4 & 6: CHẠY BENCHMARK EVALUATOR TRÊN 8 BENCHMARK CASES (CẢ CASE THẬT)")
    print("=" * 80)

    evaluator = BenchmarkEvaluator()
    evaluation_results: list[EvaluationResult] = []

    for case in BENCHMARK_CASES:
        runner = AnalysisRunner(
            analyzer=MockBenchmarkAnalyzer(case.case_id),
            retry_controller=RetryController(max_attempts=3)
        )
        pipeline = IncidentPipeline(runner=runner)

        # Chạy pipeline lấy kết quả
        result = pipeline.run(case.context)

        # Đánh giá bằng BenchmarkEvaluator
        eval_res = evaluator.evaluate_case(case, result)
        evaluation_results.append(eval_res)

        print(f"\n[{case.case_id}] {case.description}")
        print(f"  • Detector Correct  : {eval_res.detector_correct}")
        print(f"  • Error Type Correct: {eval_res.error_type_correct}")
        print(f"  • Facts Correct     : {eval_res.facts_correct}")
        print(f"  • Overall Pass      : {eval_res.overall_pass}")

    # Tổng hợp metrics benchmark
    summary = evaluator.aggregate_benchmark_results(evaluation_results)

    print("\n" + "=" * 80)
    print("           TỔNG HỢP KẾT QUẢ ĐÁNH GIÁ (BENCHMARK 8 CASES)")
    print("=" * 80)
    print(f"Tổng số case      : {summary['total_cases']}")
    print(f"Detector          : {summary['detector_score']} (Accuracy: {summary['detector_accuracy'] * 100}%)")
    print(f"Error Type        : {summary['error_type_score']} (Accuracy: {summary['error_type_accuracy'] * 100}%)")
    print(f"Facts / Evidence  : {summary['facts_score']} (Accuracy: {summary['facts_accuracy'] * 100}%)")
    print(f"Overall Pass      : {summary['overall_score']} (Pass Rate: {summary['overall_pass_rate'] * 100}%)")
    print(f"Ghi chú           : {summary['note']}")
    print("=" * 80)

    # Assertions
    assert summary["detector_accuracy"] == 1.0
    assert summary["error_type_accuracy"] == 1.0
    assert summary["facts_accuracy"] == 1.0
    assert summary["overall_pass_rate"] == 1.0
    print("\n=> TẤT CẢ 8 BENCHMARK CASES ĐÃ ĐƯỢC EVALUATE CHUẨN XÁC 100%!")


if __name__ == "__main__":
    test_benchmark_evaluator()
