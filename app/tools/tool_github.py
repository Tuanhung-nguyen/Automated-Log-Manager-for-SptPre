import requests
from typing import Optional
from app.config import settings


def get_github_workflow_runs(
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    per_page: int = 5,
    token: Optional[str] = None
) -> dict:
    """
    Lấy danh sách các lần chạy gần nhất của GitHub Actions workflow từ repository.
    Chỉ đọc metadata (read-only), an toàn và không thay đổi trạng thái workflow.
    """
    owner = owner or settings.GITHUB_OWNER
    repo = repo or settings.GITHUB_REPO
    token = token or settings.GITHUB_TOKEN

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "TestAIForDE-Agent"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(
        url,
        params={"per_page": per_page},
        headers=headers,
        timeout=15
    )
    response.raise_for_status()

    data = response.json()

    return {
        "repository": f"{owner}/{repo}",
        "total_count": data.get("total_count", 0),
        "workflow_runs": [
            {
                "id": run.get("id"),
                "name": run.get("name"),
                "run_number": run.get("run_number"),
                "event": run.get("event"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "created_at": run.get("created_at"),
                "html_url": run.get("html_url")
            }
            for run in data.get("workflow_runs", [])
        ]
    }


def get_github_workflow_jobs(
    run_id: int,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    token: Optional[str] = None
) -> dict:
    """
    Lấy danh sách các jobs và steps chi tiết của một lần chạy (run_id) trong GitHub Actions.
    Giúp xác định chính xác job hoặc step nào bị thất bại (failure).
    """
    owner = owner or settings.GITHUB_OWNER
    repo = repo or settings.GITHUB_REPO
    token = token or settings.GITHUB_TOKEN

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "TestAIForDE-Agent"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(
        url,
        params={"per_page": 100},
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    return {
        "run_id": run_id,
        "total_count": data.get("total_count", 0),
        "jobs": [
            {
                "id": job.get("id"),
                "name": job.get("name"),
                "status": job.get("status"),
                "conclusion": job.get("conclusion"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "steps": [
                    {
                        "name": step.get("name"),
                        "status": step.get("status"),
                        "conclusion": step.get("conclusion"),
                        "number": step.get("number")
                    }
                    for step in job.get("steps", [])
                ],
            }
            for job in data.get("jobs", [])
        ],
    }


def extract_error_window(lines: list[str], max_lines: int = 80) -> list[str]:
    """
    Tự động quét và trích xuất cửa sổ log xung quanh vị trí phát sinh lỗi thực tế:
    - Tìm các vị trí xuất hiện Traceback, Exception, Error, FAILED
    - Bỏ qua các cảnh báo vô hại (Deprecation warnings)
    - Cắt lấy 5 dòng trước lỗi và toàn bộ traceback/exception
    - Loại bỏ các dòng dọn dẹp runner (Post job cleanup, git config) ở cuối log
    """
    error_keywords = [
        "traceback (most recent call last)",
        "exception:",
        "error:",
        "failed with non-zero exit code",
        "fatal:"
    ]

    matched_indices = []
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if any(kw in line_lower for kw in error_keywords) and "##[warning]" not in line_lower:
            matched_indices.append(idx)

    if matched_indices:
        start_idx = max(0, matched_indices[0] - 5)
        end_idx = min(len(lines), matched_indices[-1] + 25)
        window = lines[start_idx:end_idx]
        if len(window) > max_lines:
            window = window[:max_lines]
        return window

    return lines[-max_lines:] if len(lines) > max_lines else lines


def get_github_job_logs(
    job_id: int,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    token: Optional[str] = None,
    tail_lines: int = 80
) -> dict:
    """
    Tải log dòng lệnh chi tiết (raw terminal console log) của một Job trong GitHub Actions.
    Tự động trích xuất cửa sổ log xung quanh lỗi (traceback/error) để Agent phân tích chính xác nguyên nhân gốc.
    """
    owner = owner or settings.GITHUB_OWNER
    repo = repo or settings.GITHUB_REPO
    token = token or settings.GITHUB_TOKEN

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/jobs/{job_id}/logs"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "TestAIForDE-Agent"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        if response.status_code == 200:
            lines = response.text.splitlines()
            relevant_logs = extract_error_window(lines, max_lines=tail_lines)
            return {
                "job_id": job_id,
                "success": True,
                "total_lines": len(lines),
                "error_logs": relevant_logs,
                "message": f"Tải thành công {len(lines)} dòng log console từ GitHub Actions. Đã trích xuất {len(relevant_logs)} dòng xung quanh lỗi."
            }
        elif response.status_code == 403:
            return {
                "job_id": job_id,
                "success": False,
                "error": "HTTP 403 Forbidden: Token cần được cấp quyền 'repo' để tải log.",
                "action_url": f"https://github.com/{owner}/{repo}/actions"
            }
        elif response.status_code == 410:
            return {
                "job_id": job_id,
                "success": False,
                "error": "HTTP 410 Gone: Log đã hết hạn lưu trữ trên GitHub (quá 90 ngày)."
            }
        else:
            return {
                "job_id": job_id,
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:200]}"
            }
    except Exception as e:
        return {
            "job_id": job_id,
            "success": False,
            "error": str(e)
        }


GITHUB_TOOLS = [
    {
        "name": "get_github_workflow_runs",
        "description": "Lấy danh sách các lần chạy gần nhất của GitHub Actions workflow (status, conclusion, run_id, html_url) từ GitHub repository.",
        "risk_level": "READ",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": f"Chủ sở hữu repository (mặc định cấu hình: '{settings.GITHUB_OWNER}')",
                    "default": settings.GITHUB_OWNER
                },
                "repo": {
                    "type": "string",
                    "description": f"Tên repository GitHub (mặc định cấu hình: '{settings.GITHUB_REPO}')",
                    "default": settings.GITHUB_REPO
                },
                "per_page": {
                    "type": "integer",
                    "description": "Số lượng lần chạy cần lấy (mặc định: 5)",
                    "default": 5
                }
            },
            "required": []
        },
        "function": get_github_workflow_runs
    },
    {
        "name": "get_github_workflow_jobs",
        "description": "Lấy danh sách các jobs và steps chi tiết của một lần chạy workflow qua run_id. Giúp xác định chính xác job và step nào bị failure.",
        "risk_level": "READ",
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "integer",
                    "description": "ID của lần chạy workflow (lấy từ get_github_workflow_runs)"
                },
                "owner": {
                    "type": "string",
                    "description": f"Chủ sở hữu repository (mặc định cấu hình: '{settings.GITHUB_OWNER}')",
                    "default": settings.GITHUB_OWNER
                },
                "repo": {
                    "type": "string",
                    "description": f"Tên repository GitHub (mặc định cấu hình: '{settings.GITHUB_REPO}')",
                    "default": settings.GITHUB_REPO
                }
            },
            "required": ["run_id"]
        },
        "function": get_github_workflow_jobs
    },
    {
        "name": "get_github_job_logs",
        "description": "Tải nội dung log dòng lệnh (terminal console traceback/error) của một job cụ thể qua job_id để điều tra chi tiết nguyên nhân gốc.",
        "risk_level": "READ",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "ID của job cần tải log (lấy từ get_github_workflow_jobs)"
                },
                "owner": {
                    "type": "string",
                    "description": f"Chủ sở hữu repository (mặc định cấu hình: '{settings.GITHUB_OWNER}')",
                    "default": settings.GITHUB_OWNER
                },
                "repo": {
                    "type": "string",
                    "description": f"Tên repository GitHub (mặc định cấu hình: '{settings.GITHUB_REPO}')",
                    "default": settings.GITHUB_REPO
                },
                "tail_lines": {
                    "type": "integer",
                    "description": "Số dòng log cuối cùng cần trích xuất (mặc định: 80)",
                    "default": 80
                }
            },
            "required": ["job_id"]
        },
        "function": get_github_job_logs
    }
]
