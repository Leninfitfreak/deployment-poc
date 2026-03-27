from __future__ import annotations

import argparse
import json
import os

from .github_client import GithubActionsClient
from .orchestrator import load_configs
from .state_manager import DeploymentStateManager
from .target_resolver import resolve_target
from .utils import PocError, repo_root, write_json


def build_target(configs: dict, component: str, environment: str) -> dict:
    return resolve_target(
        {
            "app": configs["global"]["active_project_key"],
            "component": component,
            "env": environment,
            "version": "lock-inspection",
        },
        configs["projects"],
        configs["app_mapping"],
        configs["environments"],
    )


def write_unlock_artifacts(root, result: dict) -> None:
    artifacts_dir = root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    write_json(artifacts_dir / "unlock-result.json", result)
    markdown = [
        "# Deployment Lock Recovery Result",
        "",
        f"- App: `{result.get('target', {}).get('app_key', '')}`",
        f"- Environment: `{result.get('target', {}).get('environment', '')}`",
        f"- Outcome: `{result.get('outcome', '')}`",
        f"- Confirm unlock: `{result.get('confirm_unlock', False)}`",
        f"- Reason: `{result.get('reason', '')}`",
        "",
        "## Lock Inspection",
        "",
        f"```json\n{result.get('lock_inspection_json', '{}')}\n```",
        "",
        "## Unlock Result",
        "",
        f"```json\n{result.get('unlock_json', '{}')}\n```",
        "",
    ]
    if result.get("error"):
        markdown.extend(["## Error", "", f"`{result['error']}`", ""])
    (artifacts_dir / "unlock-result.md").write_text("\n".join(markdown), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or force-release a stale deployment lock")
    parser.add_argument("--component", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--confirm-unlock", action="store_true")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    root = repo_root()
    configs = load_configs(root)
    policy = configs.get("policy") or {}
    try:
        target = build_target(configs, args.component, args.env)
        github_client = GithubActionsClient(
            root,
            repository=os.environ.get("GITHUB_REPOSITORY"),
            api_token=os.environ.get("GITHUB_API_TOKEN"),
        )
        state_manager = DeploymentStateManager(
            root,
            policy,
            os.environ.get("DEPLOY_GIT_USER", "deployment-poc[bot]"),
            os.environ.get("DEPLOY_GIT_EMAIL", "deployment-poc@users.noreply.github.com"),
            github_client,
            False,
        )
        inspection = state_manager.inspect_lock(target)
        unlock_result: dict = {}

        if args.confirm_unlock:
            if not policy.get("policy", {}).get("allow_force_unlock", True):
                raise PocError("Manual force unlock is disabled by deployment_policy.yaml")
            if not inspection["present"]:
                raise PocError(f"No lock exists for {target['app_key']} in {target['environment']}")
            if inspection["run_state"].get("active"):
                raise PocError(
                    f"Refusing to unlock {target['app_key']} in {target['environment']} because workflow run "
                    f"{inspection['lock'].get('run_id')} is still active"
                )
            unlock_result = state_manager.force_release_lock(
                target,
                jira_ticket=str(inspection["lock"].get("ticket") or "manual-unlock"),
                status="force_released",
                note=args.reason or "manual unlock via workflow",
                reason=inspection["reason"],
                actor=os.environ.get("GITHUB_ACTOR", ""),
                runner_name=os.environ.get("RUNNER_NAME", ""),
                repository=os.environ.get("GITHUB_REPOSITORY", github_client.repository),
            )

        result = {
            "outcome": "success",
            "confirm_unlock": args.confirm_unlock,
            "reason": args.reason,
            "target": {
                "app_key": target["app_key"],
                "environment": target["environment"],
            },
            "lock_inspection_json": json.dumps(inspection, indent=2),
            "unlock_json": json.dumps(unlock_result, indent=2),
        }
        write_unlock_artifacts(root, result)
        print(json.dumps(result, indent=2))
        return 0
    except PocError as exc:
        result = {
            "outcome": "failure",
            "confirm_unlock": args.confirm_unlock,
            "reason": args.reason,
            "target": {
                "app_key": args.component,
                "environment": args.env,
            },
            "lock_inspection_json": "{}",
            "unlock_json": "{}",
            "error": str(exc),
        }
        write_unlock_artifacts(root, result)
        print(json.dumps(result, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
