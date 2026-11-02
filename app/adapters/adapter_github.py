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
        - Xử lý cả THÀNH CÔNG ('success') lẫn THẤT BẠI ('failure').
        """
        workflow_run = payload.get("workflow_run", {})
        conclusion = workflow_run.get("conclusion")
        run_id = workflow_run.get("id")

        if not run_id or conclusion not in ["success", "failure"]:
            return None

        run_name = workflow_run.get("name", "Unknown Workflow")
        repo_info = payload.get("repository", {})
        repo_full_name = repo_info.get("full_name", f"{self.owner}/{self.repo}")
        run_number = workflow_run.get("run_number", run_id)

        # Tính duration
        duration_sec = 0.0
        created_at = workflow_run.get("created_at")
        updated_at = workflow_run.get("updated_at")
        if created_at and updated_at:
            try:
                from datetime import datetime
                t0 = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                duration_sec = round((t1 - t0).total_seconds(), 2)
            except Exception:
                duration_sec = 0.0

        project_name = repo_info.get("name") or self.repo or getattr(settings, "DEFAULT_PROJECT_NAME", "default")

        # Làm giàu danh sách Jobs con từ GitHub Actions API
        subtasks = []
        try:
            from app.tools.tool_github import get_github_workflow_jobs
            jobs_info = get_github_workflow_jobs(run_id=int(run_id), owner=self.owner, repo=self.repo, token=self.token)
            for j in jobs_info.get("jobs", []):
                j_start = j.get("started_at")
                j_end = j.get("completed_at")
                j_dur_ms = 0
                if j_start and j_end:
                    from datetime import datetime
                    t_s = datetime.fromisoformat(j_start.replace("Z", "+00:00"))
                    t_e = datetime.fromisoformat(j_end.replace("Z", "+00:00"))
                    j_dur_ms = int(round((t_e - t_s).total_seconds() * 1000))
                subtasks.append({
                    "task_key": j.get("name"),
                    "execution_duration": j_dur_ms,
                    "state": {"result_state": (j.get("conclusion") or j.get("status") or "SUCCESS").upper()}
                })
        except Exception:
            pass

        if conclusion == "failure":
            return IncidentContext(
                timestamp=workflow_run.get("created_at", ""),
                component="GitHub Actions Ingestion",
                error=f"Workflow Run Failed: {run_name}",
                log=(
                    f"Webhook event: Workflow run #{run_number} (run_id: {run_id}) "
                    f"of repository {repo_full_name} failed. Please investigate logs."
                ),
                metrics={
                    "run_id": run_id,
                    "repository": repo_full_name,
                    "project_name": project_name,
                    "job_name": run_name,
                    "job_id": workflow_run.get("workflow_id"),
                    "status": "FAILED",
                    "duration_sec": duration_sec,
                    "start_time": created_at,
                    "end_time": updated_at,
                    "html_url": workflow_run.get("html_url"),
                    "source": "github_webhook",
                    "tasks": subtasks
                }
            )
        else:
            # Chạy thành công (success): error = None
            return IncidentContext(
                timestamp=workflow_run.get("created_at", ""),
                component="GitHub Actions Ingestion",
                error=None,
                log=(
                    f"Webhook event: Workflow run #{run_number} (run_id: {run_id}) "
                    f"of repository {repo_full_name} completed successfully."
                ),
                metrics={
                    "run_id": run_id,
                    "repository": repo_full_name,
                    "project_name": project_name,
                    "job_name": run_name,
                    "job_id": workflow_run.get("workflow_id"),
                    "status": "SUCCESS",
                    "duration_sec": duration_sec,
                    "start_time": created_at,
                    "end_time": updated_at,
                    "html_url": workflow_run.get("html_url"),
                    "source": "github_webhook",
                    "tasks": subtasks
                }
            )

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


