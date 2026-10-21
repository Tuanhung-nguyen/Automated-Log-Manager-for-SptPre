from typing import Callable, Any


class RetryController:
    """
    RetryController quản lý số lần thử lại (Retry loop) khi một operation bị lỗi.
    Ngăn chặn vòng lặp vô hạn bằng cách áp đặt max_attempts.
    """

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts

    def run(
        self,
        operation: Callable[[], Any]
    ) -> Any:
        last_error = None

        for attempt in range(1, self.max_attempts + 1):
            print(f"\n[RETRY] Attempt {attempt}/{self.max_attempts}")

            try:
                result = operation()
                print("[RETRY] Operation succeeded.")
                return result

            except Exception as e:
                last_error = e
                print(f"[RETRY] Attempt {attempt} failed: {e}")

        raise RuntimeError(
            f"Operation failed after {self.max_attempts} attempts. "
            f"Last error: {last_error}"
        )
