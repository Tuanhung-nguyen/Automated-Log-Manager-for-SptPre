import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import ToolCall, ToolResult
from app.tools.loop import run_tool_loop


class MockLLMClient:
    """Mock LLM Client mô phỏng chuỗi phản hồi từng vòng lặp."""
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.call_count = 0

    def generate(self, prompt: str) -> str:
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        # Phản hồi mặc định nếu vượt số lần
        return json.dumps({
            "action": "final_answer",
            "analysis": {
                "component": "ETL",
                "error_type": "Pipeline Failure",
                "severity": "HIGH",
                "facts": ["Pipeline failed"],
                "inferences": ["Failure observed"],
                "possible_causes": ["Unknown"],
                "recommendation": "Review logs",
                "confidence": 0.8
            }
        })


def test_loop_with_allow_tool():
    """Test Case 1: Tool READ được Policy đánh giá ALLOW -> Tự động chạy an toàn."""
    print("\n" + "=" * 70)
    print(" [TEST 1] AGENT LOOP VỚI TOOL READ (ALLOW)")
    print("=" * 70)

    # Vòng 1: LLM đề xuất get_pipeline_status
    # Vòng 2: LLM nhận kết quả và đưa ra final_answer
    mock_responses = [
        json.dumps({
            "action": "tool_call",
            "tool_name": "get_pipeline_status",
            "arguments": {"pipeline_id": "etl_users"}
        }),
        json.dumps({
            "action": "final_answer",
            "analysis": {
                "component": "Pipeline",
                "error_type": "Exit Code 1",
                "severity": "HIGH",
                "facts": ["Task failed with exit code 1"],
                "inferences": ["Pipeline failed"],
                "possible_causes": ["DB Timeout"],
                "recommendation": "Check detailed logs",
                "confidence": 0.9
            }
        })
    ]
    client = MockLLMClient(mock_responses)
    result = run_tool_loop(
        context="Pipeline etl_users đang có dấu hiệu lỗi",
        client=client,
        max_iterations=3
    )

    assert result["success"] is True
    assert len(result["tool_history"]) == 1
    call, res = result["tool_history"][0]
    assert call.tool_name == "get_pipeline_status"
    assert res.result["success"] is True
    assert res.result["result"]["pipeline_id"] == "etl_users"
    print("=> TEST 1 PASSED: Tool READ (ALLOW) tự động thực thi và nạp kết quả lại cho LLM!")


def test_loop_with_human_approval_rejected():
    """Test Case 2: Tool WRITE (REQUIRE_APPROVAL) bị Human REJECT -> Không chạy, báo lỗi cho LLM."""
    print("\n" + "=" * 70)
    print(" [TEST 2] AGENT LOOP VỚI TOOL WRITE -> HUMAN REJECT")
    print("=" * 70)

    # Vòng 1: LLM đề xuất restart_pipeline (WRITE)
    # Vòng 2: LLM nhận kết quả bị từ chối -> Đưa ra giải pháp thay thế
    mock_responses = [
        json.dumps({
            "action": "tool_call",
            "tool_name": "restart_pipeline",
            "arguments": {"pipeline_id": "etl_users"}
        }),
        json.dumps({
            "action": "final_answer",
            "analysis": {
                "component": "Pipeline",
                "error_type": "Manual Intervention Needed",
                "severity": "CRITICAL",
                "facts": ["Restart action was rejected by human operator"],
                "inferences": ["Operator decided not to restart automatically"],
                "possible_causes": ["Awaiting manual inspection"],
                "recommendation": "Escalate to on-call engineer",
                "confidence": 0.95
            }
        })
    ]
    client = MockLLMClient(mock_responses)

    # Human REJECT: callback trả về False
    def reject_all_approval(tool_call: ToolCall) -> bool:
        print(f"      [HUMAN DECISION] Người dùng TỪ CHỐI (REJECT) yêu cầu gọi: {tool_call.tool_name}")
        return False

    result = run_tool_loop(
        context="Khắc phục sự cố: Hãy thử khởi động lại pipeline etl_users",
        client=client,
        max_iterations=3,
        approval_callback=reject_all_approval
    )

    assert result["success"] is True
    assert len(result["tool_history"]) == 1
    call, res = result["tool_history"][0]
    assert call.tool_name == "restart_pipeline"
    # Tool KHÔNG ĐƯỢC CHẠY
    assert res.result["success"] is False
    assert "requires human approval and was rejected" in res.result["error"]
    print("=> TEST 2 PASSED: Tool WRITE bị chặn thành công khi Human REJECT!")


def test_loop_with_human_approval_approved():
    """Test Case 3: Tool WRITE (REQUIRE_APPROVAL) được Human APPROVE -> Thực thi và nạp kết quả cho LLM."""
    print("\n" + "=" * 70)
    print(" [TEST 3] AGENT LOOP VỚI TOOL WRITE -> HUMAN APPROVE")
    print("=" * 70)

    # Vòng 1: LLM đề xuất restart_pipeline (WRITE)
    # Vòng 2: LLM nhận kết quả restart thành công -> Hoàn tất báo cáo
    mock_responses = [
        json.dumps({
            "action": "tool_call",
            "tool_name": "restart_pipeline",
            "arguments": {"pipeline_id": "etl_users"}
        }),
        json.dumps({
            "action": "final_answer",
            "analysis": {
                "component": "Pipeline",
                "error_type": "Recovered",
                "severity": "LOW",
                "facts": ["Pipeline etl_users has been restarted with human approval"],
                "inferences": ["System recovered successfully"],
                "possible_causes": ["Transient glitch"],
                "recommendation": "Monitor next scheduled run",
                "confidence": 0.99
            }
        })
    ]
    client = MockLLMClient(mock_responses)

    # Human APPROVE: callback trả về True
    def approve_restart(tool_call: ToolCall) -> bool:
        print(f"      [HUMAN DECISION] Người dùng ĐỒNG Ý (APPROVE) yêu cầu gọi: {tool_call.tool_name}")
        return True

    result = run_tool_loop(
        context="Khắc phục sự cố: Hãy khởi động lại pipeline etl_users",
        client=client,
        max_iterations=3,
        approval_callback=approve_restart
    )

    assert result["success"] is True
    assert len(result["tool_history"]) == 1
    call, res = result["tool_history"][0]
    assert call.tool_name == "restart_pipeline"
    # Tool ĐÃ ĐƯỢC CHẠY THÀNH CÔNG
    assert res.result["success"] is True
    assert res.result["result"]["status"] == "RESTARTED"
    print("=> TEST 3 PASSED: Tool WRITE thực thi thành công sau khi Human APPROVE!")


def test_loop_with_deny_tool():
    """Test Case 4: Tool bị cấm (DENY) -> Chặn ngay lập tức, báo lỗi cho LLM."""
    print("\n" + "=" * 70)
    print(" [TEST 4] AGENT LOOP VỚI TOOL BỊ CẤM (DENY)")
    print("=" * 70)

    mock_responses = [
        json.dumps({
            "action": "tool_call",
            "tool_name": "delete_data",
            "arguments": {"target": "all"}
        }),
        json.dumps({
            "action": "final_answer",
            "analysis": {
                "component": "Security Guardrail",
                "error_type": "Prohibited Action",
                "severity": "CRITICAL",
                "facts": ["delete_data tool was denied by policy"],
                "inferences": ["Action violates policy"],
                "possible_causes": ["Destructive command attempt"],
                "recommendation": "Do not attempt destructive operations",
                "confidence": 1.0
            }
        })
    ]
    client = MockLLMClient(mock_responses)
    result = run_tool_loop(
        context="Xóa toàn bộ dữ liệu bảng users",
        client=client,
        max_iterations=3
    )

    assert result["success"] is True
    assert len(result["tool_history"]) == 1
    call, res = result["tool_history"][0]
    assert call.tool_name == "delete_data"
    assert res.result["success"] is False
    assert "is not allowed" in res.result["error"]
    print("=> TEST 4 PASSED: Tool DESTRUCTIVE (DENY) bị chặn tuyệt đối!")


if __name__ == "__main__":
    test_loop_with_allow_tool()
    test_loop_with_human_approval_rejected()
    test_loop_with_human_approval_approved()
    test_loop_with_deny_tool()
    print("\n" + "=" * 70)
    print("   TẤT CẢ 4 TEST AGENT TOOL LOOP VỚI POLICY ĐÃ PASS 100%! 🚀")
    print("=" * 70)
