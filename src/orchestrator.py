from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .argocd_client import ArgoCdClient
from .gitops_repo import GitOpsRepoManager
from .github_client import GithubActionsClient
from .jira_client import JiraClient, JiraIssue
from .jira_feedback import JiraProgressReporter, apply_final_jira_feedback
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
        "latest_tags": read_yaml(config_dir / "latest_tags.yaml"),
        "jira_field_mapping": read_yaml(config_dir / "jira_field_mapping.yaml"),
        "global": read_yaml(config_dir / "global.yaml"),
        "policy": read_yaml(config_dir / "deployment_policy.yaml"),
    }


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ensure_postchecks_success(postchecks: dict) -> None:
    status = str(postchecks.get("url_check_status", "")).strip().lower()
    if status == "failure":
        detail = str(postchecks.get("url_error") or postchecks.get("url_warning") or "Post-deployment URL check failed").strip()
        raise PocError(detail)



def normalize_action(value: str) -> str:
    action = (value or "").strip().lower()
    return action or "deploy"


def ensure_argocd_port_forward(root: Path) -> None:
    run(["cmd", "/c", "call", "scripts\\start-argocd-port-forward.cmd"], cwd=root)



def refresh_kubeconfig(target: dict, environments: dict) -> None:
    env = (target.get("environment") or "").strip()
    env_cfg = (environments.get("environments", {}) or {}).get(env, {})
    cluster_name = str(env_cfg.get("cluster_context", "") or "").strip()
    if not cluster_name:
        raise PocError(f"Missing cluster_context for environment '{env}' in environments.yaml")
    region = str(env_cfg.get("aws_region", "") or os.environ.get("AWS_REGION", "us-east-1")).strip()
    kubeconfig = os.environ.get("KUBECONFIG", "")
    cmd = ["aws", "eks", "update-kubeconfig", "--region", region, "--name", cluster_name]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])
    run(cmd)

def run_terraform_provision(
    *,
    automation: dict,
    github_client: GithubActionsClient,
    target: dict,
) -> dict:
    repo = str(automation.get("repo", "") or "").strip()
    workflow = str(automation.get("provision_workflow", "") or "").strip()
    ref = str(automation.get("ref", "") or "main").strip() or "main"
    timeout_seconds = int(automation.get("timeout_seconds", 3600))
    poll_seconds = int(automation.get("poll_seconds", 20))
    if not repo or not workflow:
        raise PocError("Terraform automation repo/workflow is not configured in global.yaml")
    dispatch_time = github_client.dispatch_workflow(
        repo,
        workflow,
        ref,
        {
            "environment": target.get("environment", ""),
            "component": target.get("app_key", ""),
            "action": "provision_and_deploy",
        },
    )
    run_state = github_client.wait_for_workflow_completion(repo, workflow, dispatch_time, timeout_seconds, poll_seconds)
    if run_state.get("conclusion") and run_state.get("conclusion") != "success":
        raise PocError(f"Terraform workflow failed: {run_state.get('html_url', '')}")
    return run_state

def attempt_automatic_rollback(
    *,
    policy: dict,
    test_mode: bool,
    manual_rollback_requested: bool,
    previous_state: dict,
    desired_version: str,
    target: dict,
    issue: JiraIssue,
    gitops: GitOpsRepoManager,
    git_user: str,
    git_email: str,
    argocd: ArgoCdClient,
    argocd_timeout_seconds: int,
    jira_progress_reporter: JiraProgressReporter | None,
    trigger_argocd_sync: bool,
    failure_reason: str,
    attempted_gitops_commit: str = "",
) -> dict:
    result = {
        "attempted": False,
        "performed": False,
        "success": False,
        "eligible": False,
        "trigger_reason": failure_reason,
        "attempted_version": desired_version,
        "attempted_gitops_commit": attempted_gitops_commit,
        "rollback_version": "",
        "rollback_commit": "",
        "rollback_status": {},
        "rollback_error": "",
    }
    if manual_rollback_requested or test_mode:
        result["rollback_error"] = "Automatic rollback is not available during manual rollback mode or test mode"
        return result
    if not bool((policy.get("policy", {}) or {}).get("auto_rollback_enabled", False)):
        result["rollback_error"] = "Automatic rollback is disabled by deployment_policy.yaml"
        return result
    rollback_version = str(previous_state.get("last_version", "") or "").strip()
    if not rollback_version:
        result["rollback_error"] = "No previous stable deployment state exists for automatic rollback"
        return result
    if rollback_version == desired_version:
        result["rollback_error"] = "Previous stable version matches the failed attempted version; automatic rollback would be a no-op"
        return result
    result["attempted"] = True
    result["eligible"] = True
    result["rollback_version"] = rollback_version
    if jira_progress_reporter:
        jira_progress_reporter.publish_stage("rollback_started", {
            "target": target,
            "requested_version": target.get("requested_version", ""),
            "resolved_version": rollback_version,
            "gitops_commit": attempted_gitops_commit,
            "detail": f"Deployment failed for attempted version {desired_version}. Starting automatic GitOps rollback to previous stable version {rollback_version}.",
        })
    try:
        rollback_file = gitops.update_image_tag(target["values_path"], rollback_version)
        rollback_commit = gitops.commit_and_push(
            rollback_file,
            f"rollback({target['app_key']}): jira-{issue.key} -> {rollback_version}",
            git_user,
            git_email,
            test_mode=False,
        )
        result["performed"] = True
        result["rollback_commit"] = rollback_commit
        if argocd.configured():
            argocd.sync_app(target["argocd_app"])
        rollback_status = argocd.wait_until_synced_and_healthy(
            target["argocd_app"],
            timeout_seconds=argocd_timeout_seconds,
            expected_revision=rollback_commit,
            on_wait_progress=(
                (lambda status: jira_progress_reporter.publish_stage("argocd_sync_in_progress", {
                    "target": target,
                    "requested_version": target.get("requested_version", ""),
                    "resolved_version": rollback_version,
                    "gitops_commit": rollback_commit,
                    "detail": (
                        f"ArgoCD is still reconciling the rollback revision. "
                        f"Current sync={status.get('sync', '')}, health={status.get('health', '')}, revision={status.get('revision', '')}."
                    ),
                })) if jira_progress_reporter else None
            ),
            on_final_verification=(
                (lambda status: jira_progress_reporter.publish_stage("argocd_final_verification", {
                    "target": target,
                    "requested_version": target.get("requested_version", ""),
                    "resolved_version": rollback_version,
                    "gitops_commit": rollback_commit,
                    "detail": (
                        f"Performing final ArgoCD verification for rollback revision={status.get('revision', '')}, "
                        f"sync={status.get('sync', '')}, health={status.get('health', '')}."
                    ),
                })) if jira_progress_reporter else None
            ),
        )
        result.update({"performed": True, "success": True, "rollback_commit": rollback_commit, "rollback_status": rollback_status})
        if jira_progress_reporter:
            jira_progress_reporter.publish_stage("rollback_completed", {
                "target": target,
                "requested_version": target.get("requested_version", ""),
                "resolved_version": rollback_version,
                "gitops_commit": rollback_commit,
                "detail": f"Automatic rollback completed successfully. ArgoCD reconciled the reverted version {rollback_version}.",
            })
    except Exception as rollback_exc:
        result["rollback_error"] = str(rollback_exc)
        if jira_progress_reporter:
            jira_progress_reporter.publish_stage("rollback_failed", {
                "target": target,
                "requested_version": target.get("requested_version", ""),
                "resolved_version": rollback_version,
                "gitops_commit": result.get("rollback_commit", "") or attempted_gitops_commit,
                "detail": f"Automatic rollback failed after deployment failure: {rollback_exc}",
            })
    return result


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
    jira_progress_reporter: JiraProgressReporter | None = None
    metadata: dict = {}
    target: dict = {"project_key": "", "app_key": "", "environment": "", "gitops_repo": "", "gitops_branch": "", "values_path": "", "argocd_app": "", "namespace": "", "effective_version": ""}
    prechecks: dict = {}
    postchecks: dict = {}
    argocd_status: dict | None = None
    lock_acquire_result: dict = {}
    lock_release_result: dict = {}
    state_result: dict = {}
    rollback_result: dict = {}
    deployment_action = "failed"
    gitops_commit = ""
    requested_version = ""
    desired_version = ""
    previous_state: dict = {}
    rollback_source_version = ""
    test_mode = False
    run_id = os.environ.get("GITHUB_RUN_ID", "local-run")
    workflow_name = os.environ.get("GITHUB_WORKFLOW", "Deploy From Jira")
    actor = os.environ.get("GITHUB_ACTOR", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com').rstrip('/')}/{repository}/actions/runs/{run_id}" if repository and run_id not in {"", "local-run"} else ""

    try:
        jira = JiraClient(os.environ["JIRA_BASE_URL"], os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
        issue = jira.fetch_issue(args.jira_ticket)
        jira_progress_reporter = JiraProgressReporter(jira, issue, configs["global"], run_url=run_url)
        jira_progress_reporter.publish_stage("workflow_triggered", {"detail": "Deployment workflow accepted the Jira ticket and started processing."})
        metadata = parse_ticket_description(issue.description, configs["jira_field_mapping"])
        validate_metadata(metadata, configs["global"], configs["environments"], configs["jira_field_mapping"])
        jira_progress_reporter.publish_stage("jira_validated", {"requested_version": metadata.get("version", ""), "detail": "Jira metadata parsed and validated successfully."})
        target = resolve_target(metadata, configs["projects"], configs["app_mapping"], configs["environments"], configs["global"], configs["latest_tags"])
        validate_target(target)
        validate_version_resolution(target)
        jira_progress_reporter.publish_stage("target_resolved", {"target": target, "requested_version": target.get("requested_version", ""), "resolved_version": target.get("resolved_version", ""), "detail": "Resolved the GitOps path and ArgoCD application for the request."})
        test_mode = args.test_mode or env_flag("TEST_MODE")
        if args.rollback_to_last_success and not read_yaml(root / "config" / "deployment_policy.yaml").get("policy", {}).get("manual_rollback_enabled", True):
            raise PocError("Manual rollback is disabled by deployment_policy.yaml")
        target["previous_version"] = ""
        git_user = os.environ.get("DEPLOY_GIT_USER", "deployment-poc[bot]")
        git_email = os.environ.get("DEPLOY_GIT_EMAIL", "deployment-poc@users.noreply.github.com")
        policy = configs["policy"]
        github_client = GithubActionsClient(root, repository=os.environ.get("GITHUB_REPOSITORY"), api_token=os.environ.get("GITHUB_API_TOKEN"))
        state_manager = DeploymentStateManager(root, policy, git_user, git_email, github_client, test_mode)
        argocd = ArgoCdClient(os.environ.get("ARGOCD_SERVER"), os.environ.get("ARGOCD_AUTH_TOKEN"), insecure=env_flag("ARGOCD_INSECURE"))
        previous_state = state_manager.get_last_successful_state(target)
        target["previous_version"] = previous_state.get("last_version", "")
        deployment_action = "deploy"
        desired_version = target["resolved_version"]
        requested_version = target["requested_version"]
        repository = os.environ.get("GITHUB_REPOSITORY", github_client.repository if github_client else "")

        requested_action = normalize_action(metadata.get("action", ""))
        terraform_result = {}

        if args.rollback_to_last_success:
            rollback_version = previous_state.get("last_version", "").strip()
            if not rollback_version:
                raise PocError(f"No last successful deployment state exists for {target['project_key']}/{target['app_key']} in {target['environment']}, so rollback cannot proceed")
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
        jira_progress_reporter.publish_stage("lock_acquired", {"target": target, "requested_version": requested_version, "resolved_version": desired_version, "detail": "Deployment lock acquired successfully."})

        with GitOpsRepoManager(target["gitops_repo"], target["gitops_branch"], os.environ.get("TERRAFORM_TOKEN", "")) as gitops:
            def publish_argocd_sync_in_progress(status: dict) -> None:
                if jira_progress_reporter:
                    jira_progress_reporter.publish_stage("argocd_sync_in_progress", {
                        "target": target,
                        "requested_version": requested_version,
                        "resolved_version": desired_version,
                        "gitops_commit": gitops_commit or current_revision if 'current_revision' in locals() else gitops_commit,
                        "detail": (
                            f"ArgoCD is still reconciling the requested revision. "
                            f"Current sync={status.get('sync', '')}, health={status.get('health', '')}, revision={status.get('revision', '')}."
                        ),
                    })

            def publish_argocd_final_verification(status: dict) -> None:
                if jira_progress_reporter:
                    jira_progress_reporter.publish_stage("argocd_final_verification", {
                        "target": target,
                        "requested_version": requested_version,
                        "resolved_version": desired_version,
                        "gitops_commit": gitops_commit or current_revision if 'current_revision' in locals() else gitops_commit,
                        "detail": (
                            f"Performing final ArgoCD verification for revision={status.get('revision', '')}, "
                            f"sync={status.get('sync', '')}, health={status.get('health', '')}."
                        ),
                    })
            current_tag = gitops.get_current_image_tag(target["values_path"])
            current_revision = gitops.get_current_revision()
            if requested_action == "provision_and_deploy":
                prechecks = run_prechecks(target, gitops.repo_dir, None)
                automation_cfg = configs["global"].get("terraform_automation", {}) or {}
                terraform_client = GithubActionsClient(
                    root,
                    repository=str(automation_cfg.get("repo", "") or "").strip(),
                    api_token=os.environ.get("TERRAFORM_TOKEN", "") or os.environ.get("GITHUB_API_TOKEN", ""),
                )
                terraform_result = run_terraform_provision(
                    automation=automation_cfg,
                    github_client=terraform_client,
                    target=target,
                )
                refresh_kubeconfig(target, configs["environments"])
                ensure_argocd_port_forward(root)
                prechecks = run_prechecks(target, gitops.repo_dir, argocd)
            else:
                ensure_argocd_port_forward(root)
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

            try:
                if current_tag == desired_version:
                    jira_progress_reporter.publish_stage("gitops_commit_pushed", {"target": target, "requested_version": requested_version, "resolved_version": desired_version, "gitops_commit": current_revision, "detail": "No new GitOps commit was needed; verifying the current deployed revision."})
                    if test_mode:
                        deployment_action = "reconciled"
                        gitops_commit = current_revision
                        argocd_status = {"sync": "Synced", "health": "Healthy", "revision": gitops_commit, "operation_revision": gitops_commit, "operation_phase": "Succeeded", "raw": {"simulated": True}}
                        jira_progress_reporter.publish_stage("argocd_sync_started", {"target": target, "gitops_commit": gitops_commit, "detail": "Test mode reconciliation started against the simulated ArgoCD state."})
                    elif argocd.configured():
                        jira_progress_reporter.publish_stage("argocd_sync_started", {"target": target, "gitops_commit": current_revision, "detail": "Waiting for ArgoCD to verify the current revision."})
                        if args.trigger_argocd_sync:
                            argocd.sync_app(target["argocd_app"])
                        argocd_status = argocd.wait_until_synced_and_healthy(
                            target["argocd_app"],
                            timeout_seconds=args.argocd_timeout_seconds,
                            expected_revision=current_revision,
                            on_wait_progress=publish_argocd_sync_in_progress,
                            on_final_verification=publish_argocd_final_verification,
                        )
                        gitops_commit = current_revision
                        if args.rollback_to_last_success:
                            deployment_action = "rollback_skipped"
                        elif already_successful_same_ticket or already_successful_same_version:
                            deployment_action = "already_deployed"
                        else:
                            deployment_action = "reconciled"
                    else:
                        raise PocError(f"Target {target['app_key']} in {target['environment']} is already at version {desired_version}, but ArgoCD verification is not configured")
                else:
                    updated_file = gitops.update_image_tag(target["values_path"], desired_version)
                    commit_message = f"rollback({target['app_key']}): jira-{issue.key} -> {desired_version}" if args.rollback_to_last_success else f"deploy({target['app_key']}): jira-{issue.key} -> {desired_version}"
                    gitops_commit = gitops.commit_and_push(updated_file, commit_message, git_user, git_email, test_mode=test_mode)
                    jira_progress_reporter.publish_stage("gitops_commit_pushed", {"target": target, "requested_version": requested_version, "resolved_version": desired_version, "gitops_commit": gitops_commit, "detail": "GitOps values file was updated and pushed successfully."})
                    if test_mode:
                        argocd_status = {"sync": "Synced", "health": "Healthy", "revision": gitops_commit, "operation_revision": gitops_commit, "operation_phase": "Succeeded", "raw": {"simulated": True}}
                        jira_progress_reporter.publish_stage("argocd_sync_started", {"target": target, "gitops_commit": gitops_commit, "detail": "Test mode reconciliation started against the simulated ArgoCD state."})
                    elif argocd.configured():
                        jira_progress_reporter.publish_stage("argocd_sync_started", {"target": target, "gitops_commit": gitops_commit, "detail": "GitOps commit pushed. Waiting for ArgoCD to reconcile it."})
                        if args.trigger_argocd_sync:
                            argocd.sync_app(target["argocd_app"])
                        argocd_status = argocd.wait_until_synced_and_healthy(
                            target["argocd_app"],
                            timeout_seconds=args.argocd_timeout_seconds,
                            expected_revision=gitops_commit,
                            on_wait_progress=publish_argocd_sync_in_progress,
                            on_final_verification=publish_argocd_final_verification,
                        )
                    deployment_action = "rollback_test_mode" if args.rollback_to_last_success and test_mode else "rolled_back" if args.rollback_to_last_success else "test_mode" if test_mode else "deployed"

                jira_progress_reporter.publish_stage("argocd_synced_healthy", {"target": target, "gitops_commit": gitops_commit, "detail": "ArgoCD reported the expected revision as Synced and Healthy."})
                postchecks = run_postchecks(target, argocd_status)
                ensure_postchecks_success(postchecks)
                jira_progress_reporter.publish_stage("post_checks_completed", {"target": target, "gitops_commit": gitops_commit, "detail": "Post-deployment checks completed."})
            except PocError as deployment_exc:
                rollback_result = attempt_automatic_rollback(
                    policy=policy,
                    test_mode=test_mode,
                    manual_rollback_requested=args.rollback_to_last_success,
                    previous_state=previous_state,
                    desired_version=desired_version,
                    target=target,
                    issue=issue,
                    gitops=gitops,
                    git_user=git_user,
                    git_email=git_email,
                    argocd=argocd,
                    argocd_timeout_seconds=args.argocd_timeout_seconds,
                    jira_progress_reporter=jira_progress_reporter,
                    trigger_argocd_sync=args.trigger_argocd_sync,
                    failure_reason=str(deployment_exc),
                    attempted_gitops_commit=gitops_commit,
                )
                if rollback_result.get("performed") and rollback_result.get("success"):
                    deployment_action = "auto_rolled_back"
                    target["effective_version"] = rollback_result.get("rollback_version", "")
                    target["rollback_source_version"] = desired_version
                    state_result = state_manager.mark_success(
                        target,
                        issue.key,
                        rollback_result.get("rollback_commit", ""),
                        rollback_result.get("rollback_status", {}) or {},
                        target["values_path"],
                        deployed_version=rollback_result.get("rollback_version", ""),
                        requested_version=requested_version,
                        action=deployment_action,
                        rollback_source_version=desired_version,
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
                        "outcome": "failure",
                        "error": str(deployment_exc),
                        "prechecks_json": json.dumps(prechecks, indent=2),
                        "argocd_status_json": json.dumps(rollback_result.get("rollback_status", {}) or {}, indent=2),
                        "lock_json": json.dumps({"acquire": lock_acquire_result, "release": lock_release_result}, indent=2),
                        "state_json": json.dumps(state_result, indent=2),
                        "rollback_json": json.dumps(rollback_result, indent=2),
                        "postchecks_json": json.dumps(postchecks, indent=2),
                        "jira_progress_json": "{}",
                    }
                    jira_progress_reporter.publish_stage("failed", {
                        "target": target,
                        "requested_version": requested_version,
                        "resolved_version": desired_version,
                        "gitops_commit": gitops_commit,
                        "detail": f"Deployment failed for version {desired_version}, but automatic rollback restored stable version {rollback_result.get('rollback_version', '')}.",
                    })
                    result["jira_progress_json"] = json.dumps(jira_progress_reporter.summary(), indent=2)
                    jira_feedback_result = apply_final_jira_feedback(jira, issue, result, configs["global"])
                    result["jira_feedback_json"] = json.dumps(jira_feedback_result, indent=2)
                    write_reports(root, result)
                    print(json.dumps(result, indent=2))
                    return 1
                if rollback_result.get("attempted") and rollback_result.get("rollback_error"):
                    raise PocError(f"{deployment_exc}; automatic rollback failed: {rollback_result.get('rollback_error', '')}") from deployment_exc
                raise

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
            "lock_json": json.dumps({"acquire": lock_acquire_result, "release": lock_release_result}, indent=2),
            "state_json": json.dumps(state_result, indent=2),
            "rollback_json": json.dumps(rollback_result, indent=2),
            "postchecks_json": json.dumps(postchecks, indent=2),
            "jira_progress_json": "{}",
        }
        jira_progress_reporter.publish_stage("completed", {
            "target": target,
            "requested_version": requested_version,
            "resolved_version": desired_version,
            "gitops_commit": gitops_commit,
            "detail": f"Deployment flow completed with action '{deployment_action}'.",
        })
        result["jira_progress_json"] = json.dumps(jira_progress_reporter.summary(), indent=2)
        jira_feedback_result = apply_final_jira_feedback(jira, issue, result, configs["global"])
        result["jira_feedback_json"] = json.dumps(jira_feedback_result, indent=2)
        write_reports(root, result)
        print(json.dumps(result, indent=2))
        return 0
    except PocError as exc:
        failure_lock = {}
        failure_state = locals().get("state_result", {}) or {}
        failure_rollback = locals().get("rollback_result", {}) or {}
        try:
            if "state_manager" in locals() and issue and target.get("app_key"):
                failure_lock = state_manager.release_lock(target, issue.key, "released", f"failure: {exc}")
        except Exception:
            failure_lock = {"release_error": "failed to release lock after error"}
        result = {
            "jira_ticket": args.jira_ticket,
            "issue_summary": issue.summary if issue else "",
            "metadata": metadata,
            "target": target,
            "deployment_action": "rollback_failed" if failure_rollback.get("attempted") else "failed",
            "outcome": "failure",
            "error": str(exc),
            "gitops_commit": gitops_commit,
            "changed_file": target.get("values_path", ""),
            "workflow_run_id": run_id,
            "workflow_run_url": run_url,
            "runner_name": os.environ.get("RUNNER_NAME", ""),
            "prechecks_json": json.dumps(prechecks, indent=2),
            "argocd_status_json": json.dumps(argocd_status or {}, indent=2),
            "lock_json": json.dumps({"acquire": lock_acquire_result, "release": failure_lock}, indent=2),
            "state_json": json.dumps(failure_state, indent=2),
            "rollback_json": json.dumps(failure_rollback, indent=2),
            "postchecks_json": json.dumps(postchecks, indent=2),
            "jira_progress_json": "{}",
            "jira_feedback_json": "{}",
        }
        try:
            if jira_progress_reporter:
                jira_progress_reporter.publish_stage("failed", {
                    "target": target,
                    "requested_version": requested_version,
                    "resolved_version": desired_version,
                    "gitops_commit": gitops_commit,
                    "detail": str(exc),
                })
                result["jira_progress_json"] = json.dumps(jira_progress_reporter.summary(), indent=2)
            jira_feedback_result = apply_final_jira_feedback(jira, issue, result, configs["global"])
            result["jira_feedback_json"] = json.dumps(jira_feedback_result, indent=2)
        except Exception as jira_feedback_exc:
            if jira_progress_reporter:
                result["jira_progress_json"] = json.dumps(jira_progress_reporter.summary(), indent=2)
            result["jira_feedback_json"] = json.dumps({
                "enabled": bool(configs.get("global", {}).get("jira_feedback", {}).get("enabled", False)),
                "jira_comment_added": False,
                "jira_transition_attempted": False,
                "jira_transition_result": "failure",
                "jira_transition_name_used": "",
                "jira_feedback_error": str(jira_feedback_exc),
                "comment_attempted": False,
                "comment_result": "failure",
            }, indent=2)
        write_reports(root, result)
        print(json.dumps(result, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())






