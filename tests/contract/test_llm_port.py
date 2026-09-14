from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, ValidationError

from project_agent.application.ports.llm import StructuredLLMPort, StructuredLLMRequest
from tests.fakes.llm import FakeStructuredLLM


class RouteDecision(BaseModel):
    route: Literal["knowledge", "issue"]


@pytest.mark.asyncio
async def test_fake_structured_llm_validates_response_model() -> None:
    llm = FakeStructuredLLM()
    assert isinstance(llm, StructuredLLMPort)
    llm.queue_response({"route": "knowledge"})

    result = await llm.generate(
        StructuredLLMRequest(
            request_id="llm-1",
            model_alias="fake-default",
            system_prompt="Return a route.",
            user_prompt="How do I deploy?",
        ),
        RouteDecision,
    )

    assert result == RouteDecision(route="knowledge")
    assert llm.calls[0].request.request_id == "llm-1"


@pytest.mark.asyncio
async def test_fake_structured_llm_rejects_invalid_structured_output() -> None:
    llm = FakeStructuredLLM()
    llm.queue_response({"route": "invalid-route"})

    with pytest.raises(ValidationError):
        await llm.generate(
            StructuredLLMRequest(
                request_id="llm-2",
                model_alias="fake-default",
                system_prompt="Return a route.",
                user_prompt="Create an issue.",
            ),
            RouteDecision,
        )
