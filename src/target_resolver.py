from __future__ import annotations

from .utils import PocError


def resolve_target(metadata: dict[str, str], projects: dict, app_mapping: dict, environments: dict) -> dict:
    requested = metadata["app"].strip().lower()
    component = metadata.get("component", "").strip().lower()
    env = metadata["env"]

    app_key = _resolve_app_key(requested, component, projects, app_mapping, env)
    app_cfg = app_mapping["apps"][app_key]
    project_key = app_cfg["project"]
    project_cfg = projects["projects"][project_key]
    requested_version = metadata["version"]
    resolved_version = _resolve_version(requested_version, app_cfg, env)

    return {
        "project_key": project_key,
        "app_key": app_key,
        "environment": env,
        "requested_version": requested_version,
        "resolved_version": resolved_version,
        "version": resolved_version,
        "url": metadata.get("url") or app_cfg["ingress_url_by_env"][env],
        "gitops_repo": project_cfg["gitops_repo"],
        "gitops_branch": project_cfg["branch_by_env"][env],
        "values_path": app_cfg["values_path_by_env"][env],
        "argocd_app": app_cfg["argocd_app_by_env"][env],
        "namespace": app_cfg["namespace_by_env"][env],
        "cluster_context": environments["environments"][env]["cluster_context"],
        "requires_argocd_verification": environments["environments"][env].get("requires_argocd_verification", False),
    }


def _resolve_app_key(requested: str, component: str, projects: dict, app_mapping: dict, env: str) -> str:
    for app_key, app_cfg in app_mapping["apps"].items():
        aliases = {app_key, *app_cfg.get("aliases", [])}
        if requested in aliases:
            return app_key
        if component and component in aliases:
            return app_key

    project_cfg = projects["projects"].get(requested)
    if not project_cfg:
        raise PocError(f"Unknown app or project mapping: {requested}")

    if component:
        for app_key in project_cfg.get("allowed_apps", []):
            aliases = {app_key, *app_mapping["apps"][app_key].get("aliases", [])}
            if component in aliases:
                return app_key
        raise PocError(f"Unknown component '{component}' for project '{requested}'")

    default_app = project_cfg.get("default_app_by_env", {}).get(env)
    if not default_app:
        raise PocError(f"No default deployable app configured for project '{requested}' in env '{env}'")
    return default_app


def _resolve_version(requested_version: str, app_cfg: dict, env: str) -> str:
    aliases = app_cfg.get("version_aliases_by_env", {}).get(env, {})
    return str(aliases.get(requested_version, requested_version))
