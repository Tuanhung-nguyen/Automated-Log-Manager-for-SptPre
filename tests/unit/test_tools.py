import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import ToolCall, ToolResult
from app.tools import (
    get_pipeline_status,
    PIPELINE_TOOLS,
    TOOL_REGISTRY,
    get_tools_metadata,
    get_tool,
    execute_tool,
    run_tool_call,
)


def test_pipeline_tools_and_executor():
    # 1. Kiểm tra function trực tiếp
    status = get_pipeline_status("pipeline_orders_daily")
    assert status["pipeline_id"] == "pipeline_orders_daily"
    assert status["status"] == "FAILED"
    assert "error" in status

    # 2. Kiểm tra metadata cấu trúc JSON schema trong PIPELINE_TOOLS và GITHUB_TOOLS
    assert len(PIPELINE_TOOLS) == 3
    assert "get_pipeline_status" in TOOL_REGISTRY
    assert "get_pipeline_logs" in TOOL_REGISTRY
    assert "restart_pipeline" in TOOL_REGISTRY
    assert "get_github_workflow_runs" in TOOL_REGISTRY
    assert "get_github_workflow_jobs" in TOOL_REGISTRY
    assert "get_github_job_logs" in TOOL_REGISTRY

    # 3. Kiểm tra Tool Registry & get_tools_metadata (phải JSON serializable được, không chứa function)
    clean_metadata = get_tools_metadata()
    assert len(clean_metadata) == 6
    for m in clean_metadata:
        assert "function" not in m
    # Thử serialize JSON để chắc chắn LLM nhận được
    json_str = json.dumps(clean_metadata)
    assert "get_pipeline_status" in json_str
    assert "get_pipeline_logs" in json_str
    assert "get_github_workflow_runs" in json_str
    assert "get_github_workflow_jobs" in json_str
    assert "get_github_job_logs" in json_str

    # 4. Kiểm tra Executor: chạy thành công
    res = execute_tool("get_pipeline_status", {"pipeline_id": "test_pipe_1"})
    assert res["success"] is True
    assert res["result"]["pipeline_id"] == "test_pipe_1"
    assert res["result"]["status"] == "FAILED"

    # 5. Kiểm tra Executor: xử lý lỗi khi tool không được phép (Permission check)
    try:
        execute_tool("unknown_tool", {})
        assert False, "Phải bắn PermissionError khi tool không được cấp quyền"
    except PermissionError as e:
        assert "Tool 'unknown_tool' is not allowed" in str(e)

    # 6. Kiểm tra run_tool_call: ToolCall -> ToolResult
    tool_call = ToolCall(tool_name="get_pipeline_status", arguments={"pipeline_id": "etl_users"})
    tool_result: ToolResult = run_tool_call(tool_call)

    assert tool_result.tool_name == "get_pipeline_status"
    assert tool_result.result["success"] is True
    assert tool_result.result["result"]["pipeline_id"] == "etl_users"
    assert tool_result.result["result"]["status"] == "FAILED"

    print("=> test_pipeline_tools, registry, executor & run_tool_call PASSED 100%!")


if __name__ == "__main__":
    test_pipeline_tools_and_executor()
