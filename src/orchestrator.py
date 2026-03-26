from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .argocd_client import ArgoCdClient
from .gitops_repo import GitOpsRepoManager
from .jira_client import JiraClient
from .postchecks import run_postchecks
from .prechecks import run_prechecks
from .reporting import write_reports
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
    args = parser.parse_args()

    root = repo_root()
    configs = load_configs(root)

    try:
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

        argocd = ArgoCdClient(
            os.environ.get("ARGOCD_SERVER"),
            os.environ.get("ARGOCD_AUTH_TOKEN"),
            insecure=env_flag("ARGOCD_INSECURE"),
        )

        with GitOpsRepoManager(
            target["gitops_repo"],
            target["gitops_branch"],
            os.environ.get("INFRA_PAT", ""),
        ) as gitops:
            current_tag = gitops.get_current_image_tag(target["values_path"])
            if not env_flag("ALLOW_DUPLICATE_DEPLOYMENTS") and current_tag == target["resolved_version"]:
                raise PocError(
                    f"Duplicate deployment prevented: {target['app_key']} in {target['environment']} "
                    f"is already at version {target['resolved_version']}"
                )
            updated_file = gitops.update_image_tag(target["values_path"], target["resolved_version"])
            prechecks = run_prechecks(target, gitops.repo_dir, argocd)
            gitops_commit = gitops.commit_and_push(
                updated_file,
                f"deploy({target['app_key']}): jira-{issue.key} -> {target['resolved_version']}",
                os.environ.get("DEPLOY_GIT_USER", "deployment-poc[bot]"),
                os.environ.get("DEPLOY_GIT_EMAIL", "deployment-poc@users.noreply.github.com"),
                test_mode=test_mode,
            )

        argocd_status = None
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

        postchecks = run_postchecks(target, argocd_status)
        result = {
            "jira_ticket": issue.key,
            "issue_summary": issue.summary,
            "metadata": metadata,
            "target": target,
            "gitops_commit": gitops_commit,
            "changed_file": target["values_path"],
            "runner_name": os.environ.get("RUNNER_NAME", ""),
            "test_mode": test_mode,
            "outcome": "success",
            "prechecks_json": json.dumps(prechecks, indent=2),
            "postchecks_json": json.dumps(postchecks, indent=2),
        }
        write_reports(root, result)
        print(json.dumps(result, indent=2))
        return 0
    except PocError as exc:
        result = {
            "jira_ticket": args.jira_ticket,
            "outcome": "failure",
            "error": str(exc),
            "prechecks_json": "{}",
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
            },
        }
        write_reports(root, result)
        print(json.dumps(result, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
