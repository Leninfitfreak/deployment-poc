from __future__ import annotations

import json
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
        f"- Workflow run id: `{result.get('workflow_run_id', '')}`",
        f"- Workflow run url: `{result.get('workflow_run_url', '')}`",
    ]

    try:
        lock_payload = json.loads(result.get("lock_json", "{}") or "{}")
    except Exception:
        lock_payload = {}
    if lock_payload:
        acquire_payload = lock_payload.get("acquire", {}) or {}
        release_payload = lock_payload.get("release", {}) or {}
        previous = acquire_payload.get("previous_lock_evaluation", {}) or {}
        stale_recovery = acquire_payload.get("stale_recovery", {}) or {}
        if previous:
            markdown.append(f"- Previous lock classification: `{previous.get('classification', '')}`")
        if stale_recovery:
            markdown.append(f"- Stale lock recovery commit: `{stale_recovery.get('commit', '')}`")
        if release_payload:
            markdown.append(f"- Final lock status: `{release_payload.get('entry', {}).get('status', '')}`")

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
                f"- Effective version: `{target.get('effective_version', '')}`",
                f"- Version source: `{target.get('version_source', '')}`",
                f"- Version reference: `{target.get('version_reference', '')}`",
                f"- GitOps repo: `{target.get('gitops_repo', '')}`",
                f"- GitOps branch: `{target.get('gitops_branch', '')}`",
                f"- Values path: `{target.get('values_path', '')}`",
                f"- ArgoCD app: `{target.get('argocd_app', '')}`",
                f"- Namespace: `{target.get('namespace', '')}`",
            ]
        )
        if target.get("image_repository"):
            markdown.append(f"- Image repository: `{target.get('image_repository', '')}`")
        if target.get("latest_tag_updated_at"):
            markdown.append(f"- Latest tag metadata updated at: `{target.get('latest_tag_updated_at', '')}`")
        if target.get("rollback_source_version"):
            markdown.append(f"- Rollback source version: `{target.get('rollback_source_version', '')}`")

    try:
        jira_feedback = json.loads(result.get("jira_feedback_json", "{}") or "{}")
    except Exception:
        jira_feedback = {}
    try:
        jira_progress = json.loads(result.get("jira_progress_json", "{}") or "{}")
    except Exception:
        jira_progress = {}
    if jira_feedback:
        markdown.extend(
            [
                f"- Jira feedback mode: `{jira_feedback.get('mode', '')}`",
                f"- Jira transition result: `{jira_feedback.get('jira_transition_result', '')}`",
                f"- Jira transition used: `{jira_feedback.get('jira_transition_name_used', '')}`",
                f"- Jira comment added: `{jira_feedback.get('jira_comment_added', False)}`",
                f"- Jira final status: `{jira_feedback.get('final_status', '')}`",
                f"- Jira feedback policy satisfied: `{jira_feedback.get('policy_satisfied', '')}`",
            ]
        )
        if jira_feedback.get("jira_feedback_error"):
            markdown.append(f"- Jira feedback warning: `{jira_feedback.get('jira_feedback_error', '')}`")
    if jira_progress:
        posted = jira_progress.get("posted_stages", []) or []
        markdown.append(f"- Jira progress comments attempted: `{len(posted)}`")
        errors = jira_progress.get("errors", []) or []
        if errors:
            markdown.append(f"- Jira progress warning count: `{len(errors)}`")

    if result.get("error"):
        markdown.extend(["", "## Error", "", f"`{result['error']}`"])

    markdown.extend(
        [
            "",
            "## Pre-checks",
            "",
            f"```json\n{result.get('prechecks_json', '{}')}\n```",
            "",
            "## ArgoCD Status",
            "",
            f"```json\n{result.get('argocd_status_json', '{}')}\n```",
            "",
            "## Lock Result",
            "",
            f"```json\n{result.get('lock_json', '{}')}\n```",
            "",
            "## State Result",
            "",
            f"```json\n{result.get('state_json', '{}')}\n```",
            "",
            "## Rollback Result",
            "",
            f"```json\n{result.get('rollback_json', '{}')}\n```",
            "",
            "## Post-checks",
            "",
            f"```json\n{result.get('postchecks_json', '{}')}\n```",
            "",
            "## Jira Progress",
            "",
            f"```json\n{result.get('jira_progress_json', '{}')}\n```",
            "",
            "## Jira Feedback",
            "",
            f"```json\n{result.get('jira_feedback_json', '{}')}\n```",
            "",
        ]
    )
    (artifacts_dir / "deployment-result.md").write_text("\n".join(markdown), encoding="utf-8")
