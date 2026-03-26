from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .utils import PocError, embed_token_in_https_url, read_yaml, run, write_yaml


class GitOpsRepoManager:
    def __init__(self, repo_url: str, branch: str, token: str) -> None:
        self.repo_url = repo_url
        self.branch = branch
        self.token = token
        self.work_dir = Path(tempfile.mkdtemp(prefix="deployment-poc-"))
        self.repo_dir = self.work_dir / "repo"

    def clone(self) -> Path:
        if not self.token:
            raise PocError("INFRA_PAT is required to clone and push the GitOps repo from deployment-poc")
        authed_url = embed_token_in_https_url(self.repo_url, self.token)
        run(["git", "clone", "--branch", self.branch, authed_url, str(self.repo_dir)])
        return self.repo_dir

    def update_image_tag(self, values_path: str, new_tag: str) -> Path:
        file_path = self.repo_dir / values_path
        if not file_path.exists():
            raise PocError(f"Values file not found: {file_path}")
        payload = read_yaml(file_path)
        payload.setdefault("image", {})
        payload["image"]["tag"] = str(new_tag)
        write_yaml(file_path, payload)
        return file_path

    def commit_and_push(self, file_path: Path, commit_message: str, git_name: str, git_email: str) -> None:
        run(["git", "config", "user.name", git_name], cwd=self.repo_dir)
        run(["git", "config", "user.email", git_email], cwd=self.repo_dir)
        run(["git", "add", str(file_path.relative_to(self.repo_dir))], cwd=self.repo_dir)
        try:
            run(["git", "commit", "-m", commit_message], cwd=self.repo_dir)
        except Exception:
            return
        run(["git", "pull", "--rebase", "origin", self.branch], cwd=self.repo_dir)
        run(["git", "push", "origin", self.branch], cwd=self.repo_dir)

    def cleanup(self) -> None:
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def __enter__(self) -> "GitOpsRepoManager":
        self.clone()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

