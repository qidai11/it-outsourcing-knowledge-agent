from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.models import RetrievalGrade, RetrievalPlan
from project_agent.agent.state import AgentState
from project_agent.application.ports.knowledge import KnowledgeChunk
from project_agent.application.ports.llm import (
    StructuredLLMPort,
    StructuredLLMRequest,
    StructuredLLMUsagePort,
)
from project_agent.application.ports.qa_graph import QAGraphStorePort

_GRADING_SYSTEM_PROMPT = """\
Judge only whether the supplied, already-authorized retrieved chunks are sufficiently relevant
and sufficiently complete to attempt evidence governance and answer the user's query.
Do not decide authority, current/effective version, project membership, knowledge-space access,
or citation validity. Those are enforced elsewhere.
If one bounded second retrieval is justified, return only a refined standalone query.
Never return or request a new project, knowledge space, document ID, or security scope."""


def _build_grading_prompt(
    query: str,
    plan: RetrievalPlan,
    chunks: tuple[KnowledgeChunk, ...],
) -> str:
    lines = [
        f"User query: {query}",
        f"Current standalone query: {plan.standalone_query}",
        "",
        "Already-authorized post-filtered retrieved chunks:",
    ]
    if not chunks:
        lines.append("(none)")
    else:
        for index, chunk in enumerate(chunks, start=1):
            lines.append(f"[{index}] score={chunk.score}: {chunk.content}")
    lines.extend(["", _GRADING_SYSTEM_PROMPT])
    return "\n".join(lines)


async def grade_retrieval_node(
    state: AgentState,
    *,
    llm: StructuredLLMPort,
    llm_usage: StructuredLLMUsagePort,
    store: QAGraphStorePort,
    model_alias: str,
) -> AgentState:
    run_id = UUID(state["run_id"])
    retrieval_round = int(state.get("retrieval_round", 0))
    plan = RetrievalPlan.model_validate(
        await store.load_artifact(UUID(state["retrieval_plan_id"]))
    )
    chunks = await store.load_evidence_bundle(UUID(state["evidence_bundle_id"]))
    query = await store.load_query(run_id)
    request_id = f"{run_id}:qa-retrieval-grade:{retrieval_round}"
    grade = await llm.generate(
        StructuredLLMRequest(
            request_id=request_id,
            model_alias=model_alias,
            system_prompt=_GRADING_SYSTEM_PROMPT,
            user_prompt=_build_grading_prompt(query, plan, chunks),
            temperature=0.0,
            metadata={"run_id": str(run_id), "project_id": str(state.get("project_id") or "")},
        ),
        RetrievalGrade,
    )
    usage = await llm_usage.get_usage(request_id)
    await store.record_llm_usage(
        run_id=run_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
    grade_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_GRADE",
        payload=grade.model_dump(mode="json"),
    )
    if grade.adequate:
        return {
            "retrieval_grade_id": str(grade_id),
            "route": "govern_evidence",
            "last_error_code": None,
        }
    if (
        grade.second_round_justified
        and retrieval_round < 2
        and plan.allow_second_round
        and grade.refined_query is not None
    ):
        refined_plan = plan.model_copy(update={"standalone_query": grade.refined_query.strip()})
        refined_plan_id = await store.save_artifact(
            run_id=run_id,
            artifact_type="RETRIEVAL_PLAN",
            payload=refined_plan.model_dump(mode="json"),
        )
        return {
            "retrieval_grade_id": str(grade_id),
            "retrieval_plan_id": str(refined_plan_id),
            "route": "retrieve_again",
            "last_error_code": None,
        }
    return {
        "retrieval_grade_id": str(grade_id),
        "route": "refusal",
        "last_error_code": "INSUFFICIENT_EVIDENCE",
    }
