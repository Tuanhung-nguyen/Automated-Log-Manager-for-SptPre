import sys
import json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Đảm bảo import được module app từ thư mục gốc
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import IncidentContext, AnalysisResult
from app.pipeline import IncidentPipeline, AgentRunner
from app.tools.loop import run_tool_loop


class MockAgentLLMClient:
    """Mock LLM để test tích hợp nhanh Pipeline + AgentRunner."""
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.idx = 0

    def generate(self, prompt: str) -> str:
        if self.idx < len(self.responses):
            resp = self.responses[self.idx]
            self.idx += 1
            return resp
        return json.dumps({
            "action": "final_answer",
            "analysis": {
                "component": "Database",
                "error_type": "Connection Timeout",
                "severity": "HIGH",
                "facts": ["Connection refused on port 5432"],
                "inferences": ["DB down or network issue"],
                "possible_causes": ["DB host unreachable"],
                "recommendation": "Check DB service",
                "confidence": 0.95
            }
        })


def test_incident_pipeline_with_agent_runner():
    print("=" * 80)
    print("   INTEGRATION TEST: INCIDENT PIPELINE + AGENT RUNNER (TOOL CALLING)")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # TEST 1: Log bình thường -> Detector SKIPPED (Không kích hoạt Agent)
    # -------------------------------------------------------------------------
    normal_context = IncidentContext(
        timestamp="2026-10-10 12:00:00",
        component="Spark",
        error="None",
        log="Application completed successfully with 100,000 records."
    )
    mock_client = MockAgentLLMClient([])
    agent_runner = AgentRunner(client=mock_client)
    pipeline = IncidentPipeline(runner=agent_runner)

    res_skipped: AnalysisResult = pipeline.run(normal_context)
    assert res_skipped.status == "SKIPPED"
    assert res_skipped.execution_record.detect_output is False
    assert len(res_skipped.execution_record.tool_calls) == 0
    print("\n[TEST 1 PASSED] Normal log -> Detector SKIPPED thành công!")

    # -------------------------------------------------------------------------
    # TEST 2: Có sự cố -> Detector chuyển tiếp sang AgentRunner -> Tool Loop chạy!
    # -------------------------------------------------------------------------
    incident_context = IncidentContext(
        timestamp="2026-10-10 12:15:00",
        component="ETL Pipeline",
        error="Pipeline failure alert",
        log="Job etl_users failed unexpectedly. Check status and logs."
    )

    # Mô phỏng phản hồi từng vòng của Agent:
    # Vòng 1: Gọi get_pipeline_status
    # Vòng 2: Gọi get_pipeline_logs
    # Vòng 3: Kết luận final_answer
    responses = [
        json.dumps({
            "action": "tool_call",
            "tool_name": "get_pipeline_status",
            "arguments": {"pipeline_id": "etl_users"}
        }),
        json.dumps({
            "action": "tool_call",
            "tool_name": "get_pipeline_logs",
            "arguments": {"pipeline_id": "etl_users"}
        }),
        json.dumps({
            "action": "final_answer",
            "analysis": {
                "component": "PostgreSQL",
                "error_type": "Database Connection Timeout",
                "severity": "CRITICAL",
                "facts": [
                    "Database connection timeout after 30s",
                    "Connection refused on port 5432"
                ],
                "inferences": ["Database server is unreachable or port 5432 blocked"],
                "possible_causes": ["DB host down", "Firewall rules"],
                "recommendation": "Restart database service and check firewall port 5432",
                "confidence": 0.98
            }
        })
    ]
    agent_client = MockAgentLLMClient(responses)
    active_agent_runner = AgentRunner(client=agent_client, max_iterations=4)
    active_pipeline = IncidentPipeline(runner=active_agent_runner)

    res_incident: AnalysisResult = active_pipeline.run(incident_context)
    rec = res_incident.execution_record

    print(f"\n[PIPELINE OUTPUT]:")
    print(f"  • Final Status       : {res_incident.status}")
    print(f"  • Detect Output      : {rec.detect_output}")
    print(f"  • Detect Duration    : {rec.detect_duration_ms} ms")
    print(f"  • Total Duration     : {rec.total_duration_ms} ms")
    print(f"  • Tool Calls Count   : {len(rec.tool_calls)}")
    for idx, tc in enumerate(rec.tool_calls, 1):
        print(f"     Tool {idx}: {tc['tool_name']} -> {tc['result']['success']}")

    print(f"\n[AI FINAL ANALYSIS]:")
    print(f"  • Component          : {res_incident.analysis.component}")
    print(f"  • Error Type         : {res_incident.analysis.error_type}")
    print(f"  • Severity           : {res_incident.analysis.severity}")
    print(f"  • Facts              : {res_incident.analysis.facts}")
    print(f"  • Recommendation     : {res_incident.analysis.recommendation}")

    # Assertions
    assert res_incident.status == "SUCCESS"
    assert rec.detect_output is True
    assert len(rec.tool_calls) == 2
    assert rec.tool_calls[0]["tool_name"] == "get_pipeline_status"
    assert rec.tool_calls[1]["tool_name"] == "get_pipeline_logs"
    assert res_incident.analysis.error_type == "Database Connection Timeout"

    print("\n=> TEST 2 PASSED: Pipeline đã tích hợp hoàn hảo AgentRunner + Tool Loop! 🎉")


if __name__ == "__main__":
    test_incident_pipeline_with_agent_runner()
