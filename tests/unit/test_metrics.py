import sys
from pathlib import Path

# Thêm project root vào sys.path để có thể chạy trực tiếp python tests/unit/test_metrics.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import IncidentContext, AnalysisResult
from app.pipeline import RetryController, AnalysisRunner, IncidentPipeline
from app.observability import MetricsAggregator, AggregatedMetrics, ExecutionRecord


class MockSuccessFirstAttemptAnalyzer:
    def analyze(self, context, feedback=None):
        return """
        {
            "component": "Spark",
            "error_type": "YARN memory limit exceeded",
            "severity": "HIGH",
            "facts": ["Container killed by YARN for exceeding memory limit."],
            "inferences": ["Executor reached memory limit"],
            "possible_causes": ["Memory limit too low"],
            "recommendation": "Increase spark.executor.memory",
            "confidence": 0.7
        }
        """


class MockFailThenSuccessAnalyzer:
    def __init__(self):
        self.attempt = 0

    def analyze(self, context, feedback=None):
        self.attempt += 1
        if self.attempt == 1:
            return '{"component": "Spark", "error_type": "ExecutorLostFailure"}'
        return """
        {
            "component": "Spark",
            "error_type": "YARN memory limit exceeded",
            "severity": "HIGH",
            "facts": ["Container killed by YARN for exceeding memory limit."],
            "inferences": ["Executor reached memory limit"],
            "possible_causes": ["Memory limit too low"],
            "recommendation": "Increase spark.executor.memory",
            "confidence": 0.7
        }
        """


def run_pipeline_executions():
    # 1. Execution 1: Normal Log -> SKIPPED (0 attempts)
    ctx1 = IncidentContext(
        timestamp="2026-09-17 14:00:00",
        component="Spark",
        error="None",
        log="Application finished successfully. Total 1,000,000 records processed."
    )
    pipe1 = IncidentPipeline(runner=AnalysisRunner(analyzer=MockSuccessFirstAttemptAnalyzer(), retry_controller=RetryController(max_attempts=3)))
    res1: AnalysisResult = pipe1.run(ctx1)

    # 2. Execution 2: Incident -> SUCCESS in Attempt 1 (1 attempt)
    ctx2 = IncidentContext(
        timestamp="2026-09-17 14:20:31",
        component="Spark",
        error="ExecutorLostFailure",
        log="Container killed by YARN for exceeding memory limit."
    )
    pipe2 = IncidentPipeline(runner=AnalysisRunner(analyzer=MockSuccessFirstAttemptAnalyzer(), retry_controller=RetryController(max_attempts=3)))
    res2: AnalysisResult = pipe2.run(ctx2)

    # 3. Execution 3: Incident -> Attempt 1 fail (Schema Error) -> Retry -> SUCCESS in Attempt 2 (2 attempts)
    ctx3 = IncidentContext(
        timestamp="2026-09-17 14:20:31",
        component="Spark",
        error="ExecutorLostFailure",
        log="Container killed by YARN for exceeding memory limit."
    )
    pipe3 = IncidentPipeline(runner=AnalysisRunner(analyzer=MockFailThenSuccessAnalyzer(), retry_controller=RetryController(max_attempts=3)))
    res3: AnalysisResult = pipe3.run(ctx3)

    return [res1.execution_record, res2.execution_record, res3.execution_record]


def test_metrics_aggregator():
    executions = run_pipeline_executions()
    aggregator = MetricsAggregator()
    metrics = aggregator.aggregate(executions)

    assert metrics.total_executions == 3
    assert metrics.incident_count == 2
    assert metrics.skipped_count == 1
    assert metrics.success_count == 2
    assert metrics.human_review_count == 0

    assert metrics.total_attempts == 3
    assert metrics.retry_count == 1
    assert metrics.average_attempts == 1.0

    assert metrics.error_categories.get("Schema Error") == 1
    print("=> test_metrics_aggregator PASSED!")


if __name__ == "__main__":
    test_metrics_aggregator()
