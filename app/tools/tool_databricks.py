import requests
import re
from typing import Optional, Dict, Any
from app.config import settings


def _extract_error_window(log_text: str, window_before: int = 15, window_after: int = 30) -> str:
    """
    Cắt thông minh cửa sổ log xung quanh vị trí xuất hiện Exception / Error trong terminal/notebook output.
    Giúp tiết kiệm token và tránh làm loãng context của LLM.
    """
    lines = log_text.splitlines()
    error_patterns = [
        re.compile(r"traceback \(most recent call last\)", re.IGNORECASE),
        re.compile(r"(error|exception|fail):", re.IGNORECASE),
        re.compile(r"analysisexception|py4jjavaerror|sparkexception", re.IGNORECASE),
    ]

    error_idx = None
    for idx, line in enumerate(lines):
        for pattern in error_patterns:
            if pattern.search(line):
                error_idx = idx
                break
        if error_idx is not None:
            break

    if error_idx is None:
        # Nếu không thấy pattern rõ ràng, lấy 40 dòng cuối cùng (thường chứa lỗi)
        return "\n".join(lines[-40:])

    start_idx = max(0, error_idx - window_before)
    end_idx = min(len(lines), error_idx + window_after + 1)
    sliced_lines = lines[start_idx:end_idx]

    header = f"--- [DATABRICKS LOG TRUNCATED: LẤY TỪ DÒNG {start_idx+1} ĐẾN {end_idx}/{len(lines)}] ---\n"
    return header + "\n".join(sliced_lines)


def get_databricks_job_run(run_id: int, host: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
    """
    Tra cứu thông tin chi tiết của một lần chạy Databricks Job Run:
    Bao gồm trạng thái (state), thời gian chạy, cluster ID, và các tasks bên trong.
    """
    base_url = (host or settings.DATABRICKS_HOST or "").rstrip("/")
    api_token = token or settings.DATABRICKS_TOKEN

    if not base_url or not api_token:
        raise ValueError("Thiếu cấu hình DATABRICKS_HOST hoặc DATABRICKS_TOKEN.")

    url = f"{base_url}/api/2.1/jobs/runs/get"
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {"run_id": run_id}

    response = requests.get(url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    state = data.get("state", {})
    tasks = data.get("tasks", [])

    failed_tasks = []
    for t in tasks:
        t_state = t.get("state", {})
        if t_state.get("result_state") == "FAILED" or t_state.get("life_cycle_state") == "INTERNAL_ERROR":
            failed_tasks.append({
                "task_key": t.get("task_key"),
                "run_id": t.get("run_id"),
                "description": t.get("description"),
                "result_state": t_state.get("result_state"),
                "state_message": t_state.get("state_message")
            })

    return {
        "job_id": data.get("job_id"),
        "run_id": data.get("run_id"),
        "run_name": data.get("run_name"),
        "life_cycle_state": state.get("life_cycle_state"),
        "result_state": state.get("result_state"),
        "state_message": state.get("state_message"),
        "start_time": data.get("start_time"),
        "execution_duration_ms": data.get("execution_duration"),
        "cluster_instance": data.get("cluster_instance", {}),
        "failed_tasks": failed_tasks
    }


def get_databricks_run_output(run_id: int, host: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
    """
    Trích xuất terminal log / traceback lỗi của Notebook hoặc Python Task trên Databricks khi bị fail.
    Tự động cắt cửa sổ log thông minh để cung cấp bằng chứng cho AI Agent.
    """
    base_url = (host or settings.DATABRICKS_HOST or "").rstrip("/")
    api_token = token or settings.DATABRICKS_TOKEN

    if not base_url or not api_token:
        raise ValueError("Thiếu cấu hình DATABRICKS_HOST hoặc DATABRICKS_TOKEN.")

    url = f"{base_url}/api/2.1/jobs/runs/get-output"
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {"run_id": run_id}

    response = requests.get(url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    error_summary = data.get("error", "")
    error_trace = data.get("error_trace", "")
    notebook_output = data.get("notebook_output", {}).get("result", "")

    raw_log = f"{error_summary}\n{error_trace}\n{notebook_output}".strip()
    if not raw_log:
        raw_log = "Không tìm thấy nội dung error trace trong output của task."

    smart_slice = _extract_error_window(raw_log)

    return {
        "run_id": run_id,
        "has_error": bool(error_summary or error_trace),
        "error_summary": error_summary,
        "log_slice": smart_slice
    }


# =====================================================================
# METADATA TOOLS DATABRICKS DÀNH CHO AGENT REACT LOOP
# =====================================================================
DATABRICKS_TOOLS: list[dict] = [
    {
        "name": "get_databricks_job_run",
        "description": "Tra cứu thông tin trạng thái, cluster và các task của một lần chạy Databricks Job Run theo run_id. Dùng khi cần biết task nào trong Databricks job bị fail.",
        "risk_level": "READ",
        "function": get_databricks_job_run,
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "integer",
                    "description": "Mã định danh lần chạy của Databricks Job (run_id)"
                }
            },
            "required": ["run_id"]
        }
    },
    {
        "name": "get_databricks_run_output",
        "description": "Trích xuất terminal traceback, exception log của Notebook hoặc Python task bị gãy trên Databricks. Dùng khi đã có run_id của task bị lỗi và cần đọc nguyên nhân gãy cụ thể.",
        "risk_level": "READ",
        "function": get_databricks_run_output,
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "integer",
                    "description": "Mã định danh lần chạy của Databricks Task Run (run_id) cần đọc output traceback"
                }
            },
            "required": ["run_id"]
        }
    }
]
