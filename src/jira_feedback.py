from __future__ import annotations

import json
from datetime import datetime, timezone

from .jira_client import JiraClient, JiraIssue


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


def build_final_jira_comment(result: dict) -> str:
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
        f"Version source: {target.get('version_source', '')}",
        f"Deployment action: {result.get('deployment_action', '')}",
    ]
    if target.get("image_repository"):
        lines.append(f"Image repository: {target.get('image_repository', '')}")
    if target.get("latest_tag_updated_at"):
        lines.append(f"Latest tag metadata updated at: {target.get('latest_tag_updated_at', '')}")
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


class JiraProgressReporter:
    def __init__(self, jira: JiraClient | None, issue: JiraIssue | None, global_config: dict, run_url: str = "") -> None:
        self.jira = jira
        self.issue = issue
        self.config = (global_config or {}).get("jira_feedback", {}) or {}
        progress_config = self.config.get("progress_comments", {}) or {}
        self.enabled = bool(self.config.get("enabled", False) and progress_config.get("enabled", False))
        self.allowed_stages = set(progress_config.get("stages", []) or [])
        self.run_url = run_url
        self.posted_stages: list[dict] = []
        self.errors: list[str] = []

    def publish_stage(self, stage: str, context: dict | None = None) -> dict:
        context = context or {}
        entry = {
            "stage": stage,
            "attempted": False,
            "posted": False,
            "skipped": False,
            "error": "",
        }
        if not self.enabled or not self.jira or not self.issue:
            entry["skipped"] = True
            self.posted_stages.append(entry)
            return entry
        if self.allowed_stages and stage not in self.allowed_stages:
            entry["skipped"] = True
            self.posted_stages.append(entry)
            return entry
        entry["attempted"] = True
        try:
            self.jira.add_comment(self.issue.key, self._build_stage_comment(stage, context))
            entry["posted"] = True
        except Exception as exc:
            entry["error"] = str(exc)
            self.errors.append(f"{stage}: {exc}")
        self.posted_stages.append(entry)
        return entry

    def summary(self) -> dict:
        return {
            "enabled": self.enabled,
            "posted_stages": self.posted_stages,
            "errors": self.errors,
        }

    def _build_stage_comment(self, stage: str, context: dict) -> str:
        target = context.get("target", {}) or {}
        lines = [
            f"Deployment progress: {stage}",
            f"Jira ticket: {self.issue.key}",
        ]
        if target.get("app_key"):
            lines.append(f"Component: {target.get('app_key', '')}")
        if target.get("environment"):
            lines.append(f"Environment: {target.get('environment', '')}")
        if context.get("requested_version"):
            lines.append(f"Requested version: {context.get('requested_version')}")
        if context.get("resolved_version"):
            lines.append(f"Resolved version: {context.get('resolved_version')}")
        if target.get("version_source"):
            lines.append(f"Version source: {target.get('version_source', '')}")
        if target.get("argocd_app"):
            lines.append(f"ArgoCD application: {target.get('argocd_app', '')}")
        if context.get("gitops_commit"):
            lines.append(f"GitOps commit SHA: {context.get('gitops_commit')}")
        if context.get("detail"):
            lines.append(f"Detail: {context.get('detail')}")
        if self.run_url:
            lines.append(f"Workflow run URL: {self.run_url}")
        lines.append(f"Timestamp: {utc_now_iso()}")
        return "\n".join(line for line in lines if str(line).strip())


def apply_final_jira_feedback(jira: JiraClient | None, issue: JiraIssue | None, result: dict, global_config: dict) -> dict:
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
            jira.add_comment(issue.key, build_final_jira_comment(result))
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
