from typing import List, Optional, Dict, Any
from app.adapters.base import BaseSourceAdapter
from app.core.models import IncidentContext
from app.tools.tool_github import get_github_workflow_runs, get_github_workflow_jobs
from app.config import settings


class GitHubAdapter(BaseSourceAdapter):
    """
    Adapter chuyên biệt dành cho GitHub Actions.
    Chịu trách nhiệm giao tiếp với GitHub API và chuẩn hóa thành IncidentContext.
    """

    def __init__(self, owner: Optional[str] = None, repo: Optional[str] = None):
        self.owner = owner or settings.GITHUB_OWNER
        self.repo = repo or settings.GITHUB_REPO

    @property
    def source_name(self) -> str:
        return "github"

    def fetch_incident_context(self, target_id: str, **kwargs) -> IncidentContext:
        """Dành cho CLI on-demand: lấy log qua run_id."""
        run_id = int(target_id)
        owner = kwargs.get("owner", self.owner)
        repo = kwargs.get("repo", self.repo)

        jobs_data = get_github_workflow_jobs(run_id=run_id, owner=owner, repo=repo)
        jobs = jobs_data.get("jobs", [])

        failed_job_name = "Unknown Job"
        failed_job_id = None
        for j in jobs:
            if j.get("conclusion") == "failure":
                failed_job_name = j.get("name", failed_job_name)
                failed_job_id = j.get("id")
                break

        context = IncidentContext(
            timestamp=jobs_data.get("repository", ""),
            component="GitHub Actions Ingestion",
            error=f"Workflow Run Failed (run_id: {run_id}) at job: {failed_job_name}",
            log=(
                f"Workflow run_id {run_id} of repository {owner}/{repo} failed. "
                f"Failed job: {failed_job_name} (job_id: {failed_job_id}). "
                f"Please investigate logs and determine root cause."
            ),
            metrics={
                "run_id": run_id,
                "repository": f"{owner}/{repo}",
                "failed_job_id": failed_job_id,
                "source": self.source_name
            }
        )
        return context

    def parse_webhook_payload(self, payload: Dict[str, Any]) -> Optional[IncidentContext]:
        """
        Dành cho Webhook tự động:
        GitHub Actions gửi payload có key 'workflow_run'.
        - Chỉ xử lý khi kết luận là THẤT BẠI ('failure').
        - Bỏ qua các sự kiện thành công hoặc đang chạy.
        """
        workflow_run = payload.get("workflow_run", {})
        conclusion = workflow_run.get("conclusion")
        run_id = workflow_run.get("id")

        if conclusion != "failure" or not run_id:
            # Thành công hoặc không phải lỗi -> Bỏ qua
            return None

        run_name = workflow_run.get("name", "Unknown Workflow")
        repo_info = payload.get("repository", {})
        repo_full_name = repo_info.get("full_name", f"{self.owner}/{self.repo}")

        context = IncidentContext(
            timestamp=workflow_run.get("created_at", ""),
            component="GitHub Actions Ingestion",
            error=f"Workflow Run Failed: {run_name}",
            log=(
                f"Webhook event: Workflow run #{workflow_run.get('run_number')} (run_id: {run_id}) "
                f"of repository {repo_full_name} failed. Please investigate logs."
            ),
            metrics={
                "run_id": run_id,
                "repository": repo_full_name,
                "html_url": workflow_run.get("html_url"),
                "source": "github_webhook"
            }
        )
        return context

    def poll_new_failures(self, per_page: int = 5, **kwargs) -> List[IncidentContext]:
        owner = kwargs.get("owner", self.owner)
        repo = kwargs.get("repo", self.repo)

        runs_data = get_github_workflow_runs(owner=owner, repo=repo, per_page=per_page)
        failures: List[IncidentContext] = []

        for run in runs_data.get("workflow_runs", []):
            if run.get("status") == "completed" and run.get("conclusion") == "failure":
                context = IncidentContext(
                    timestamp=run.get("created_at", ""),
                    component="GitHub Actions Ingestion",
                    error=f"Workflow Run Failed: {run.get('name')}",
                    log=(
                        f"Workflow run #{run.get('run_number')} (run_id: {run.get('id')}) of repository "
                        f"{owner}/{repo} terminated with failure conclusion. "
                        f"Please investigate root cause."
                    ),
                    metrics={
                        "run_id": run.get("id"),
                        "repository": f"{owner}/{repo}",
                        "html_url": run.get("html_url"),
                        "source": self.source_name
                    }
                )
                failures.append(context)

        return failures
