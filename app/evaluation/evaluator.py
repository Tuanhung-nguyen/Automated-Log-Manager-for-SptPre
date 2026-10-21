from pydantic import BaseModel
from typing import Optional
from app.core.models import AnalysisResult
from app.evaluation.benchmark import BenchmarkCase


class EvaluationResult(BaseModel):
    """Kết quả đối chiếu tự động giữa phân tích thực tế và Ground Truth."""
    case_id: str
    detector_correct: bool
    error_type_correct: Optional[bool] = None
    facts_correct: Optional[bool] = None
    overall_pass: bool


TAXONOMY_KEYWORDS: dict[str, list[str]] = {
    "MEMORY_LIMIT_EXCEEDED": ["memory", "oom", "exceed", "executorlost"],
    "KAFKA_CONSUMER_LAG": ["lag", "consumer"],
    "DB_CONNECTION_POOL_EXHAUSTED": ["connection", "pool", "exhaust"],
    "PIPELINE_TIMEOUT": ["timeout", "timed out", "exceeded"],
    "DISK_FULL": ["disk", "space", "device"],
    "SCHEMA_VALIDATION_FAILED": ["schema", "type", "validation"],
    "CONNECTION_ERROR": ["connection", "host", "resolve", "dns", "nameresolutionerror", "network"],
}


class BenchmarkEvaluator:
    """
    Evaluator đánh giá tự động dựa trên Ground Truth (Phase 4):
    Đối chiếu kết quả phân tích của hệ thống với đáp án chuẩn được định nghĩa trước.
    """

    def evaluate_case(
        self,
        case: BenchmarkCase,
        result: AnalysisResult
    ) -> EvaluationResult:
        gt = case.ground_truth
        rec = result.execution_record

        # 1. Đánh giá Detector
        detect_output = rec.detect_output if rec is not None else (result.status != "SKIPPED")

        if gt.incident:
            # Case sự cố: Detector phải bắt được (True) và status khác SKIPPED
            detector_correct = (detect_output is True) and (result.status != "SKIPPED")
        else:
            # Case bình thường: Detector phải trả False và status là SKIPPED
            detector_correct = (detect_output is False) and (result.status == "SKIPPED")

        # 2. Xử lý Case bình thường (Normal Log)
        if not gt.incident:
            return EvaluationResult(
                case_id=case.case_id,
                detector_correct=detector_correct,
                error_type_correct=None,
                facts_correct=None,
                overall_pass=detector_correct
            )

        # 3. Xử lý Case sự cố (Incident)
        # Nếu detector sai hoặc không thành công phân tích -> FAIL các chỉ số sau
        if not detector_correct or result.status != "SUCCESS" or not result.analysis:
            return EvaluationResult(
                case_id=case.case_id,
                detector_correct=detector_correct,
                error_type_correct=False,
                facts_correct=False,
                overall_pass=False
            )

        analysis = result.analysis

        # 3.1. So khớp Error Type
        error_type_correct = self._match_error_type(gt.error_type, analysis.error_type)

        # 3.2. So khớp Required Facts
        facts_correct = self._match_facts(gt.required_facts, analysis.facts)

        overall_pass = detector_correct and error_type_correct and facts_correct

        return EvaluationResult(
            case_id=case.case_id,
            detector_correct=detector_correct,
            error_type_correct=error_type_correct,
            facts_correct=facts_correct,
            overall_pass=overall_pass
        )

    def _match_error_type(self, expected_type: str | None, actual_type: str) -> bool:
        if not expected_type:
            return True

        expected_upper = expected_type.upper()
        actual_lower = actual_type.lower()

        # Kiểm tra khớp chính xác taxonomy
        if expected_upper in actual_type.upper():
            return True

        # Kiểm tra từ khóa đặc trưng của taxonomy
        keywords = TAXONOMY_KEYWORDS.get(expected_upper, [])
        if any(kw in actual_lower for kw in keywords):
            return True

        return False

    def _match_facts(self, required_facts: list[str], actual_facts: list[str]) -> bool:
        if not required_facts:
            return True

        actual_combined = " ".join(actual_facts).lower()
        for req in required_facts:
            if req.lower() not in actual_combined:
                return False
        return True

    def aggregate_benchmark_results(
        self,
        evaluations: list[EvaluationResult]
    ) -> dict:
        """
        Tổng hợp tỷ lệ chính xác trên toàn bộ benchmark suite.
        Lưu ý: Báo cáo đây là kết quả trên synthetic benchmark, không phải accuracy production.
        """
        total = len(evaluations)
        if total == 0:
            return {}

        detector_passes = sum(1 for e in evaluations if e.detector_correct)
        
        # Chỉ tính accuracy error_type và facts trên các case sự cố (có error_type_correct != None)
        incident_evals = [e for e in evaluations if e.error_type_correct is not None]
        incident_total = len(incident_evals)

        error_type_passes = sum(1 for e in incident_evals if e.error_type_correct)
        facts_passes = sum(1 for e in incident_evals if e.facts_correct)

        overall_passes = sum(1 for e in evaluations if e.overall_pass)

        return {
            "total_cases": total,
            "incident_cases": incident_total,
            "detector_score": f"{detector_passes}/{total}",
            "detector_accuracy": round(detector_passes / total, 2),
            "error_type_score": f"{error_type_passes}/{incident_total}" if incident_total > 0 else "N/A",
            "error_type_accuracy": round(error_type_passes / incident_total, 2) if incident_total > 0 else 0.0,
            "facts_score": f"{facts_passes}/{incident_total}" if incident_total > 0 else "N/A",
            "facts_accuracy": round(facts_passes / incident_total, 2) if incident_total > 0 else 0.0,
            "overall_score": f"{overall_passes}/{total}",
            "overall_pass_rate": round(overall_passes / total, 2),
            "note": "Kết quả được đo lường trên Synthetic Benchmark 7 cases (Phase 4), chưa phải production accuracy."
        }
