from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.models import GroundedAnswerDraft
from project_agent.agent.state import AgentState
from project_agent.application.ports.llm import (
    StructuredLLMPort,
    StructuredLLMRequest,
    StructuredLLMUsagePort,
)
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.domain.evidence import FrozenEvidenceBundle


def _build_grounded_evidence_prompt(query: str, bundle: FrozenEvidenceBundle) -> str:
    sections = [f"用户问题：{query}", "", "可引用 Evidence："]
    for item in bundle.evidence:
        location_parts: list[str] = []
        if item.page_no is not None:
            location_parts.append(f"page={item.page_no}")
        if item.section:
            location_parts.append(f"section={item.section}")
        location = ", ".join(location_parts) or "location=unknown"
        sections.append(
            f"[{item.label}] authority={item.authority_level.value}; "
            f"document={item.document_title}; version={item.version_label}; {location}\n"
            f"{item.content}"
        )
    if bundle.unresolved_conflicts:
        sections.append("")
        sections.append("以下冲突未能通过 AuthorityPolicy 唯一解决，必须显式披露：")
        for key, labels in bundle.unresolved_conflicts.items():
            sections.append(f"- {key}: {', '.join(labels)}")
    sections.extend(
        [
            "",
            "输出规则：",
            "1. 只输出可由上述 Evidence 支撑的事实 Claim。",
            "2. 每条 Claim 必须绑定至少一个 Evidence ID，例如 E1。",
            "3. 不得编造不存在的 Evidence ID。",
            "4. 如果存在未解决冲突，conflict_disclosure 必须引用冲突双方 Evidence。",
            "5. 不要依赖模型自身知识补充项目事实。",
        ]
    )
    return "\n".join(sections)


async def _generate_draft(
    state: AgentState,
    *,
    llm: StructuredLLMPort,
    llm_usage: StructuredLLMUsagePort,
    store: QAGraphStorePort,
    model_alias: str,
    revision_errors: tuple[str, ...] = (),
) -> tuple[UUID, str]:
    run_id = UUID(state["run_id"])
    query = await store.load_query(run_id)
    prompt_artifact = await store.load_artifact(UUID(state["prompt_snapshot_id"]))
    system_prompt = prompt_artifact.get("content")
    if not isinstance(system_prompt, str):
        raise ValueError("prompt snapshot content is missing")
    bundle = await store.load_governed_evidence_bundle(UUID(state["evidence_bundle_id"]))
    if not bundle.evidence:
        raise ValueError("answer generation requires governed Evidence")

    user_prompt = _build_grounded_evidence_prompt(query, bundle)
    revision_no = int(state.get("revision_count", 0))
    if revision_errors:
        user_prompt += (
            "\n\n上一次草稿未通过 Citation Guard，请只修复以下问题，不增加新事实：\n- "
            + "\n- ".join(revision_errors)
        )
    request_id = f"{run_id}:qa-answer:{revision_no}"
    response = await llm.generate(
        StructuredLLMRequest(
            request_id=request_id,
            model_alias=model_alias,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            metadata={"run_id": str(run_id), "project_id": str(state["project_id"])},
        ),
        GroundedAnswerDraft,
    )
    usage = await llm_usage.get_usage(request_id)
    await store.record_llm_usage(
        run_id=run_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
    draft_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="ANSWER_DRAFT",
        payload=response.model_dump(mode="json"),
    )
    return draft_id, request_id


async def generate_answer_node(
    state: AgentState,
    *,
    llm: StructuredLLMPort,
    llm_usage: StructuredLLMUsagePort,
    store: QAGraphStorePort,
    model_alias: str,
) -> AgentState:
    draft_id, _ = await _generate_draft(
        state,
        llm=llm,
        llm_usage=llm_usage,
        store=store,
        model_alias=model_alias,
    )
    return {
        "answer_draft_id": str(draft_id),
        "revision_count": int(state.get("revision_count", 0)),
        "route": "citation_guard",
        "last_error_code": None,
    }
