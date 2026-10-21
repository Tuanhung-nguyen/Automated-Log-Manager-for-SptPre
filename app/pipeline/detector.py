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
    text = (
        context.error + " " +
        context.log
    ).lower()

    for keyword in ERROR_KEYWORDS:
        if keyword in text:
            return True

    return False
