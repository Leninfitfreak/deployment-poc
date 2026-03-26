from __future__ import annotations

from pathlib import Path

from .argocd_client import ArgoCdClient
from .utils import PocError


def run_prechecks(target: dict, infra_repo_dir: Path, argocd_client: ArgoCdClient | None) -> dict:
    values_file = infra_repo_dir / target["values_path"]
    if not values_file.exists():
        raise PocError(f"Target values file not found: {values_file}")

    results = {
        "values_file_exists": True,
        "namespace": target["namespace"],
        "argocd_check_attempted": False,
    }

    if argocd_client and argocd_client.configured():
        results["argocd_check_attempted"] = True
        results["argocd_status"] = argocd_client.get_app_status(target["argocd_app"])

    return results

