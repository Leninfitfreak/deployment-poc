from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .github_client import GithubActionsClient
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
    def __init__(
        self,
        repo_root: Path,
        policy: dict,
        git_name: str,
        git_email: str,
        github_client: GithubActionsClient | None = None,
        test_mode: bool = False,
    ) -> None:
        self.repo_root = repo_root
        self.config_dir = repo_root / "config"
        self.state_path = self.config_dir / "deployment_state.yaml"
        self.lock_path = self.config_dir / "deploy_locks.yaml"
        self.policy = policy.get("policy", {})
        self.git_name = git_name
        self.git_email = git_email
        self.github_client = github_client
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

    def get_lock_state(self, target: dict) -> dict:
        locks = self._load_locks()
        return (
            locks.get("locks", {})
            .get(self._deployment_key(target), {})
            .get(target["environment"], {})
        )

    def inspect_lock(self, target: dict) -> dict:
        existing = self.get_lock_state(target)
        deployment_key = self._deployment_key(target)
        now = datetime.now(timezone.utc)
        timeout_minutes = int(self.policy.get("lock_timeout_minutes", 30))
        stale_check_enabled = bool(self.policy.get("stale_lock_check_enabled", True))
        unlock_requires_run_check = bool(self.policy.get("unlock_requires_run_check", True))
        auto_release_stale_locks = bool(self.policy.get("auto_release_stale_locks", True))

        if not existing:
            return {
                "deployment_key": deployment_key,
                "environment": target["environment"],
                "present": False,
                "blocking": False,
                "classification": "no_lock",
                "lock": {},
            }

        status = str(existing.get("status", "") or "")
        acquired_at = parse_iso_timestamp(existing.get("acquired_at"))
        last_updated_at = parse_iso_timestamp(existing.get("last_updated_at")) or acquired_at
        age_minutes = None
        if last_updated_at:
            age_minutes = round((now - last_updated_at).total_seconds() / 60, 2)
        timed_out = bool(
            stale_check_enabled
            and last_updated_at
            and last_updated_at < now - timedelta(minutes=timeout_minutes)
        )

        run_state_payload = {
            "checked": False,
            "status": "",
            "conclusion": "",
            "active": False,
            "finished": False,
            "html_url": existing.get("run_url", ""),
            "found": False,
        }

        run_id = str(existing.get("run_id", "") or "").strip()
        repository = str(existing.get("repository", "") or "").strip()
        if run_id and self.github_client and self.github_client.configured():
            try:
                run_state = self.github_client.get_run_state(run_id, repository or None)
                run_state_payload = {
                    "checked": True,
                    "status": run_state.status,
                    "conclusion": run_state.conclusion,
                    "active": run_state.active,
                    "finished": run_state.finished,
                    "html_url": run_state.html_url,
                    "found": run_state.found,
                }
            except Exception as exc:
                run_state_payload = {
                    "checked": True,
                    "status": "lookup_failed",
                    "conclusion": "",
                    "active": False,
                    "finished": False,
                    "html_url": existing.get("run_url", ""),
                    "found": False,
                    "error": str(exc),
                }

        classification = "released"
        blocking = False
        stale_candidate = False
        auto_recoverable = False
        reason = ""

        if status == "in_progress":
            blocking = True
            classification = "active"
            reason = f"Deployment lock active for {deployment_key} in {target['environment']}"
            if timed_out:
                stale_candidate = True
                classification = "stale_candidate"
                reason = (
                    f"Deployment lock for {deployment_key} in {target['environment']} exceeded "
                    f"{timeout_minutes} minute timeout"
                )
                if run_state_payload["checked"]:
                    if run_state_payload["active"]:
                        classification = "active"
                        stale_candidate = False
                        reason = (
                            f"Deployment lock still belongs to an active workflow run "
                            f"{existing.get('run_id')}"
                        )
                    elif run_state_payload["found"] or run_state_payload["status"] == "not_found":
                        if auto_release_stale_locks:
                            auto_recoverable = True
                            classification = "stale_auto_recoverable"
                            reason = (
                                f"Deployment lock is stale because workflow run {existing.get('run_id')} "
                                f"is no longer active"
                            )
                        else:
                            classification = "stale_manual_required"
                            reason = (
                                f"Deployment lock is stale, but auto recovery is disabled by policy"
                            )
                    elif unlock_requires_run_check:
                        classification = "stale_manual_required"
                        reason = (
                            "Deployment lock exceeded timeout, but workflow run status could not be verified"
                        )
                elif unlock_requires_run_check:
                    classification = "stale_manual_required"
                    reason = (
                        "Deployment lock exceeded timeout, but no workflow run verification is configured"
                    )
                elif auto_release_stale_locks:
                    auto_recoverable = True
                    classification = "stale_auto_recoverable"
                    reason = "Deployment lock exceeded timeout and policy allows time-based auto recovery"
                else:
                    classification = "stale_manual_required"
                    reason = "Deployment lock exceeded timeout and manual unlock is required by policy"
        else:
            blocking = False
            classification = status or "released"
            reason = f"Deployment lock is non-blocking with status '{classification}'"

        return {
            "deployment_key": deployment_key,
            "environment": target["environment"],
            "present": True,
            "blocking": blocking,
            "classification": classification,
            "stale_candidate": stale_candidate,
            "auto_recoverable": auto_recoverable,
            "age_minutes": age_minutes,
            "timeout_minutes": timeout_minutes,
            "run_state": run_state_payload,
            "lock": existing,
            "reason": reason,
        }

    def acquire_lock(
        self,
        target: dict,
        jira_ticket: str,
        run_id: str,
        requested_version: str,
        resolved_version: str,
        *,
        actor: str = "",
        runner_name: str = "",
        repository: str = "",
        workflow_name: str = "",
        run_url: str = "",
    ) -> dict:
        self._sync_latest()
        evaluation = self.inspect_lock(target)
        stale_recovery = {}

        if evaluation["blocking"]:
            if evaluation["classification"] == "stale_auto_recoverable":
                stale_recovery = self.force_release_lock(
                    target,
                    jira_ticket=jira_ticket,
                    status="force_released",
                    note=f"auto-recovered stale lock before {jira_ticket}",
                    reason=evaluation["reason"],
                    actor=actor,
                    runner_name=runner_name,
                    repository=repository,
                )
                self._sync_latest()
            elif evaluation["classification"] == "stale_manual_required":
                raise PocError(
                    f"{evaluation['reason']}. Use the unlock-deployment-lock workflow to inspect and release it safely."
                )
            else:
                existing = evaluation["lock"]
                raise PocError(
                    f"Deployment lock active for {evaluation['deployment_key']} in {target['environment']} "
                    f"(ticket={existing.get('ticket')}, run={existing.get('run_id')})"
                )

        locks = self._load_locks()
        deployment_key = self._deployment_key(target)
        env_locks = locks.setdefault("locks", {}).setdefault(deployment_key, {})
        now = utc_now_iso()
        lock_entry = {
            "app_key": target["app_key"],
            "environment": target["environment"],
            "ticket": jira_ticket,
            "run_id": run_id,
            "run_url": run_url or (self.github_client.build_run_url(run_id) if self.github_client and run_id else ""),
            "requested_version": requested_version,
            "resolved_version": resolved_version,
            "actor": actor,
            "runner_name": runner_name,
            "repository": repository or (self.github_client.repository if self.github_client else ""),
            "workflow_name": workflow_name,
            "acquired_at": now,
            "last_updated_at": now,
            "status": "in_progress",
        }
        env_locks[target["environment"]] = lock_entry
        self._save_locks(locks)
        commit = self._commit_and_push(
            [self.lock_path],
            f"chore(lock): acquire {target['app_key']} {target['environment']} for {jira_ticket}",
        )
        return {
            "entry": lock_entry,
            "commit": commit,
            "previous_lock_evaluation": evaluation,
            "stale_recovery": stale_recovery,
        }

    def release_lock(self, target: dict, jira_ticket: str, status: str, note: str = "") -> dict:
        self._sync_latest()
        locks = self._load_locks()
        deployment_key = self._deployment_key(target)
        env_locks = locks.setdefault("locks", {}).setdefault(deployment_key, {})
        existing = env_locks.get(target["environment"], {})
        updated = {
            **existing,
            "ticket": jira_ticket or existing.get("ticket", ""),
            "status": status,
            "released_at": utc_now_iso(),
            "last_updated_at": utc_now_iso(),
            "note": note,
        }
        env_locks[target["environment"]] = updated
        self._save_locks(locks)
        commit = self._commit_and_push(
            [self.lock_path],
            f"chore(lock): release {target['app_key']} {target['environment']} for {jira_ticket or existing.get('ticket', 'manual')}",
        )
        return {"entry": updated, "commit": commit}

    def force_release_lock(
        self,
        target: dict,
        *,
        jira_ticket: str,
        status: str,
        note: str,
        reason: str,
        actor: str = "",
        runner_name: str = "",
        repository: str = "",
    ) -> dict:
        self._sync_latest()
        locks = self._load_locks()
        deployment_key = self._deployment_key(target)
        env_locks = locks.setdefault("locks", {}).setdefault(deployment_key, {})
        existing = env_locks.get(target["environment"])
        if not existing:
            raise PocError(f"No lock exists for {deployment_key} in {target['environment']}")
        updated = {
            **existing,
            "status": status,
            "released_at": utc_now_iso(),
            "last_updated_at": utc_now_iso(),
            "note": note,
            "force_release_reason": reason,
            "force_release_actor": actor,
            "force_release_runner": runner_name,
            "force_release_repository": repository,
            "force_release_ticket": jira_ticket,
        }
        env_locks[target["environment"]] = updated
        self._save_locks(locks)
        commit = self._commit_and_push(
            [self.lock_path],
            f"chore(lock): {status} {target['app_key']} {target['environment']} for {jira_ticket}",
        )
        return {"entry": updated, "commit": commit}

    def mark_success(
        self,
        target: dict,
        jira_ticket: str,
        gitops_commit: str,
        argocd_status: dict,
        changed_file: str,
        *,
        deployed_version: str,
        requested_version: str,
        action: str,
        rollback_source_version: str = "",
    ) -> dict:
        self._sync_latest()
        state = self._load_state()
        deployment_key = self._deployment_key(target)
        env_state = state.setdefault("deployments", {}).setdefault(deployment_key, {})
        previous = env_state.get(target["environment"], {})
        if previous.get("last_version") and previous.get("last_version") != deployed_version:
            previous_successful_version = previous.get("last_version")
            previous_successful_gitops_commit = previous.get("last_gitops_commit")
        else:
            previous_successful_version = previous.get("previous_successful_version")
            previous_successful_gitops_commit = previous.get("previous_successful_gitops_commit")
        env_state[target["environment"]] = {
            "last_version": deployed_version,
            "last_requested_version": requested_version,
            "last_gitops_commit": gitops_commit,
            "last_ticket": jira_ticket,
            "last_argocd_app": target["argocd_app"],
            "last_changed_file": changed_file,
            "last_deployed_at": utc_now_iso(),
            "last_status": "success",
            "last_action": action,
            "last_sync_status": argocd_status.get("sync"),
            "last_health_status": argocd_status.get("health"),
            "previous_successful_version": previous_successful_version,
            "previous_successful_gitops_commit": previous_successful_gitops_commit,
            "rollback_source_version": rollback_source_version or None,
        }
        self._save_state(state)
        commit = self._commit_and_push(
            [self.state_path],
            f"chore(state): record {target['app_key']} {target['environment']} deployment for {jira_ticket}",
        )
        return {"entry": env_state[target["environment"]], "commit": commit}
