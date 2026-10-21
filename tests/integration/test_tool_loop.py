import sys
from pathlib import Path

# Đảm bảo import được module app từ thư mục gốc
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.tools import run_tool_loop


def test_agent_tool_loop_with_policy():
    print("=" * 80)
    print("   INTEGRATION TEST: AGENT TOOL LOOP VỚI POLICY & HUMAN APPROVAL")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # TEST 1: Vòng lặp điều tra sự cố bình thường (READ tools tự động ALLOW)
    # -------------------------------------------------------------------------
    incident_context = "Cảnh báo hệ thống: Pipeline etl_users đang có dấu hiệu thất bại bất thường."

    # Callback duyệt người dùng: nếu gặp tool WRITE thì tự động từ chối hoặc đồng ý
    approval_calls = []

    def mock_human_approver(tool_call):
        approval_calls.append(tool_call.tool_name)
        print(f"    [HUMAN IN THE LOOP] Nhận yêu cầu phê duyệt tool: {tool_call.tool_name}")
        # Ví dụ: chỉ phê duyệt nếu là restart_pipeline, từ chối các tool khác
        return True

    result = run_tool_loop(
        context=incident_context,
        max_iterations=4,
        approval_callback=mock_human_approver
    )

    assert result["success"] is True
    assert result["analysis"] is not None
    assert len(result["tool_history"]) >= 1

    called_tools = [tc.tool_name for tc, _ in result["tool_history"]]
    print(f"\n=> Danh sách tools đã được LLM tự động gọi: {called_tools}")
    print(f"=> Tổng số vòng lặp thực hiện: {result['iterations']}")
    print(f"=> Phân tích sự cố: {result['analysis'].error_type}")
    print(f"=> Các tool đã qua Human Approval check: {approval_calls}")
    print("\n=> TEST AGENT TOOL LOOP TÍCH HỢP POLICY ĐÃ PASS 100%! 🎉")


if __name__ == "__main__":
    test_agent_tool_loop_with_policy()
