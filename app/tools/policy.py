from enum import Enum


class RiskLevel(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


# Phân loại mức độ rủi ro của từng tool
TOOL_RISK_LEVELS: dict[str, RiskLevel] = {
    "get_pipeline_status": RiskLevel.READ,
    "get_pipeline_logs": RiskLevel.READ,
    "restart_pipeline": RiskLevel.WRITE,
    "get_github_workflow_runs": RiskLevel.READ,
    "get_github_workflow_jobs": RiskLevel.READ,
    "get_github_job_logs": RiskLevel.READ,
    "get_databricks_job_run": RiskLevel.READ,
    "get_databricks_run_output": RiskLevel.READ,
}


def get_tool_risk(tool_name: str) -> RiskLevel:
    """Trả về mức rủi ro của tool (mặc định DESTRUCTIVE nếu tool lạ)."""
    return TOOL_RISK_LEVELS.get(tool_name, RiskLevel.DESTRUCTIVE)


def evaluate_policy(tool_name: str) -> PolicyDecision:
    """
    Đánh giá quyền hạn theo risk_level của tool:
    - READ        -> ALLOW (Tự động thực thi an toàn)
    - WRITE       -> REQUIRE_APPROVAL (Cần Human Approval trước khi chạy)
    - DESTRUCTIVE -> DENY (Chặn hoàn toàn)
    """
    if tool_name not in TOOL_RISK_LEVELS:
        return PolicyDecision.DENY

    risk = TOOL_RISK_LEVELS[tool_name]
    if risk == RiskLevel.READ:
        return PolicyDecision.ALLOW
    elif risk == RiskLevel.WRITE:
        return PolicyDecision.REQUIRE_APPROVAL
    else:
        return PolicyDecision.DENY


def check_permission(tool_name: str, approved: bool = False) -> bool:
    """
    Kiểm tra quyền thực thi có tính đến Human Approval:
    - ALLOW            -> Luôn cho phép
    - REQUIRE_APPROVAL -> Chỉ cho phép khi có approved=True từ người dùng
    - DENY             -> Luôn từ chối
    """
    decision = evaluate_policy(tool_name)
    if decision == PolicyDecision.ALLOW:
        return True
    elif decision == PolicyDecision.REQUIRE_APPROVAL:
        return approved
    return False
