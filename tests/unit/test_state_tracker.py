import unittest
import tempfile
from pathlib import Path
from app.monitor.state import StateTracker


class TestStateTracker(unittest.TestCase):
    def test_state_tracker_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_state_file = Path(tmpdir) / "test_seen_runs.json"

            tracker = StateTracker(state_file_path=str(temp_state_file))

            # 1. Ban đầu rỗng
            self.assertFalse(tracker.is_seen(12345))
            self.assertFalse(tracker.is_seen(67890))

            # 2. Đánh dấu run_id 12345
            tracker.mark_as_seen(12345)
            self.assertTrue(tracker.is_seen(12345))
            self.assertFalse(tracker.is_seen(67890))

            # 3. Tạo tracker mới đọc lại từ cùng file xem có persist không
            tracker_reloaded = StateTracker(state_file_path=str(temp_state_file))
            self.assertTrue(tracker_reloaded.is_seen(12345))
            self.assertFalse(tracker_reloaded.is_seen(67890))


if __name__ == "__main__":
    unittest.main()

