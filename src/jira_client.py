from __future__ import annotations

from dataclasses import dataclass

import requests

from .utils import PocError


@dataclass
class JiraIssue:
    key: str
    summary: str
    description: str
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
        return JiraIssue(
            key=payload["key"],
            summary=fields.get("summary") or "",
            description=description,
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
