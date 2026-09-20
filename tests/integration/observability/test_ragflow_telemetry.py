from __future__ import annotations

import os

import httpx
import pytest

from project_agent.infrastructure.ragflow.client import RagflowHttpClient
from project_agent.observability.metrics import ObservabilityMetrics, metrics_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_RAGFLOW_INTEGRATION") != "1",
    reason="set RUN_RAGFLOW_INTEGRATION=1 to run WS6 real RAGFlow telemetry gate",
)


@pytest.mark.asyncio
async def test_real_ragflow_success_records_bounded_operation_metric() -> None:
    base_url = os.environ["RAGFLOW_BASE_URL"].rstrip("/")
    api_key = os.environ["RAGFLOW_API_KEY"]
    metrics = ObservabilityMetrics()
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        client = RagflowHttpClient(http, api_key=api_key)
        with metrics_context(metrics):
            await client.request_data("GET", "/api/v1/datasets")
    rendered = metrics.render_latest().decode()
    expected = (
        'project_agent_ragflow_requests_total'
        '{operation="dataset_list",outcome="success"} 1.0'
    )
    assert expected in rendered
    assert base_url not in rendered
    assert api_key not in rendered
