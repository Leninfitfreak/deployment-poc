from __future__ import annotations

from urllib.parse import urlparse

from .utils import PocError


def validate_metadata(metadata: dict[str, str], env_config: dict, field_mapping: dict) -> None:
    for field_name, config in field_mapping["description_fields"].items():
        if config.get("required") and not metadata.get(field_name):
            raise PocError(f"Missing required Jira deployment metadata: {field_name}")

    env = metadata["env"]
    if env not in env_config["environments"]:
        raise PocError(f"Unsupported environment: {env}")

    parsed = urlparse(metadata["url"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PocError(f"Invalid deployment URL: {metadata['url']}")


def validate_target(target: dict) -> None:
    required = [
        "project_key",
        "app_key",
        "gitops_repo",
        "gitops_branch",
        "values_path",
        "argocd_app",
        "namespace",
    ]
    for key in required:
        if not target.get(key):
            raise PocError(f"Resolved target missing required field: {key}")
