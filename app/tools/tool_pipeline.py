def get_pipeline_status(pipeline_id: str) -> dict:
    """
    Tool lấy trạng thái thực thi hiện tại của một Data Pipeline theo pipeline_id.
    """
    pid_lower = pipeline_id.lower()
    if "memory" in pid_lower or "oom" in pid_lower or "spark" in pid_lower:
        return {
            "pipeline_id": pipeline_id,
            "status": "FAILED",
            "last_run": "2026-10-13T01:30:00",
            "duration_seconds": 450,
            "error": "Task failed: OutOfMemoryError / Container killed by YARN for exceeding memory limits."
        }
    return {
        "pipeline_id": pipeline_id,
        "status": "FAILED",
        "last_run": "2026-10-13T01:30:00",
        "duration_seconds": 182,
        "error": "Task failed with non-zero exit code (1). Check execution logs for details."
    }


def get_pipeline_logs(pipeline_id: str) -> dict:
    """
    Tool lấy danh sách log chi tiết của một pipeline khi gặp lỗi hoặc cần điều tra sâu nguyên nhân gốc.
    """
    pid_lower = pipeline_id.lower()
    if "memory" in pid_lower or "oom" in pid_lower or "spark" in pid_lower:
        return {
            "pipeline_id": pipeline_id,
            "logs": [
                "Worker node-05 executor process heartbeat timed out",
                "java.lang.OutOfMemoryError: Java heap space",
                "ExecutorLostFailure: Executor 3 lost (Container killed by YARN for exceeding 8GB memory limits)",
                "Task 42 in stage 2.0 failed: OutOfMemoryError in aggregation shuffle"
            ]
        }
    return {
        "pipeline_id": pipeline_id,
        "logs": [
            "Connecting to PostgreSQL primary database host...",
            "Database connection timeout after 30s",
            "Retry 1 failed: Connection refused on port 5432",
            "Retry 2 failed: Connection refused on port 5432",
            "Pipeline terminated with Fatal Error: Could not acquire DB connection"
        ]
    }


def restart_pipeline(pipeline_id: str) -> dict:
    """
    Tool khởi động lại một pipeline (hành động thay đổi trạng thái - WRITE).
    """
    return {
        "pipeline_id": pipeline_id,
        "status": "RESTARTED",
        "message": f"Pipeline {pipeline_id} has been restarted."
    }


PIPELINE_TOOLS = [
    {
        "name": "get_pipeline_status",
        "description": "Lấy trạng thái tổng quan (status, duration, error sơ bộ) của một pipeline.",
        "risk_level": "READ",
        "parameters": {
            "type": "object",
            "properties": {
                "pipeline_id": {
                    "type": "string",
                    "description": "ID của pipeline cần kiểm tra"
                }
            },
            "required": ["pipeline_id"]
        },
        "function": get_pipeline_status
    },
    {
        "name": "get_pipeline_logs",
        "description": "Lấy các dòng log chi tiết của pipeline để điều tra sâu nguyên nhân và các bước retry lỗi.",
        "risk_level": "READ",
        "parameters": {
            "type": "object",
            "properties": {
                "pipeline_id": {
                    "type": "string",
                    "description": "ID của pipeline cần lấy log chi tiết"
                }
            },
            "required": ["pipeline_id"]
        },
        "function": get_pipeline_logs
    },
    {
        "name": "restart_pipeline",
        "description": "Khởi động lại một pipeline bị lỗi sau khi đã phân tích nguyên nhân.",
        "risk_level": "WRITE",
        "parameters": {
            "type": "object",
            "properties": {
                "pipeline_id": {
                    "type": "string",
                    "description": "ID của pipeline cần khởi động lại"
                }
            },
            "required": ["pipeline_id"]
        },
        "function": restart_pipeline
    }
]
