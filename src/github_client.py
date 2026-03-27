from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
