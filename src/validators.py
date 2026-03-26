from __future__ import annotations

from urllib.parse import urlparse

from .utils import PocError


def validate_metadata(metadata: dict[str, str], global_config: dict, env_config: dict, field_mapping: dict) -> None:
    for field_name, config in field_mapping["description_fields"].items():
        if field_name == "url":
            continue
        if config.get("required") and not metadata.get(field_name):
            raise PocError(f"Missing required Jira deployment metadata: {field_name}")

    env = metadata.get("env", "").strip()
    if not env:
        raise PocError("Deployment environment is required")
    if env not in env_config["environments"]:
        raise PocError(f"Unsupported environment: {env}")
    allowed_envs = global_config.get("allowed_environments", [])
    if allowed_envs and env not in allowed_envs:
        raise PocError(f"Environment '{env}' is not enabled for this deployment-poc instance")

    version = metadata.get("version", "").strip()
    if not version:
        raise PocError("Deployment version is required")

    if metadata.get("url"):
        parsed = urlparse(metadata["url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PocError(f"Invalid deployment URL: {metadata['url']}")


def validate_target(target: dict) -> None:
    required = [
        "project_key",
        "app_key",
        "resolved_version",
        "gitops_repo",
        "gitops_branch",
        "values_path",
        "argocd_app",
        "namespace",
    ]
    for key in required:
        if not target.get(key):
            raise PocError(f"Resolved target missing required field: {key}")


def validate_version_resolution(target: dict) -> None:
    requested = target.get("requested_version", "")
    resolved = target.get("resolved_version", "")
    if not requested:
        raise PocError("Requested version is empty after Jira parsing")
    if not resolved:
        raise PocError("Resolved version is empty after target resolution")
