import sys
import time
from typing import Optional, List

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
from app.core.models import IncidentContext, AnalysisResult
from app.monitor.state import StateTracker
from app.monitor.notifier import AlertNotifier
from app.tools.tool_github import get_github_workflow_runs
from app.config import settings


class GitHubWorkflowPoller:
    """
    Module tuần tra và phát hiện tự động các workflow run bị lỗi trên GitHub Actions.
    Khi phát hiện lỗi mới (chưa có trong StateTracker), nó tự tạo IncidentContext
    và chuyển cho IncidentPipeline xử lý.
    """

    def __init__(
        self,
        pipeline,
        state_tracker: Optional[StateTracker] = None,
        notifier: Optional[AlertNotifier] = None,
        owner: Optional[str] = None,
        repo: Optional[str] = None
    ):
        self.pipeline = pipeline
        self.tracker = state_tracker or StateTracker()
        self.notifier = notifier or AlertNotifier()
        self.owner = owner or settings.GITHUB_OWNER
        self.repo = repo or settings.GITHUB_REPO

    def poll_once(self, per_page: int = 5) -> List[AnalysisResult]:
        """
        Thực hiện một lượt quét danh sách workflow runs gần nhất:
        - Tìm các run có status='completed' và conclusion='failure'.
        - Bỏ qua các run đã được xử lý (is_seen).
        - Gửi các run mới vào pipeline phân tích.
        """
        print(f"\n🔍 [POLLER] Đang quét GitHub Actions: {self.owner}/{self.repo}...")

        try:
            runs_data = get_github_workflow_runs(
                owner=self.owner,
                repo=self.repo,
                per_page=per_page
            )
        except Exception as e:
            print(f"❌ [POLLER ERROR] Không thể lấy workflow runs từ GitHub: {e}")
            return []

        workflow_runs = runs_data.get("workflow_runs", [])
        results: List[AnalysisResult] = []

        new_failures_found = 0

        for run in workflow_runs:
            run_id = run["id"]
            run_name = run["name"]
            status = run["status"]
            conclusion = run["conclusion"]

            # Chỉ quan tâm đến các lần chạy đã hoàn tất và kết luận là THẤT BẠI (failure)
            if status == "completed" and conclusion == "failure":
                if self.tracker.is_seen(run_id):
                    # Đã phân tích rồi -> Bỏ qua
                    continue

                new_failures_found += 1
                print(f"\n🚨 [PHÁT HIỆN SỰ CỐ MỚI] Workflow: '{run_name}' (Run ID: {run_id}) bị FAILED!")
                print(f"   • URL: {run.get('html_url')}")
                print(f"   • Thời gian tạo: {run.get('created_at')}")

                # Tạo IncidentContext chuẩn từ dữ liệu GitHub
                context = IncidentContext(
                    timestamp=run.get("created_at", ""),
                    component="GitHub Actions Ingestion",
                    error=f"Workflow Run Failed: {run_name}",
                    log=(
                        f"Workflow run #{run.get('run_number')} (run_id: {run_id}) of repository "
                        f"{self.repo} (owner: {self.owner}) terminated with failure conclusion. "
                        f"Please investigate root cause."
                    ),
                    metrics={
                        "run_id": run_id,
                        "repository": f"{self.owner}/{self.repo}",
                        "html_url": run.get("html_url")
                    }
                )

                # Chuyển giao cho IncidentPipeline phân tích
                print(f"🚀 [KÍCH HOẠT TỰ ĐỘNG] Chuyển sự cố Run ID {run_id} sang Agent Pipeline...")
                analysis_result = self.pipeline.run(context)
                results.append(analysis_result)

                # Gửi cảnh báo tự động qua AlertNotifier
                self.notifier.send_alert(analysis_result)

                # Đánh dấu đã xử lý để không bao giờ phân tích lại run này
                self.tracker.mark_as_seen(run_id)
                print(f"💾 [STATE SAVED] Đã đánh dấu Run ID {run_id} vào StateTracker.")

        if new_failures_found == 0:
            print("✅ [POLLER] Không có sự cố mới nào cần xử lý.")

        return results

    def start_polling_loop(self, interval_seconds: Optional[int] = None, max_iterations: Optional[int] = None):
        """
        Vòng lặp tuần tra liên tục theo chu kỳ thời gian (Daemon / Background Poller).
        - interval_seconds: Thời gian nghỉ giữa các lần quét (mặc định lấy từ settings.POLL_INTERVAL_SECONDS).
        - max_iterations: Số lần quét tối đa (nếu None sẽ chạy vô tận).
        """
        interval = interval_seconds if interval_seconds is not None else settings.POLL_INTERVAL_SECONDS
        print("=" * 80)
        print(f"  KHỞI ĐỘNG HỆ THỐNG GIÁM SÁT TỰ ĐỘNG (AUTO-POLLER)")
        print(f"  Repo: {self.owner}/{self.repo} | Chu kỳ quét: {interval}s")
        print("=" * 80)

        iterations = 0
        try:
            while True:
                iterations += 1
                print(f"\n--- [LƯỢT QUÉT #{iterations}] Lúc {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
                self.poll_once()

                if max_iterations and iterations >= max_iterations:
                    print(f"\n🏁 Đã hoàn thành {max_iterations} lượt quét theo yêu cầu.")
                    break

                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n🛑 Người dùng đã dừng hệ thống giám sát tự động (Ctrl + C).")
