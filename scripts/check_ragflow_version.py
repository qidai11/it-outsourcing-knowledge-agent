from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

from project_agent.application.ports.knowledge import EnsureKnowledgeSpaceRequest
from project_agent.config import Settings
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.infrastructure.ragflow.baseline import (
    BASELINE_DATASET_BINDINGS,
    RAGFLOW_DEFAULT_IMAGE,
    RAGFLOW_STABLE_VERSION,
)
from project_agent.infrastructure.ragflow.client import RagflowRetryPolicy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the pinned RAGFlow V1 baseline.")
    parser.add_argument(
        "--image",
        default=os.getenv("RAGFLOW_IMAGE", ""),
        help=f"Deployed RAGFlow image, for example {RAGFLOW_DEFAULT_IMAGE}",
    )
    parser.add_argument(
        "--ensure-datasets",
        action="store_true",
        help="Create/reuse the three Task 0 baseline datasets.",
    )
    return parser.parse_args()


def validate_declared_version(settings: Settings, image: str) -> None:
    if settings.ragflow_expected_version != RAGFLOW_STABLE_VERSION:
        raise RuntimeError(
            "RAGFLOW_EXPECTED_VERSION must be "
            f"{RAGFLOW_STABLE_VERSION}, got {settings.ragflow_expected_version!r}"
        )
    if image:
        expected_suffix = f":{RAGFLOW_STABLE_VERSION}"
        if not image.endswith(expected_suffix):
            raise RuntimeError(
                f"RAGFlow image must be pinned to {expected_suffix}; got {image!r}"
            )


async def main_async(args: argparse.Namespace) -> int:
    settings = Settings()
    validate_declared_version(settings, args.image)

    base_url = settings.ragflow_base_url.rstrip("/")
    api_key = settings.ragflow_api_key.get_secret_value()
    if not api_key or api_key == "replace-me":
        raise RuntimeError("RAGFLOW_API_KEY is not configured")

    timeout = httpx.Timeout(settings.ragflow_request_timeout_seconds)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as http:
        health = await http.get("/api/v1/system/healthz")
        health.raise_for_status()
        health_payload = health.json()
        if not isinstance(health_payload, dict) or health_payload.get("status") != "ok":
            raise RuntimeError(f"RAGFlow health check is not ok: {health_payload!r}")

        adapter = RagflowAdapter.from_http_client(
            http,
            api_key=api_key,
            embedding_model=settings.ragflow_embedding_model or None,
            chunk_method=settings.ragflow_chunk_method,
            retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
        )

        # Authenticated API-shape check. ensure_space performs the same list call,
        # but keeping this explicit gives clearer diagnostics when API keys fail.
        from project_agent.infrastructure.ragflow.client import RagflowHttpClient

        api = RagflowHttpClient(
            http,
            api_key=api_key,
            retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
        )
        datasets = await api.request_data(
            "GET", "/api/v1/datasets", params={"page": 1, "page_size": 1}
        )
        if not isinstance(datasets, list):
            raise RuntimeError("RAGFlow /api/v1/datasets response shape is incompatible")

        print(f"[PASS] RAGFlow health: {health_payload}")
        print(f"[PASS] Expected version: {RAGFLOW_STABLE_VERSION}")
        if args.image:
            print(f"[PASS] Pinned image: {args.image}")
        else:
            print(
                "[WARN] No --image/RAGFLOW_IMAGE supplied; server API does not expose "
                "a trustworthy version field, so image-tag verification was skipped."
            )

        if args.ensure_datasets:
            print("Baseline datasets:")
            for project_id, space_key in BASELINE_DATASET_BINDINGS.items():
                space = await adapter.ensure_space(
                    EnsureKnowledgeSpaceRequest(project_id=project_id, space_key=space_key)
                )
                print(f"  {project_id}: {space.space_key} -> {space.knowledge_space_id}")

    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
