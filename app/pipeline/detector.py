from app.core.models import IncidentContext


ERROR_KEYWORDS = [
    "error",
    "exception",
    "failed",
    "failure",
    "killed",
    "timeout",
    "oom",
    "out of memory",
    "lag",
    "exhausted",
]


def detect_incident(context: IncidentContext) -> bool:
    """
    Detector: Kiểm tra xem log/error có dấu hiệu của incident hay không.
    Nhiệm vụ: Lọc nhanh (Fast-path filtering) các log bình thường để tránh tốn chi phí gọi LLM.
    """
    # Nếu lần chạy thành công rõ ràng (status = SUCCESS và không có lỗi) -> Bỏ qua ngay
    if context.metrics and context.metrics.get("status") == "SUCCESS" and not context.error:
        return False

    text = (
        (context.error or "") + " " +
        (context.log or "")
    ).lower()

    for keyword in ERROR_KEYWORDS:
        if keyword in text:
            return True

    return False
