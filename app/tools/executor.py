from app.core import ToolCall, ToolResult
from .registry import get_tool
from .policy import check_permission, evaluate_policy, PolicyDecision


def execute_tool(tool_name: str, arguments: dict, approved: bool = False) -> dict:
    """
    Thực thi tool an toàn:
    - Kiểm tra quyền (Permission & Human Approval check qua policy)
    - Tra cứu tool từ registry
    - Gọi hàm tương ứng với arguments
    - Bắt Exception và trả về kết quả cấu trúc {success, result/error}
    """
    decision = evaluate_policy(tool_name)
    if decision == PolicyDecision.DENY:
        raise PermissionError(
            f"Tool '{tool_name}' is not allowed"
        )

    if decision == PolicyDecision.REQUIRE_APPROVAL and not approved:
        raise PermissionError(
            f"Tool '{tool_name}' requires human approval and was rejected"
        )

    tool = get_tool(tool_name)
    if not tool:
        return {
            "success": False,
            "error": f"Tool '{tool_name}' không tồn tại trong Tool Registry."
        }

    func = tool.get("function")
    if not callable(func):
        return {
            "success": False,
            "error": f"Tool '{tool_name}' không có hàm thực thi hợp lệ."
        }

    try:
        result = func(**arguments)
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Lỗi khi thực thi tool '{tool_name}': {str(e)}"
        }


def run_tool_call(tool_call: ToolCall, approved: bool = False) -> ToolResult:
    """
    Đóng gói toàn bộ luồng thực thi Tool:
    ToolCall -> Registry lookup -> execute_tool (có check Human Approval) -> ToolResult
    """
    if not tool_call.tool_name:
        return ToolResult(
            tool_name="",
            result={"success": False, "error": "tool_name is None"}
        )

    try:
        result = execute_tool(
            tool_call.tool_name,
            tool_call.arguments,
            approved=approved
        )
    except PermissionError as e:
        result = {
            "success": False,
            "error": str(e)
        }

    return ToolResult(
        tool_name=tool_call.tool_name,
        result=result
    )
