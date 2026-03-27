from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .argocd_client import ArgoCdClient
from .gitops_repo import GitOpsRepoManager
from .github_client import GithubActionsClient
from .jira_client import JiraClient, JiraIssue
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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def jira_feedback_mode(result: dict) -> str:
    action = (result.get("deployment_action") or "").strip()
    outcome = (result.get("outcome") or "").strip()
    if outcome == "failure" or action == "failed":
        return "failure"
    if action in {"already_deployed", "rollback_skipped"}:
        return action
    return "success"


def build_jira_comment(result: dict) -> str:
    mode = jira_feedback_mode(result)
    target = result.get("target", {}) or {}
    argocd_status = {}
    try:
        argocd_status = json.loads(result.get("argocd_status_json", "{}") or "{}")
    except Exception:
        argocd_status = {}

    label = {
        "success": "SUCCESS",
        "failure": "FAILURE",
        "already_deployed": "ALREADY_DEPLOYED",
        "rollback_skipped": "ROLLBACK_SKIPPED",
    }.get(mode, mode.upper())

    lines = [
        f"Deployment result: {label}",
        f"Jira ticket: {result.get('jira_ticket', '')}",
        f"Component: {target.get('app_key', '')}",
        f"Environment: {target.get('environment', '')}",
        f"Requested version: {target.get('requested_version', '')}",
        f"Resolved deployable version: {target.get('resolved_version', '')}",
        f"Deployment action: {result.get('deployment_action', '')}",
    ]
    if result.get("gitops_commit"):
        lines.append(f"GitOps commit SHA: {result.get('gitops_commit', '')}")
    if result.get("changed_file"):
        lines.append(f"GitOps file: {result.get('changed_file', '')}")
    if target.get("argocd_app"):
        lines.append(f"ArgoCD application: {target.get('argocd_app', '')}")
    if argocd_status:
        lines.append(f"Final Sync status: {argocd_status.get('sync', '')}")
        lines.append(f"Final Health status: {argocd_status.get('health', '')}")
        lines.append(f"Observed revision: {argocd_status.get('revision', '')}")
    if result.get("workflow_run_url"):
        lines.append(f"Workflow run URL: {result.get('workflow_run_url', '')}")
    if result.get("error"):
        lines.append(f"Error summary: {result.get('error', '')}")
    if mode == "already_deployed":
        lines.append("No new GitOps deployment was needed because the requested version was already active and verified.")
    if mode == "rollback_skipped":
        lines.append("Rollback request did not create a new deployment because the last successful version was already active and verified.")
    lines.append(f"Timestamp: {utc_now_iso()}")
    return "\n".join(line for line in lines if str(line).strip())


def apply_jira_feedback(jira: JiraClient | None, issue: JiraIssue | None, result: dict, global_config: dict) -> dict:
    config = (global_config or {}).get("jira_feedback", {}) or {}
    feedback = {
        "enabled": bool(config.get("enabled", False)),
        "mode": jira_feedback_mode(result),
        "jira_comment_added": False,
        "jira_transition_attempted": False,
        "jira_transition_result": "skipped",
        "jira_transition_name_used": "",
        "jira_feedback_error": "",
        "current_status": "",
        "final_status": "",
        "available_transitions": [],
        "comment_attempted": False,
        "comment_result": "skipped",
        "policy_requires_transition_success": bool(config.get("require_transition_success", False)),
        "policy_satisfied": True,
    }
    if not feedback["enabled"]:
        feedback["jira_feedback_error"] = "Jira feedback disabled by config"
        return feedback
    if not jira:
        feedback["jira_feedback_error"] = "Jira client unavailable for feedback"
        return feedback
    if not issue:
        feedback["jira_feedback_error"] = "Jira issue details unavailable for feedback"
        return feedback

    transition_candidates = (config.get("transition_name_candidates", {}) or {}).get(feedback["mode"], []) or []
    comment_policy = config.get("comment_on", {}) or {}
    should_comment = (
        comment_policy.get("failure", True)
        if feedback["mode"] == "failure"
        else comment_policy.get("noop", True)
        if feedback["mode"] in {"already_deployed", "rollback_skipped"}
        else comment_policy.get("success", True)
    )

    try:
        current_issue, transition, transitions = jira.resolve_transition(issue.key, transition_candidates)
        feedback["current_status"] = current_issue.status_name
        feedback["available_transitions"] = [
            {
                "id": item.id,
                "name": item.name,
                "to_status_name": item.to_status_name,
            }
            for item in transitions
        ]
        normalized_candidates = {name.strip().casefold(): name for name in transition_candidates if str(name).strip()}
        if current_issue.status_name.strip().casefold() in normalized_candidates:
            feedback["jira_transition_result"] = "skipped_already_in_target_status"
            feedback["jira_transition_name_used"] = normalized_candidates[current_issue.status_name.strip().casefold()]
            feedback["final_status"] = current_issue.status_name
        elif transition:
            feedback["jira_transition_attempted"] = True
            feedback["jira_transition_name_used"] = transition.name or transition.to_status_name
            jira.transition_issue(issue.key, transition.id)
            refreshed = jira.fetch_issue(issue.key)
            feedback["jira_transition_result"] = "success"
            feedback["final_status"] = refreshed.status_name
        else:
            feedback["jira_transition_result"] = "skipped_unavailable"
            feedback["jira_feedback_error"] = (
                f"No configured Jira transition is available from status '{current_issue.status_name}' "
                f"for mode '{feedback['mode']}'"
            )
            feedback["final_status"] = current_issue.status_name
    except Exception as exc:
        feedback["jira_transition_result"] = "failure"
        feedback["jira_feedback_error"] = str(exc)

    if should_comment:
        feedback["comment_attempted"] = True
        try:
            jira.add_comment(issue.key, build_jira_comment(result))
            feedback["jira_comment_added"] = True
            feedback["comment_result"] = "success"
        except Exception as exc:
            feedback["comment_result"] = "failure"
            if feedback["jira_feedback_error"]:
                feedback["jira_feedback_error"] = f"{feedback['jira_feedback_error']}; comment failed: {exc}"
            else:
                feedback["jira_feedback_error"] = f"comment failed: {exc}"
    feedback["policy_satisfied"] = (
        feedback["jira_transition_result"] in {"success", "skipped_already_in_target_status", "skipped"}
        and feedback["comment_result"] in {"success", "skipped"}
    )
    return feedback


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

    jira: JiraClient | None = None
    issue: JiraIssue | None = None
    jira_feedback_result: dict = {}
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
        lock_acquire_result = {}
        lock_release_result = {}
        state_result = {}
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

        lock_acquire_result = state_manager.acquire_lock(
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
        lock_release_result = state_manager.release_lock(target, issue.key, "released", deployment_action)
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
            "lock_json": json.dumps(
                {
                    "acquire": lock_acquire_result,
                    "release": lock_release_result,
                },
                indent=2,
            ),
            "state_json": json.dumps(state_result, indent=2),
            "rollback_json": json.dumps(rollback_result, indent=2),
            "postchecks_json": json.dumps(postchecks, indent=2),
        }
        jira_feedback_result = apply_jira_feedback(jira, issue, result, configs["global"])
        result["jira_feedback_json"] = json.dumps(jira_feedback_result, indent=2)
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
            "lock_json": json.dumps(
                {
                    "acquire": locals().get("lock_acquire_result", {}),
                    "release": failure_lock,
                },
                indent=2,
            ),
            "state_json": json.dumps(failure_state, indent=2),
            "rollback_json": json.dumps(failure_rollback, indent=2),
            "postchecks_json": "{}",
            "jira_feedback_json": "{}",
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
        try:
            jira_feedback_result = apply_jira_feedback(jira, issue, result, configs["global"])
            result["jira_feedback_json"] = json.dumps(jira_feedback_result, indent=2)
        except Exception as jira_feedback_exc:
            result["jira_feedback_json"] = json.dumps(
                {
                    "enabled": bool(configs.get("global", {}).get("jira_feedback", {}).get("enabled", False)),
                    "jira_comment_added": False,
                    "jira_transition_attempted": False,
                    "jira_transition_result": "failure",
                    "jira_transition_name_used": "",
                    "jira_feedback_error": str(jira_feedback_exc),
                    "comment_attempted": False,
                    "comment_result": "failure",
                },
                indent=2,
            )
        write_reports(root, result)
        print(json.dumps(result, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
