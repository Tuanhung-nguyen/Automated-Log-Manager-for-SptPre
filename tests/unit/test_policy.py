import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import ToolCall
from app.tools import (
    execute_tool,
    run_tool_call,
    check_permission,
    get_tool_risk,
    evaluate_policy,
    RiskLevel,
    PolicyDecision,
    get_tool,
)


def test_permission_and_human_approval_policy():
    print("=" * 70)
    print("   TEST POLICY: RISK LEVELS & HUMAN APPROVAL (WRITE TOOLS)")
    print("=" * 70)

    # -------------------------------------------------------------
    # Case 1: get_pipeline_status (READ) -> ALLOW -> Tự động chạy
    # -------------------------------------------------------------
    tool_status = "get_pipeline_status"
    assert get_tool_risk(tool_status) == RiskLevel.READ
    assert evaluate_policy(tool_status) == PolicyDecision.ALLOW
    assert check_permission(tool_status) is True

    res = execute_tool(tool_status, {"pipeline_id": "test_pipeline"})
    assert res["success"] is True
    print(f"[TEST 1 PASSED] {tool_status} (READ) -> ALLOW -> Tự động chạy thành công!")

    # -------------------------------------------------------------
    # Case 2A: restart_pipeline (WRITE) -> APPROVE -> Chạy thành công
    # -------------------------------------------------------------
    tool_write = "restart_pipeline"
    assert get_tool_risk(tool_write) == RiskLevel.WRITE
    assert evaluate_policy(tool_write) == PolicyDecision.REQUIRE_APPROVAL

    # Người dùng Approve (approved=True)
    assert check_permission(tool_write, approved=True) is True
    res_approved = execute_tool(tool_write, {"pipeline_id": "etl_users"}, approved=True)
    assert res_approved["success"] is True
    assert res_approved["result"]["status"] == "RESTARTED"
    print(f"[TEST 2A PASSED] {tool_write} (WRITE) -> APPROVE (approved=True) -> Thực thi thành công!")

    # -------------------------------------------------------------
    # Case 2B: restart_pipeline (WRITE) -> REJECT -> Chặn không chạy
    # -------------------------------------------------------------
    # Người dùng Reject (approved=False)
    assert check_permission(tool_write, approved=False) is False
    try:
        execute_tool(tool_write, {"pipeline_id": "etl_users"}, approved=False)
        assert False, f"{tool_write} khi bị Reject phải ném ra ngoại lệ PermissionError"
    except PermissionError as e:
        assert "requires human approval" in str(e)
        print(f"[TEST 2B PASSED] {tool_write} (WRITE) -> REJECT (approved=False) -> Chặn an toàn! (Lỗi: {e})")

    # Kiểm tra qua run_tool_call wrapper:
    tc = ToolCall(tool_name=tool_write, arguments={"pipeline_id": "etl_users"})
    tr_rejected = run_tool_call(tc, approved=False)
    assert tr_rejected.result["success"] is False
    assert "requires human approval" in tr_rejected.result["error"]

    tr_approved = run_tool_call(tc, approved=True)
    assert tr_approved.result["success"] is True
    assert tr_approved.result["result"]["status"] == "RESTARTED"

    # -------------------------------------------------------------
    # Case 3: delete_data (DESTRUCTIVE / UNKNOWN) -> DENY -> Luôn chặn
    # -------------------------------------------------------------
    tool_denied = "delete_data"
    assert get_tool_risk(tool_denied) == RiskLevel.DESTRUCTIVE
    assert evaluate_policy(tool_denied) == PolicyDecision.DENY
    assert check_permission(tool_denied, approved=True) is False  # Dù có approve vẫn DENY

    try:
        execute_tool(tool_denied, {}, approved=True)
        assert False, f"Gọi {tool_denied} phải ném ra ngoại lệ PermissionError"
    except PermissionError as e:
        assert f"Tool '{tool_denied}' is not allowed" in str(e)
        print(f"[TEST 3 PASSED] {tool_denied} (DESTRUCTIVE) -> DENY -> Luôn chặn dù có approve! (Lỗi: {e})")

    print("\n=> TẤT CẢ TEST HUMAN APPROVAL VÀ POLICY ĐÃ PASS 100%! 🎉")


if __name__ == "__main__":
    test_permission_and_human_approval_policy()
