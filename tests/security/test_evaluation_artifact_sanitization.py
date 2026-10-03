"""Collector must never serialize credentials from transport, provider or DB rows."""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from project_agent.evaluation.artifacts import ArtifactStore, _to_jsonable
from project_agent.evaluation.collector import (
    RunFacts,
    RunObservation,
    SideEffectSnapshot,
    TrialCollector,
)
from project_agent.evaluation.models import EvaluationCase

RUN_ID, PROJECT_ID = uuid4(), uuid4()
CASE = EvaluationCase(
    case_id="Q001", split="acceptance", priority="P1", project_code="PRJ-RETAIL-ALPHA",
    user_alias="alpha_dev", user_role="developer", question_type="knowledge_qa",
    question="Safe benchmark question", expected_behavior="answer",
    expected_source_type="requirement", expected_identifier=None,
    expected_project_scope="PRJ-RETAIL-ALPHA", notes=None,
)
STATE = {"project_ids": {CASE.project_code: PROJECT_ID}}


class Reader:
    def __init__(self, facts: RunFacts):
        self.facts = facts

    async def read(self, *, run_id, project_id, request_id):  # type: ignore[no-untyped-def]
        assert project_id == PROJECT_ID
        return self.facts


async def _collect(
    tmp_path, *, answer=None, query=None, error_category=None, events=()
):  # type: ignore[no-untyped-def]
    facts = RunFacts(
        run=SimpleNamespace(id=RUN_ID, thread_id=uuid4(), project_id=PROJECT_ID,
                            user_id=uuid4(), status="SUCCEEDED", business_mode="qa",
                            started_at=None, finished_at=None, model_alias=None,
                            prompt_version=None, prompt_content_hash=None,
                            input_tokens=0, output_tokens=0, total_tokens=0),
        answer=SimpleNamespace(answer_text=answer, refusal_reason=None) if answer else None,
        events=events,
    )
    trial = await TrialCollector(Reader(facts)).collect(
        case=replace(CASE, question=query) if query else CASE,
        run_observation=RunObservation(trial_no=1, run_id=RUN_ID, http_status=200,
                                       error_category=error_category),
        fixture_state=STATE, before_state=SideEffectSnapshot(count=0),
        after_state=SideEffectSnapshot(count=0),
    )
    store = ArtifactStore(tmp_path, "safe-run")
    store.write_json(store.trial_path(trial.case_id, trial.trial_no), trial)
    return json.dumps(_to_jsonable(trial))


@pytest.mark.asyncio
async def test_trial_artifact_contains_no_authorization_header(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    secret = "Bearer testauthorizationtoken01234567890"
    artifact = await _collect(tmp_path, answer=f"authorization: {secret}")
    assert secret not in artifact
    assert "[REDACTED]" in artifact


@pytest.mark.asyncio
async def test_trial_artifact_contains_no_jwt(tmp_path) -> None:  # type: ignore[no-untyped-def]
    secret = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    artifact = await _collect(tmp_path, query=f"exposed {secret}")
    assert secret not in artifact
    assert "[REDACTED]" in artifact


@pytest.mark.asyncio
async def test_trial_artifact_contains_no_ragflow_or_llm_api_key(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    events = (SimpleNamespace(sequence_no=1, event_type="ARTIFACT_AVAILABLE",
                payload_json={"artifact_type": "ANSWER_DRAFT", "artifact": {
                    "llm_api_key": "LLM_TEST_SECRET_123456",
                    "ragflow_api_key": "RAGFLOW_TEST_SECRET_987654",
                }}),)
    artifact = await _collect(
        tmp_path, answer="ragflow_api_key=RAGFLOW_TEST_SECRET_987654", events=events,
    )
    assert "RAGFLOW_TEST_SECRET" not in artifact
    assert "LLM_TEST_SECRET" not in artifact


@pytest.mark.asyncio
async def test_trial_artifact_contains_no_database_password(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    secret = (
        "postgresql+asyncpg://user:databasepassword@localhost:5432/eval_db"
    )
    artifact = await _collect(
        tmp_path, answer=f"DB connection failed: {secret}",
        error_category=f"DB_FAILURE_{secret}",
    )
    assert "databasepassword" not in artifact
    assert "UNCLASSIFIED_ERROR" in artifact
