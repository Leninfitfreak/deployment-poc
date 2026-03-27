from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .jira_client import JiraClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Jira test ticket for deployment-poc validation")
    parser.add_argument("--project-key", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--description")
    args = parser.parse_args()
    description = args.description or os.environ.get("JIRA_TICKET_DESCRIPTION", "")
    description = description.replace("\\n", "\n")
    if not description.strip():
        raise SystemExit("Ticket description is required")

    jira = JiraClient(
        os.environ["JIRA_BASE_URL"],
        os.environ["JIRA_EMAIL"],
        os.environ["JIRA_API_TOKEN"],
    )
    issue = jira.create_issue(args.project_key, args.summary, description)
    result = {"key": issue.key, "summary": issue.summary, "description": issue.description}
    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "jira-ticket.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (artifacts_dir / "jira-ticket.md").write_text(
        "\n".join(
            [
                "# Jira Test Ticket",
                "",
                f"- Key: `{issue.key}`",
                f"- Summary: `{issue.summary}`",
                "",
                "## Description",
                "",
                "```text",
                issue.description,
                "```",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
