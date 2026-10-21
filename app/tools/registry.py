from .tool_pipeline import PIPELINE_TOOLS
from .tool_github import GITHUB_TOOLS
from .tool_databricks import DATABRICKS_TOOLS

ALL_TOOLS = PIPELINE_TOOLS + GITHUB_TOOLS + DATABRICKS_TOOLS

# Tập hợp toàn bộ tools hệ thống hỗ trợ
TOOL_REGISTRY: dict[str, dict] = {
    tool["name"]: tool
    for tool in ALL_TOOLS
}


def get_tools_metadata() -> list[dict]:
    """
    Trả về metadata thuần JSON (đã lược bỏ 'function') để gửi cho LLM.
    Tránh lỗi TypeError khi serialize JSON.
    """
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "risk_level": tool.get("risk_level", "READ"),
            "parameters": tool["parameters"]
        }
        for tool in TOOL_REGISTRY.values()
    ]


def get_tool(tool_name: str) -> dict | None:
    """Tra cứu tool theo tên."""
    return TOOL_REGISTRY.get(tool_name)
