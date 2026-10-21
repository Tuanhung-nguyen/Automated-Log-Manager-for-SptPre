import json
from pathlib import Path
from typing import Set


class StateTracker:
    """
    Quản lý danh sách các workflow run_id đã được theo dõi và xử lý.
    Dữ liệu được lưu trữ dạng JSON để không bị mất khi khởi động lại chương trình.
    """

    def __init__(self, state_file_path: str = "data/monitor/seen_runs.json"):
        self.state_file = Path(state_file_path)
        self.seen_run_ids: Set[int] = set()
        self._load_state()

    def _load_state(self) -> None:
        """Đọc danh sách run_id từ file JSON nếu file đã tồn tại."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.seen_run_ids = set(data.get("seen_run_ids", []))
            except Exception as e:
                print(f"⚠️ [WARN] Không đọc được state file: {e}. Tạo mới bộ nhớ rỗng.")
                self.seen_run_ids = set()
        else:
            self.seen_run_ids = set()

    def _save_state(self) -> None:
        """Ghi danh sách run_id hiện tại xuống file JSON."""
        # Tạo thư mục cha nếu chưa có
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"seen_run_ids": sorted(list(self.seen_run_ids))},
                    f,
                    indent=2,
                    ensure_ascii=False
                )
        except Exception as e:
            print(f"❌ [ERROR] Không lưu được state file: {e}")

    def is_seen(self, run_id: int) -> bool:
        """Kiểm tra xem run_id này đã được xử lý trước đó chưa."""
        return run_id in self.seen_run_ids

    def mark_as_seen(self, run_id: int) -> None:
        """Đánh dấu một run_id là đã xử lý và lưu ngay xuống đĩa."""
        self.seen_run_ids.add(run_id)
        self._save_state()
