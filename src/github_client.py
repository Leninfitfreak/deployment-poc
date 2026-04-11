from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import time
import requests

from .utils import PocError, git_credential_fill, github_repo_slug


@dataclass
class GithubRunState:
    run_id: str
    repository: str
    found: bool
    status: str
    conclusion: str
    html_url: str

    @property
    def active(self) -> bool:
        return self.found and self.status not in {"completed"}

    @property
    def finished(self) -> bool:
        return self.found and self.status == "completed"


class GithubActionsClient:
    def __init__(
        self,
        repo_root: Path,
        repository: str | None = None,
        api_token: str | None = None,
        api_base: str = "https://api.github.com",
    ) -> None:
        self.repo_root = repo_root
        self.repository = (repository or "").strip() or github_repo_slug(repo_root)
        self.api_base = api_base.rstrip("/")
        self.session = requests.Session()
        token = (api_token or "").strip()
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            credentials = git_credential_fill("github.com")
            username = credentials.get("username", "").strip()
            password = credentials.get("password", "").strip()
            if username and password:
                self.session.auth = (username, password)
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def configured(self) -> bool:
        return bool(self.repository)

    def build_run_url(self, run_id: str) -> str:
        return f"https://github.com/{self.repository}/actions/runs/{run_id}"

    def get_run_state(self, run_id: str, repository: str | None = None) -> GithubRunState:
        repo = (repository or "").strip() or self.repository
        if not repo:
            raise PocError("GitHub repository is required to inspect workflow runs")
        response = self.session.get(f"{self.api_base}/repos/{repo}/actions/runs/{run_id}", timeout=30)
        if response.status_code == 404:
            return GithubRunState(
                run_id=run_id,
                repository=repo,
                found=False,
                status="not_found",
                conclusion="",
                html_url=self.build_run_url(run_id),
            )
        if response.status_code == 401:
            raise PocError("GitHub Actions run lookup authentication failed")
        response.raise_for_status()
        payload = response.json()
        return GithubRunState(
            run_id=str(run_id),
            repository=repo,
            found=True,
            status=str(payload.get("status", "")),
            conclusion=str(payload.get("conclusion", "") or ""),
            html_url=str(payload.get("html_url", "") or self.build_run_url(run_id)),
        )
    def dispatch_workflow(self, repository: str, workflow: str, ref: str, inputs: dict | None = None) -> datetime:
        repo = (repository or "").strip() or self.repository
        if not repo:
            raise PocError("GitHub repository is required to dispatch workflow")
        if not workflow:
            raise PocError("Workflow file name is required to dispatch workflow")
        payload = {"ref": ref or "main"}
        if inputs:
            payload["inputs"] = inputs
        response = self.session.post(
            f"{self.api_base}/repos/{repo}/actions/workflows/{workflow}/dispatches",
            json=payload,
            timeout=30,
        )
        if response.status_code == 404:
            raise PocError(f"Workflow dispatch failed: repo={repo} workflow={workflow} not found")
        if response.status_code == 401:
            raise PocError("Workflow dispatch authentication failed")
        if response.status_code not in {200, 201, 202, 204}:
            raise PocError(f"Workflow dispatch failed: status={response.status_code} body={response.text}")
        return datetime.now(timezone.utc)

    def _parse_github_time(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def find_recent_workflow_run(self, repository: str, workflow: str, since: datetime | None = None) -> dict:
        repo = (repository or "").strip() or self.repository
        if not repo:
            raise PocError("GitHub repository is required to inspect workflow runs")
        if not workflow:
            raise PocError("Workflow file name is required to inspect workflow runs")
        response = self.session.get(
            f"{self.api_base}/repos/{repo}/actions/workflows/{workflow}/runs?event=workflow_dispatch&per_page=10",
            timeout=30,
        )
        if response.status_code == 404:
            raise PocError(f"Workflow runs not found for repo={repo} workflow={workflow}")
        if response.status_code == 401:
            raise PocError("Workflow run lookup authentication failed")
        response.raise_for_status()
        payload = response.json()
        runs = payload.get("workflow_runs", []) or []
        for run in runs:
            created_at = self._parse_github_time(str(run.get("created_at", "")))
            if since and created_at and created_at < since:
                continue
            return {
                "id": str(run.get("id", "")),
                "status": str(run.get("status", "")),
                "conclusion": str(run.get("conclusion", "")) or "",
                "html_url": str(run.get("html_url", "")) or self.build_run_url(str(run.get("id", ""))),
                "created_at": str(run.get("created_at", "")),
                "head_branch": str(run.get("head_branch", "")),
            }
        return {}

    def wait_for_workflow_completion(
        self,
        repository: str,
        workflow: str,
        since: datetime | None,
        timeout_seconds: int,
        poll_seconds: int,
    ) -> dict:
        deadline = time.time() + max(1, int(timeout_seconds))
        poll = max(5, int(poll_seconds))
        last_seen = {}
        while time.time() < deadline:
            run = self.find_recent_workflow_run(repository, workflow, since)
            if run:
                last_seen = run
                if run.get("status") == "completed":
                    return run
            time.sleep(poll)
        if last_seen:
            raise PocError(
                f"Timed out waiting for workflow completion for {repository}/{workflow}; "
                f"last_status={last_seen.get('status')} conclusion={last_seen.get('conclusion')} url={last_seen.get('html_url')}"
            )
        raise PocError(f"Timed out waiting for workflow completion for {repository}/{workflow} (no run detected)")

