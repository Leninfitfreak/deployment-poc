from __future__ import annotations

from urllib.parse import urlparse

import requests


def run_postchecks(target: dict, argocd_status: dict | None) -> dict:
    results = {
        "argocd_status": argocd_status,
        "url_reachable": False,
        "url_check_status": "not-run",
    }
    try:
        response = requests.get(target["url"], timeout=15)
        results["url_reachable"] = response.status_code < 500
        results["url_status_code"] = response.status_code
        results["url_check_status"] = "pass" if results["url_reachable"] else "failure"
    except requests.RequestException as exc:
        results["url_error"] = str(exc)
        parsed = urlparse(target["url"])
        if parsed.hostname and parsed.hostname.endswith(".local"):
            fallback = _check_local_ingress_fallback(target["url"])
            results.update(fallback)
    return results


def _check_local_ingress_fallback(url: str) -> dict:
    parsed = urlparse(url)
    fallback_url = f"{parsed.scheme or 'http'}://127.0.0.1{parsed.path or '/'}"
    if parsed.query:
        fallback_url = f"{fallback_url}?{parsed.query}"
    try:
        response = requests.get(fallback_url, headers={"Host": parsed.netloc}, timeout=15)
        return {
            "url_fallback_url": fallback_url,
            "url_fallback_host_header": parsed.netloc,
            "url_fallback_status_code": response.status_code,
            "url_reachable": response.status_code < 500,
            "url_check_status": "warning",
            "url_warning": f"Direct DNS lookup for {parsed.netloc} failed; localhost host-header fallback succeeded.",
        }
    except requests.RequestException as exc:
        return {
            "url_fallback_url": fallback_url,
            "url_fallback_host_header": parsed.netloc,
            "url_check_status": "warning",
            "url_warning": f"Direct DNS lookup for {parsed.netloc} failed and localhost host-header fallback also failed: {exc}",
        }
