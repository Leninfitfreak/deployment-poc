from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .utils import PocError, read_yaml, run, write_yaml


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


class DeploymentStateManager:
    def __init__(self, repo_root: Path, policy: dict, git_name: str, git_email: str, test_mode: bool = False) -> None:
        self.repo_root = repo_root
        self.config_dir = repo_root / "config"
        self.state_path = self.config_dir / "deployment_state.yaml"
        self.lock_path = self.config_dir / "deploy_locks.yaml"
        self.policy = policy.get("policy", {})
        self.git_name = git_name
        self.git_email = git_email
        self.test_mode = test_mode

    def _sync_latest(self) -> None:
        if self.test_mode:
            return
        run(["git", "pull", "--rebase", "origin", "main"], cwd=self.repo_root)

    def _commit_and_push(self, paths: list[Path], message: str) -> str:
        run(["git", "config", "user.name", self.git_name], cwd=self.repo_root)
        run(["git", "config", "user.email", self.git_email], cwd=self.repo_root)
        for path in paths:
            run(["git", "add", str(path.relative_to(self.repo_root))], cwd=self.repo_root)
        try:
            run(["git", "commit", "-m", message], cwd=self.repo_root)
        except Exception:
            return run(["git", "rev-parse", "HEAD"], cwd=self.repo_root)
        if self.test_mode:
            return f"test-mode-{run(['git', 'rev-parse', '--short', 'HEAD'], cwd=self.repo_root)}"
        run(["git", "push", "origin", "main"], cwd=self.repo_root)
        return run(["git", "rev-parse", "HEAD"], cwd=self.repo_root)

    def _load_state(self) -> dict:
        return read_yaml(self.state_path) or {"deployments": {}}

    def _save_state(self, payload: dict) -> None:
        write_yaml(self.state_path, payload)

    def _load_locks(self) -> dict:
        return read_yaml(self.lock_path) or {"locks": {}}

    def _save_locks(self, payload: dict) -> None:
        write_yaml(self.lock_path, payload)

    @staticmethod
    def _deployment_key(target: dict) -> str:
        return f"{target['project_key']}/{target['app_key']}"

    def get_last_successful_state(self, target: dict) -> dict:
        state = self._load_state()
        return (
            state.get("deployments", {})
            .get(self._deployment_key(target), {})
            .get(target["environment"], {})
        )

    def acquire_lock(self, target: dict, jira_ticket: str, run_id: str, requested_version: str) -> dict:
        self._sync_latest()
        locks = self._load_locks()
        deployment_key = self._deployment_key(target)
        env_locks = locks.setdefault("locks", {}).setdefault(deployment_key, {})
        existing = env_locks.get(target["environment"])
        if existing:
            acquired_at = parse_iso_timestamp(existing.get("acquired_at"))
            timeout_minutes = int(self.policy.get("lock_timeout_minutes", 30))
            stale = acquired_at and acquired_at < datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
            if existing.get("status") == "in_progress" and not stale:
                raise PocError(
                    f"Deployment lock active for {deployment_key} in {target['environment']} "
                    f"(ticket={existing.get('ticket')}, run={existing.get('run_id')})"
                )
        lock_entry = {
            "ticket": jira_ticket,
            "run_id": run_id,
            "requested_version": requested_version,
            "resolved_version": target["resolved_version"],
            "acquired_at": utc_now_iso(),
            "status": "in_progress",
        }
        env_locks[target["environment"]] = lock_entry
        self._save_locks(locks)
        commit = self._commit_and_push(
            [self.lock_path],
            f"chore(lock): acquire {target['app_key']} {target['environment']} for {jira_ticket}",
        )
        return {"entry": lock_entry, "commit": commit}

    def release_lock(self, target: dict, jira_ticket: str, status: str, note: str = "") -> dict:
        self._sync_latest()
        locks = self._load_locks()
        deployment_key = self._deployment_key(target)
        env_locks = locks.setdefault("locks", {}).setdefault(deployment_key, {})
        existing = env_locks.get(target["environment"], {})
        env_locks[target["environment"]] = {
            **existing,
            "ticket": jira_ticket,
            "status": status,
            "released_at": utc_now_iso(),
            "note": note,
        }
        self._save_locks(locks)
        commit = self._commit_and_push(
            [self.lock_path],
            f"chore(lock): release {target['app_key']} {target['environment']} for {jira_ticket}",
        )
        return {"entry": env_locks[target["environment"]], "commit": commit}

    def mark_success(self, target: dict, jira_ticket: str, gitops_commit: str, argocd_status: dict, changed_file: str) -> dict:
        self._sync_latest()
        state = self._load_state()
        deployment_key = self._deployment_key(target)
        env_state = state.setdefault("deployments", {}).setdefault(deployment_key, {})
        previous = env_state.get(target["environment"], {})
        env_state[target["environment"]] = {
            "last_version": target["resolved_version"],
            "last_requested_version": target["requested_version"],
            "last_gitops_commit": gitops_commit,
            "last_ticket": jira_ticket,
            "last_argocd_app": target["argocd_app"],
            "last_changed_file": changed_file,
            "last_deployed_at": utc_now_iso(),
            "last_status": "success",
            "last_sync_status": argocd_status.get("sync"),
            "last_health_status": argocd_status.get("health"),
            "previous_successful_version": previous.get("last_version"),
            "previous_successful_gitops_commit": previous.get("last_gitops_commit"),
        }
        self._save_state(state)
        commit = self._commit_and_push(
            [self.state_path],
            f"chore(state): record {target['app_key']} {target['environment']} deployment for {jira_ticket}",
        )
        return {"entry": env_state[target["environment"]], "commit": commit}

