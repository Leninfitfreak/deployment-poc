from __future__ import annotations

import requests


def run_postchecks(target: dict, argocd_status: dict | None) -> dict:
    results = {
        "argocd_status": argocd_status,
        "url_reachable": False,
    }
    try:
        response = requests.get(target["url"], timeout=15)
        results["url_reachable"] = response.status_code < 500
        results["url_status_code"] = response.status_code
    except requests.RequestException as exc:
        results["url_error"] = str(exc)
    return results

