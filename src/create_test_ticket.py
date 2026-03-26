from __future__ import annotations

import argparse
import json
import os

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
    print(json.dumps({"key": issue.key, "summary": issue.summary, "description": issue.description}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
