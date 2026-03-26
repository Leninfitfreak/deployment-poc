from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import yaml


class PocError(RuntimeError):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def write_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def parse_ticket_description(description: str, field_mapping: dict) -> dict[str, str]:
    values: dict[str, str] = {}
    alias_map: dict[str, str] = {}
    for canonical, config in field_mapping["description_fields"].items():
        for alias in config.get("aliases", []):
            alias_map[alias.lower()] = canonical

    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        canonical = alias_map.get(key.strip().lower())
        if canonical:
            values[canonical] = value.strip()
    return values


def embed_token_in_https_url(url: str, token: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise PocError("only https git remotes are supported for token embedding")
    netloc = f"x-access-token:{token}@{parsed.netloc}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def run(command: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

