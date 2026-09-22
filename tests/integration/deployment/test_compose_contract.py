from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SERVICES = ("app-api", "app-worker")
APP_IMAGE = "project-agent:ws7"
APP_DATA_VOLUME = "project_agent_app_data"
APP_DATA_PATH = "/var/lib/project-agent/data"
DATABASE_URL = (
    "postgresql+asyncpg://project_agent:project_agent@postgres:5432/project_agent"
)
RAGFLOW_BASE_URL = "http://host.docker.internal:9380"


def _render_compose() -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _service(config: dict[str, Any], name: str) -> dict[str, Any]:
    return config["services"][name]


def _environment(service: dict[str, Any]) -> dict[str, str]:
    environment = service.get("environment", {})
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}
    return dict(item.split("=", 1) for item in environment)


def _volume_targets(service: dict[str, Any]) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for volume in service.get("volumes", []):
        if isinstance(volume, dict):
            source = str(volume.get("source", ""))
            target = str(volume.get("target", ""))
        else:
            source, target, *_ = str(volume).split(":")
        targets.add((source, target))
    return targets


def _extra_hosts(service: dict[str, Any]) -> dict[str, str]:
    extra_hosts = service.get("extra_hosts", {})
    if isinstance(extra_hosts, dict):
        return {str(key): str(value) for key, value in extra_hosts.items()}

    result: dict[str, str] = {}
    for item in extra_hosts:
        raw = str(item)
        separator = "=" if "=" in raw else ":"
        host, value = raw.split(separator, 1)
        result[host] = value
    return result


def _ports(service: dict[str, Any]) -> set[tuple[str, str]]:
    ports: set[tuple[str, str]] = set()
    for port in service.get("ports", []):
        if isinstance(port, dict):
            published = str(port.get("published", ""))
            target = str(port.get("target", ""))
        else:
            published, target, *_ = str(port).split(":")
        ports.add((published, target))
    return ports


def _healthcheck_command(service: dict[str, Any]) -> str:
    return " ".join(str(part) for part in service["healthcheck"]["test"])


def test_compose_declares_only_postgres_api_and_worker() -> None:
    config = _render_compose()

    assert set(config["services"]) == {"postgres", "app-api", "app-worker"}
    assert "redis" not in config["services"]
    assert "ragflow" not in config["services"]


def test_api_and_worker_reuse_one_application_image() -> None:
    config = _render_compose()

    for name in APP_SERVICES:
        service = _service(config, name)
        assert service["image"] == APP_IMAGE
        assert Path(service["build"]["context"]).resolve() == REPO_ROOT.resolve()


def test_api_and_worker_share_storage_and_wait_for_healthy_postgres() -> None:
    config = _render_compose()

    assert APP_DATA_VOLUME in config["volumes"]
    for name in APP_SERVICES:
        service = _service(config, name)
        assert (APP_DATA_VOLUME, APP_DATA_PATH) in _volume_targets(service)
        assert service["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_compose_uses_container_database_and_ragflow_host_gateway() -> None:
    config = _render_compose()

    for name in APP_SERVICES:
        service = _service(config, name)
        environment = _environment(service)
        assert environment["DATABASE_URL"] == DATABASE_URL
        assert environment["LOCAL_STORAGE_ROOT"] == APP_DATA_PATH
        assert environment["RAGFLOW_BASE_URL"] == RAGFLOW_BASE_URL
        assert _extra_hosts(service)["host.docker.internal"] == "host-gateway"

    worker_environment = _environment(_service(config, "app-worker"))
    assert worker_environment["RETENTION_SWEEP_ENABLED"] == "false"
    assert worker_environment["WORKER_METRICS_ENABLED"] == "true"
    assert worker_environment["WORKER_METRICS_HOST"] == "0.0.0.0"
    assert worker_environment["WORKER_METRICS_PORT"] == "9101"


def test_compose_exposes_api_and_worker_healthchecks() -> None:
    config = _render_compose()

    api = _service(config, "app-api")
    worker = _service(config, "app-worker")

    assert ("8000", "8000") in _ports(api)
    assert ("9101", "9101") in _ports(worker)
    assert "/ready" in _healthcheck_command(api)
    assert "9101/metrics" in _healthcheck_command(worker)
