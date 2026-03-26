from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

from .utils import PocError


class ArgoCdClient:
    def __init__(self, server: str | None, token: str | None, insecure: bool = False) -> None:
        self.server = (server or "").rstrip("/")
        self.token = token
        self.insecure = insecure
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        if self.server and self._should_disable_tls_verification():
            self.session.verify = False
            requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    def configured(self) -> bool:
        return bool(self.server and self.token)

    def _check_ready(self) -> None:
        if not self.configured():
            raise PocError("ArgoCD credentials not configured. Set ARGOCD_SERVER and ARGOCD_AUTH_TOKEN.")

    def _should_disable_tls_verification(self) -> bool:
        if self.insecure:
            return True
        parsed = urlparse(self.server)
        return parsed.hostname in {"127.0.0.1", "localhost"}

    def get_app_status(self, app_name: str) -> dict:
        self._check_ready()
        response = self.session.get(f"{self.server}/api/v1/applications/{app_name}", timeout=30)
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status", {})
        return {
            "sync": status.get("sync", {}).get("status"),
            "health": status.get("health", {}).get("status"),
            "raw": payload,
        }

    def sync_app(self, app_name: str) -> None:
        self._check_ready()
        response = self.session.post(f"{self.server}/api/v1/applications/{app_name}/sync", json={}, timeout=30)
        response.raise_for_status()

    def wait_until_synced_and_healthy(self, app_name: str, timeout_seconds: int = 600, interval_seconds: int = 15) -> dict:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            status = self.get_app_status(app_name)
            if status["sync"] == "Synced" and status["health"] == "Healthy":
                return status
            time.sleep(interval_seconds)
        raise PocError(f"Timed out waiting for ArgoCD app '{app_name}' to become Synced and Healthy")
