from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .argocd_client import ArgoCdClient
from .gitops_repo import GitOpsRepoManager
from .github_client import GithubActionsClient
from .jira_client import JiraClient
from .postchecks import run_postchecks
from .prechecks import run_prechecks
from .reporting import write_reports
from .state_manager import DeploymentStateManager
from .target_resolver import resolve_target
from .utils import PocError, parse_ticket_description, read_yaml, repo_root
from .validators import validate_metadata, validate_target, validate_version_resolution


def load_configs(root: Path) -> dict:
    config_dir = root / "config"
    return {
        "projects": read_yaml(config_dir / "projects.yaml"),
        "app_mapping": read_yaml(config_dir / "app_mapping.yaml"),
        "environments": read_yaml(config_dir / "environments.yaml"),
        "jira_field_mapping": read_yaml(config_dir / "jira_field_mapping.yaml"),
        "global": read_yaml(config_dir / "global.yaml"),
        "policy": read_yaml(config_dir / "deployment_policy.yaml"),
    }


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Jira-driven GitOps deployment POC")
    parser.add_argument("--jira-ticket", required=True)
    parser.add_argument("--trigger-argocd-sync", action="store_true")
    parser.add_argument("--argocd-timeout-seconds", type=int, default=600)
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--rollback-to-last-success", action="store_true")
    args = parser.parse_args()

    root = repo_root()
    configs = load_configs(root)

    try:
        run_id = os.environ.get("GITHUB_RUN_ID", "local-run")
        jira = JiraClient(
            os.environ["JIRA_BASE_URL"],
            os.environ["JIRA_EMAIL"],
            os.environ["JIRA_API_TOKEN"],
        )
        issue = jira.fetch_issue(args.jira_ticket)
        metadata = parse_ticket_description(issue.description, configs["jira_field_mapping"])
        validate_metadata(metadata, configs["global"], configs["environments"], configs["jira_field_mapping"])
        target = resolve_target(metadata, configs["projects"], configs["app_mapping"], configs["environments"])
        validate_target(target)
        validate_version_resolution(target)
        test_mode = args.test_mode or env_flag("TEST_MODE")
        if args.rollback_to_last_success and not read_yaml(root / "config" / "deployment_policy.yaml").get("policy", {}).get("manual_rollback_enabled", True):
            raise PocError("Manual rollback is disabled by deployment_policy.yaml")
        target["previous_version"] = ""
        git_user = os.environ.get("DEPLOY_GIT_USER", "deployment-poc[bot]")
        git_email = os.environ.get("DEPLOY_GIT_EMAIL", "deployment-poc@users.noreply.github.com")
        policy = configs["policy"]
        github_client = GithubActionsClient(
            root,
            repository=os.environ.get("GITHUB_REPOSITORY"),
            api_token=os.environ.get("GITHUB_API_TOKEN"),
        )
        state_manager = DeploymentStateManager(root, policy, git_user, git_email, github_client, test_mode)

        argocd = ArgoCdClient(
            os.environ.get("ARGOCD_SERVER"),
            os.environ.get("ARGOCD_AUTH_TOKEN"),
            insecure=env_flag("ARGOCD_INSECURE"),
        )
        previous_state = state_manager.get_last_successful_state(target)
        target["previous_version"] = previous_state.get("last_version", "")
        lock_result = state_result = {}
        rollback_result = {}
        deployment_action = "deploy"
        current_tag = ""
        gitops_commit = ""
        desired_version = target["resolved_version"]
        requested_version = target["requested_version"]
        rollback_source_version = ""
        workflow_name = os.environ.get("GITHUB_WORKFLOW", "Deploy From Jira")
        actor = os.environ.get("GITHUB_ACTOR", "")
        repository = os.environ.get("GITHUB_REPOSITORY", github_client.repository if github_client else "")
        run_url = (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com').rstrip('/')}/{repository}/actions/runs/{run_id}"
            if repository and run_id not in {"", "local-run"}
            else ""
        )

        if args.rollback_to_last_success:
            rollback_version = previous_state.get("last_version", "").strip()
            if not rollback_version:
                raise PocError(
                    f"No last successful deployment state exists for {target['project_key']}/{target['app_key']} "
                    f"in {target['environment']}, so rollback cannot proceed"
                )
            desired_version = rollback_version
            requested_version = rollback_version
            deployment_action = "rollback_requested"

        lock_result = state_manager.acquire_lock(
            target,
            issue.key,
            run_id,
            requested_version,
            desired_version,
            actor=actor,
            runner_name=os.environ.get("RUNNER_NAME", ""),
            repository=repository,
            workflow_name=workflow_name,
            run_url=run_url,
        )

        argocd_status = None
        with GitOpsRepoManager(
            target["gitops_repo"],
            target["gitops_branch"],
            os.environ.get("INFRA_PAT", ""),
        ) as gitops:
            current_tag = gitops.get_current_image_tag(target["values_path"])
            current_revision = gitops.get_current_revision()
            prechecks = run_prechecks(target, gitops.repo_dir, argocd)
            rollback_source_version = current_tag

            already_successful_same_ticket = (
                previous_state.get("last_status") == "success"
                and previous_state.get("last_ticket") == issue.key
                and previous_state.get("last_version") == desired_version
            )

            already_successful_same_version = (
                previous_state.get("last_status") == "success"
                and previous_state.get("last_version") == desired_version
            )

            if current_tag == desired_version:
                if test_mode:
                    deployment_action = "reconciled"
                    gitops_commit = current_revision
                    argocd_status = {
                        "sync": "Synced",
                        "health": "Healthy",
                        "revision": gitops_commit,
                        "operation_revision": gitops_commit,
                        "operation_phase": "Succeeded",
                        "raw": {"simulated": True},
                    }
                elif argocd.configured():
                    if args.trigger_argocd_sync:
                        argocd.sync_app(target["argocd_app"])
                    argocd_status = argocd.wait_until_synced_and_healthy(
                        target["argocd_app"],
                        timeout_seconds=args.argocd_timeout_seconds,
                        expected_revision=current_revision,
                    )
                    gitops_commit = current_revision
                    if args.rollback_to_last_success:
                        deployment_action = "rollback_skipped"
                    elif already_successful_same_ticket or already_successful_same_version:
                        deployment_action = "already_deployed"
                    else:
                        deployment_action = "reconciled"
                else:
                    raise PocError(
                        f"Target {target['app_key']} in {target['environment']} is already at version "
                        f"{desired_version}, but ArgoCD verification is not configured"
                    )
            else:
                updated_file = gitops.update_image_tag(target["values_path"], desired_version)
                commit_message = (
                    f"rollback({target['app_key']}): jira-{issue.key} -> {desired_version}"
                    if args.rollback_to_last_success
                    else f"deploy({target['app_key']}): jira-{issue.key} -> {desired_version}"
                )
                gitops_commit = gitops.commit_and_push(
                    updated_file,
                    commit_message,
                    git_user,
                    git_email,
                    test_mode=test_mode,
                )
                try:
                    if test_mode:
                        argocd_status = {
                            "sync": "Synced",
                            "health": "Healthy",
                            "revision": gitops_commit,
                            "operation_revision": gitops_commit,
                            "operation_phase": "Succeeded",
                            "raw": {"simulated": True},
                        }
                    elif argocd.configured():
                        if args.trigger_argocd_sync:
                            argocd.sync_app(target["argocd_app"])
                        argocd_status = argocd.wait_until_synced_and_healthy(
                            target["argocd_app"],
                            timeout_seconds=args.argocd_timeout_seconds,
                            expected_revision=gitops_commit,
                        )
                    deployment_action = (
                        "rollback_test_mode"
                        if args.rollback_to_last_success and test_mode
                        else "rolled_back"
                        if args.rollback_to_last_success
                        else "test_mode"
                        if test_mode
                        else "deployed"
                    )
                except PocError as deploy_error:
                    if (
                        not args.rollback_to_last_success
                        and not test_mode
                        and policy.get("policy", {}).get("auto_rollback_enabled", False)
                        and previous_state.get("last_version")
                        and previous_state.get("last_version") != desired_version
                    ):
                        rollback_version = previous_state["last_version"]
                        rollback_file = gitops.update_image_tag(target["values_path"], rollback_version)
                        rollback_commit = gitops.commit_and_push(
                            rollback_file,
                            f"rollback({target['app_key']}): jira-{issue.key} -> {rollback_version}",
                            git_user,
                            git_email,
                            test_mode=False,
                        )
                        rollback_status = argocd.wait_until_synced_and_healthy(
                            target["argocd_app"],
                            timeout_seconds=args.argocd_timeout_seconds,
                            expected_revision=rollback_commit,
                        )
                        rollback_result = {
                            "performed": True,
                            "rollback_version": rollback_version,
                            "rollback_commit": rollback_commit,
                            "rollback_status": rollback_status,
                        }
                    raise deploy_error

        postchecks = run_postchecks(target, argocd_status)
        target["effective_version"] = desired_version
        if rollback_source_version and deployment_action in {"rolled_back", "rollback_skipped", "rollback_test_mode"}:
            target["rollback_source_version"] = rollback_source_version
        state_result = state_manager.mark_success(
            target,
            issue.key,
            gitops_commit,
            argocd_status or {},
            target["values_path"],
            deployed_version=desired_version,
            requested_version=requested_version,
            action=deployment_action,
            rollback_source_version=rollback_source_version if deployment_action in {"rolled_back", "rollback_skipped", "rollback_test_mode"} else "",
        )
        lock_result = state_manager.release_lock(target, issue.key, "released", deployment_action)
        result = {
            "jira_ticket": issue.key,
            "issue_summary": issue.summary,
            "metadata": metadata,
            "target": target,
            "deployment_action": deployment_action,
            "gitops_commit": gitops_commit,
            "changed_file": target["values_path"],
            "runner_name": os.environ.get("RUNNER_NAME", ""),
            "workflow_run_id": run_id,
            "workflow_run_url": run_url,
            "test_mode": test_mode,
            "outcome": "success",
            "prechecks_json": json.dumps(prechecks, indent=2),
            "argocd_status_json": json.dumps(argocd_status or {}, indent=2),
            "lock_json": json.dumps(lock_result, indent=2),
            "state_json": json.dumps(state_result, indent=2),
            "rollback_json": json.dumps(rollback_result, indent=2),
            "postchecks_json": json.dumps(postchecks, indent=2),
        }
        write_reports(root, result)
        print(json.dumps(result, indent=2))
        return 0
    except PocError as exc:
        failure_lock = {}
        failure_state = {}
        failure_rollback = locals().get("rollback_result", {})
        try:
            if "state_manager" in locals() and "target" in locals() and "issue" in locals():
                failure_lock = state_manager.release_lock(
                    target,
                    issue.key,
                    "released",
                    f"failure: {exc}",
                )
        except Exception:
            failure_lock = {"release_error": "failed to release lock after error"}
        result = {
            "jira_ticket": args.jira_ticket,
            "deployment_action": "failed",
            "outcome": "failure",
            "error": str(exc),
            "workflow_run_id": locals().get("run_id", ""),
            "workflow_run_url": locals().get("run_url", ""),
            "prechecks_json": "{}",
            "argocd_status_json": "{}",
            "lock_json": json.dumps(failure_lock, indent=2),
            "state_json": json.dumps(failure_state, indent=2),
            "rollback_json": json.dumps(failure_rollback, indent=2),
            "postchecks_json": "{}",
            "target": {
                "project_key": "",
                "app_key": "",
                "environment": "",
                "gitops_repo": "",
                "gitops_branch": "",
                "values_path": "",
                "argocd_app": "",
                "namespace": "",
                "effective_version": "",
            },
        }
        write_reports(root, result)
        print(json.dumps(result, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
