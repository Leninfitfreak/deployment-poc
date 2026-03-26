from __future__ import annotations

from pathlib import Path

from .utils import write_json


def write_reports(root: Path, result: dict) -> None:
    artifacts_dir = root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    write_json(artifacts_dir / "deployment-result.json", result)

    markdown = [
        "# Deployment Result",
        "",
        f"- Jira ticket: `{result.get('jira_ticket', '')}`",
        f"- Outcome: `{result.get('outcome', '')}`",
        f"- Deployment action: `{result.get('deployment_action', '')}`",
        f"- GitOps commit: `{result.get('gitops_commit', '')}`",
        f"- Changed file: `{result.get('changed_file', '')}`",
        f"- Runner: `{result.get('runner_name', '')}`",
    ]

    target = result.get("target", {})
    if target:
        markdown.extend(
            [
                f"- Project: `{target.get('project_key', '')}`",
                f"- App: `{target.get('app_key', '')}`",
                f"- Environment: `{target.get('environment', '')}`",
                f"- Previous version: `{target.get('previous_version', '')}`",
                f"- Requested version: `{target.get('requested_version', '')}`",
                f"- Resolved version: `{target.get('resolved_version', '')}`",
                f"- GitOps repo: `{target.get('gitops_repo', '')}`",
                f"- GitOps branch: `{target.get('gitops_branch', '')}`",
                f"- Values path: `{target.get('values_path', '')}`",
                f"- ArgoCD app: `{target.get('argocd_app', '')}`",
                f"- Namespace: `{target.get('namespace', '')}`",
            ]
        )

    if result.get("error"):
        markdown.extend(["", "## Error", "", f"`{result['error']}`"])

    markdown.extend(
        [
            "",
            "## Pre-checks",
            "",
            f"```json\n{result.get('prechecks_json', '{}')}\n```",
            "",
            "## Lock Result",
            "",
            f"```json\n{result.get('lock_json', '{}')}\n```",
            "",
            "## State Result",
            "",
            f"```json\n{result.get('state_json', '{}')}\n```",
            "",
            "## Post-checks",
            "",
            f"```json\n{result.get('postchecks_json', '{}')}\n```",
            "",
        ]
    )
    (artifacts_dir / "deployment-result.md").write_text("\n".join(markdown), encoding="utf-8")
