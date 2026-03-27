from __future__ import annotations

from dataclasses import dataclass

import requests

from .utils import PocError


@dataclass
class JiraIssue:
    key: str
    summary: str
    description: str
    status_name: str
    status_id: str
    raw: dict


@dataclass
class JiraTransition:
    id: str
    name: str
    to_status_name: str
    to_status_id: str
    raw: dict


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str) -> None:
        if not base_url or not email or not api_token:
            raise PocError("Jira client requires JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})

    def fetch_issue(self, issue_key: str) -> JiraIssue:
        response = self.session.get(f"{self.base_url}/rest/api/3/issue/{issue_key}", timeout=30)
        if response.status_code == 404:
            raise PocError(f"Jira ticket not found: {issue_key}")
        if response.status_code == 401:
            raise PocError("Jira authentication failed")
        response.raise_for_status()
        payload = response.json()
        fields = payload.get("fields", {})
        description = self._description_to_text(fields.get("description"))
        status = fields.get("status") or {}
        return JiraIssue(
            key=payload["key"],
            summary=fields.get("summary") or "",
            description=description,
            status_name=(status.get("name") or "").strip(),
            status_id=str(status.get("id") or "").strip(),
            raw=payload,
        )

    def create_issue(self, project_key: str, summary: str, description: str, issue_type: str = "Task") -> JiraIssue:
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": issue_type},
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": line}],
                        }
                        for line in description.splitlines()
                        if line.strip()
                    ],
                },
            }
        }
        response = self.session.post(f"{self.base_url}/rest/api/3/issue", json=payload, timeout=30)
        if response.status_code == 401:
            raise PocError("Jira authentication failed while creating issue")
        response.raise_for_status()
        created = response.json()
        return self.fetch_issue(created["key"])

    def get_transitions(self, issue_key: str) -> list[JiraTransition]:
        response = self.session.get(f"{self.base_url}/rest/api/3/issue/{issue_key}/transitions", timeout=30)
        if response.status_code == 404:
            raise PocError(f"Jira ticket not found while loading transitions: {issue_key}")
        if response.status_code == 401:
            raise PocError("Jira authentication failed while loading transitions")
        response.raise_for_status()
        payload = response.json()
        transitions: list[JiraTransition] = []
        for item in payload.get("transitions", []):
            target_status = item.get("to") or {}
            transitions.append(
                JiraTransition(
                    id=str(item.get("id") or "").strip(),
                    name=(item.get("name") or "").strip(),
                    to_status_name=(target_status.get("name") or "").strip(),
                    to_status_id=str(target_status.get("id") or "").strip(),
                    raw=item,
                )
            )
        return transitions

    def resolve_transition(self, issue_key: str, candidate_names: list[str]) -> tuple[JiraIssue, JiraTransition | None, list[JiraTransition]]:
        issue = self.fetch_issue(issue_key)
        transitions = self.get_transitions(issue_key)
        if not candidate_names:
            return issue, None, transitions

        normalized_candidates = [name.strip().casefold() for name in candidate_names if str(name).strip()]
        current_status = issue.status_name.strip().casefold()
        if current_status and current_status in normalized_candidates:
            return issue, None, transitions

        by_name: dict[str, JiraTransition] = {}
        for transition in transitions:
            for lookup_key in {
                transition.name.strip().casefold(),
                transition.to_status_name.strip().casefold(),
            }:
                if lookup_key:
                    by_name.setdefault(lookup_key, transition)

        for candidate in normalized_candidates:
            resolved = by_name.get(candidate)
            if resolved:
                return issue, resolved, transitions
        return issue, None, transitions

    def transition_issue(self, issue_key: str, transition_id: str) -> None:
        if not transition_id:
            raise PocError("Jira transition id is required")
        response = self.session.post(
            f"{self.base_url}/rest/api/3/issue/{issue_key}/transitions",
            json={"transition": {"id": transition_id}},
            timeout=30,
        )
        if response.status_code == 404:
            raise PocError(f"Jira ticket not found while transitioning: {issue_key}")
        if response.status_code == 401:
            raise PocError("Jira authentication failed while transitioning issue")
        response.raise_for_status()

    def add_comment(self, issue_key: str, comment_text: str) -> None:
        text = (comment_text or "").strip()
        if not text:
            raise PocError("Jira comment text is empty")
        paragraphs = []
        for line in text.splitlines():
            if not line.strip():
                continue
            paragraphs.append({"type": "paragraph", "content": [{"type": "text", "text": line}]})
        response = self.session.post(
            f"{self.base_url}/rest/api/3/issue/{issue_key}/comment",
            json={"body": {"type": "doc", "version": 1, "content": paragraphs}},
            timeout=30,
        )
        if response.status_code == 404:
            raise PocError(f"Jira ticket not found while adding comment: {issue_key}")
        if response.status_code == 401:
            raise PocError("Jira authentication failed while adding comment")
        response.raise_for_status()

    def _description_to_text(self, node: dict | None) -> str:
        if not node:
            return ""
        chunks: list[str] = []

        def walk(value: dict | list | str | None) -> None:
            if isinstance(value, str):
                chunks.append(value)
                return
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if isinstance(value, dict):
                text = value.get("text")
                if text:
                    chunks.append(text)
                for item in value.get("content", []):
                    walk(item)

        walk(node)
        return "\n".join(line.strip() for line in chunks if str(line).strip())
