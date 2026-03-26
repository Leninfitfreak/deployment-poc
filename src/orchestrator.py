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
from .validators import validate_metadata, validate_target


def load_configs(root: Path) -> dict:
    config_dir = root / "config"
    return {
        "projects": read_yaml(config_dir / "projects.yaml"),
        "app_mapping": read_yaml(config_dir / "app_mapping.yaml"),
        "environments": read_yaml(config_dir / "environments.yaml"),
        "jira_field_mapping": read_yaml(config_dir / "jira_field_mapping.yaml"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Jira-driven GitOps deployment POC")
    parser.add_argument("--jira-ticket", required=True)
    parser.add_argument("--trigger-argocd-sync", action="store_true")
    parser.add_argument("--argocd-timeout-seconds", type=int, default=600)
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
        validate_metadata(metadata, configs["environments"], configs["jira_field_mapping"])
        target = resolve_target(metadata, configs["projects"], configs["app_mapping"], configs["environments"])
        validate_target(target)

        argocd = ArgoCdClient(
            os.environ.get("ARGOCD_SERVER"),
            os.environ.get("ARGOCD_AUTH_TOKEN"),
        )

        with GitOpsRepoManager(
            target["gitops_repo"],
            target["gitops_branch"],
            os.environ.get("INFRA_PAT", ""),
        ) as gitops:
            updated_file = gitops.update_image_tag(target["values_path"], metadata["version"])
            prechecks = run_prechecks(target, gitops.repo_dir, argocd)
            gitops.commit_and_push(
                updated_file,
                f"deploy({target['app_key']}): jira-{issue.key} -> {metadata['version']}",
                os.environ.get("DEPLOY_GIT_USER", "deployment-poc[bot]"),
                os.environ.get("DEPLOY_GIT_EMAIL", "deployment-poc@users.noreply.github.com"),
            )

        argocd_status = None
        if argocd.configured():
            if args.trigger_argocd_sync:
                argocd.sync_app(target["argocd_app"])
            argocd_status = argocd.wait_until_synced_and_healthy(
                target["argocd_app"],
                timeout_seconds=args.argocd_timeout_seconds,
            )

        postchecks = run_postchecks(target, argocd_status)
        result = {
            "jira_ticket": issue.key,
            "issue_summary": issue.summary,
            "metadata": metadata,
            "target": target,
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

