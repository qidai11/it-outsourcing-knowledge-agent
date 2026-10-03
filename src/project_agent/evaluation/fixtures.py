"""Deterministic identifiers and PostgreSQL materialization for WS8 fixtures."""

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_agent.application.ports.knowledge import (
    EnsureKnowledgeSpaceRequest,
    IngestionState,
    KnowledgeIngestionRequest,
)
from project_agent.evaluation.dataset import EvaluationDataset
from project_agent.evaluation.models import CorpusDocument
from project_agent.infrastructure.db.models.schema import (
    CitationModel,
    ClientModel,
    DocumentIdentifierModel,
    DocumentModel,
    DocumentVersionModel,
    EvidenceSnapshotModel,
    ProjectKnowledgeSpaceModel,
    ProjectMembershipModel,
    ProjectModel,
    SandboxIssueModel,
    SandboxProjectModel,
    SystemConfigModel,
)
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter

PROJECT_CODES = ("PRJ-RETAIL-ALPHA", "PRJ-LOGISTICS-BETA")
QA_PROMPT_CONFIG_KEY = "prompt.qa.answer"
QA_PROMPT_CONTENT = (
    "Answer only from governed project evidence. Every factual claim must cite "
    "the supplied Evidence IDs."
)


def _ragflow_dataset_name(namespace: str, project_code: str) -> str:
    # Unique to the WS8 V0 evaluation namespace; never use baseline names.
    return f"ws8-v0-{namespace}-{project_code.lower()}"


def fixture_uuid(
    dataset_version: str,
    logical_key: str,
    *,
    evaluation_namespace: str | UUID,
) -> UUID:
    """Derive a stable UUIDv5 isolated to the requested evaluation namespace."""
    namespace = (
        evaluation_namespace
        if isinstance(evaluation_namespace, UUID)
        else uuid5(
            NAMESPACE_URL,
            f"it-outsourcing-knowledge-agent/ws8/evaluation/{evaluation_namespace}",
        )
    )
    return uuid5(namespace, f"{dataset_version}\0{logical_key}")


def _read_fixture(dataset: EvaluationDataset, name: str) -> dict[str, Any]:
    path = dataset.root / "fixtures" / name
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected fixture object: {path}")
    return value


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _root_doc_code(code: str, documents: Mapping[str, Any]) -> str:
    current = code
    while documents[current].supersedes_doc_code is not None:
        current = documents[current].supersedes_doc_code
    return current


def _version_no(code: str, documents: Mapping[str, Any]) -> int:
    number = 1
    current = code
    while documents[current].supersedes_doc_code is not None:
        number += 1
        current = documents[current].supersedes_doc_code
    return number


async def _ingest_published_corpus(
    *,
    adapter: RagflowAdapter,
    project_docs: Mapping[str, CorpusDocument],
    document_version_ids: Mapping[str, UUID],
    knowledge_space_ids: Mapping[str, UUID | str],
) -> dict[str, dict[str, str]]:
    """Upload published documents and frozen adversarial residue documents."""
    mappings: dict[str, dict[str, str]] = {}
    jobs: dict[str, str] = {}
    for code, frozen in project_docs.items():
        if (
            frozen.lifecycle_status != "PUBLISHED"
            and getattr(frozen, "provider_residue_mode", None)
            != "adversarial_test_only"
        ):
            continue
        dataset_id = str(knowledge_space_ids[frozen.project_code])
        receipt = await adapter.ingest(
            KnowledgeIngestionRequest(
                project_id=frozen.project_code,
                knowledge_space_id=dataset_id,
                document_version_id=str(document_version_ids[code]),
                object_key=code,
                metadata={"filename": f"{code}.md"},
            )
        )
        # This exact format is defined by the existing RagflowAdapter.
        parts = receipt.ingestion_job_id.split(":", 2)
        if (
            len(parts) != 3
            or parts[0] != "ragflow"
            or parts[1] != dataset_id
            or not parts[2]
        ):
            raise ValueError(f"unexpected ingestion receipt for {code}")
        mappings[code] = {"dataset_id": dataset_id, "document_id": parts[2]}
        jobs[code] = receipt.ingestion_job_id

    # Enqueue every document before polling; bounded per-document wait.
    loop = asyncio.get_running_loop()
    for code, job_id in jobs.items():
        deadline = loop.time() + 300.0
        while True:
            status = await adapter.get_ingestion_status(job_id)
            if status.state == IngestionState.SUCCEEDED:
                break
            if status.state == IngestionState.FAILED:
                raise RuntimeError(
                    f"RAGFlow parsing failed for {code}: {status.error_code}"
                )
            if loop.time() >= deadline:
                raise TimeoutError(f"RAGFlow parsing timed out for {code}")
            await asyncio.sleep(1.0)
    return mappings


async def _ensure_required_qa_prompt_config(
    session: AsyncSession,
    *,
    updated_by: UUID,
) -> None:
    existing_prompt = await session.scalar(
        select(SystemConfigModel.id).where(
            SystemConfigModel.config_key == QA_PROMPT_CONFIG_KEY,
            SystemConfigModel.enabled.is_(True),
        )
    )
    if existing_prompt is not None:
        return

    current_version = await session.scalar(
        select(func.max(SystemConfigModel.version)).where(
            SystemConfigModel.config_key == QA_PROMPT_CONFIG_KEY
        )
    )
    session.add(
        SystemConfigModel(
            config_key=QA_PROMPT_CONFIG_KEY,
            config_value_json={"content": QA_PROMPT_CONTENT},
            version=int(current_version or 0) + 1,
            content_hash=sha256(QA_PROMPT_CONTENT.encode()).hexdigest(),
            enabled=True,
            updated_by=updated_by,
        )
    )


async def prepare_v0(
    *,
    dataset: EvaluationDataset,
    evaluation_namespace: str,
    session_factory: async_sessionmaker[AsyncSession],
    ragflow_adapter: RagflowAdapter | None,
) -> Mapping[str, Any]:
    """Materialize V0 fixtures and optional dedicated provider datasets."""

    identities = _read_fixture(dataset, "identities.json")["identities"]
    memberships = _read_fixture(dataset, "memberships.json")["memberships"]
    issues = _read_fixture(dataset, "sandbox-issues.json")["issues"]

    user_ids = {item["alias"]: UUID(item["user_id"]) for item in identities}
    company_id = fixture_uuid(
        dataset.dataset_version,
        "company",
        evaluation_namespace=evaluation_namespace,
    )
    client_ids = {
        code: fixture_uuid(
            dataset.dataset_version,
            f"client:{code}",
            evaluation_namespace=evaluation_namespace,
        )
        for code in PROJECT_CODES
    }
    project_ids = {
        code: fixture_uuid(
            dataset.dataset_version,
            f"project:{code}",
            evaluation_namespace=evaluation_namespace,
        )
        for code in PROJECT_CODES
    }
    # Database row IDs remain deterministic even when RAGFlow supplies its own IDs.
    knowledge_space_row_ids = {
        code: fixture_uuid(
            dataset.dataset_version,
            f"knowledge-space:{code}",
            evaluation_namespace=evaluation_namespace,
        )
        for code in PROJECT_CODES
    }
    knowledge_space_ids: dict[str, UUID | str] = dict(knowledge_space_row_ids)
    if ragflow_adapter is not None:
        for code in PROJECT_CODES:
            space = await ragflow_adapter.ensure_space(
                EnsureKnowledgeSpaceRequest(
                    project_id=code,
                    space_key=_ragflow_dataset_name(evaluation_namespace, code),
                )
            )
            knowledge_space_ids[code] = space.knowledge_space_id
    sandbox_project_ids = {
        code: fixture_uuid(
            dataset.dataset_version,
            f"sandbox-project:{code}",
            evaluation_namespace=evaluation_namespace,
        )
        for code in PROJECT_CODES
    }

    project_docs = {
        code: doc
        for code, doc in dataset.documents_by_code.items()
        if doc.project_code in project_ids
    }
    document_ids = {
        code: fixture_uuid(
            dataset.dataset_version,
            f"document:{_root_doc_code(code, project_docs)}",
            evaluation_namespace=evaluation_namespace,
        )
        for code in project_docs
    }
    document_version_ids = {
        code: fixture_uuid(
            dataset.dataset_version,
            f"document-version:{code}",
            evaluation_namespace=evaluation_namespace,
        )
        for code in project_docs
    }
    membership_ids = {
        item["fact_id"]: fixture_uuid(
            dataset.dataset_version,
            f"membership:{item['fact_id']}",
            evaluation_namespace=evaluation_namespace,
        )
        for item in memberships
    }
    sandbox_issue_ids = {
        item["issue_key"]: fixture_uuid(
            dataset.dataset_version,
            f"sandbox-issue:{item['issue_key']}",
            evaluation_namespace=evaluation_namespace,
        )
        for item in issues
    }

    async with session_factory() as session:
        # Explicit FK barriers: the production session disables autoflush.
        # ORM merge order alone does not guarantee SQL INSERT order.
        for code in PROJECT_CODES:
            await session.merge(
                ClientModel(
                    id=client_ids[code],
                    company_id=company_id,
                    name=f"WS8 V0 {code}",
                )
            )
        await session.flush()

        for code in PROJECT_CODES:
            manager = next(
                item["user_id"]
                for item in memberships
                if item["project_code"] == code and item["expected_current"]
            )
            await session.merge(
                ProjectModel(
                    id=project_ids[code],
                    company_id=company_id,
                    client_id=client_ids[code],
                    code=code,
                    name=f"WS8 V0 {code}",
                    manager_id=UUID(manager),
                )
            )
        await session.flush()

        for code in PROJECT_CODES:
            await session.merge(
                ProjectKnowledgeSpaceModel(
                    id=knowledge_space_row_ids[code],
                    project_id=project_ids[code],
                    provider="ragflow",
                    external_space_id=(
                        str(knowledge_space_ids[code])
                        if ragflow_adapter is not None
                        else f"{evaluation_namespace}:{code}"
                    ),
                )
            )
            await session.merge(
                SandboxProjectModel(
                    id=sandbox_project_ids[code],
                    project_id=project_ids[code],
                    external_key=f"ws8-{sandbox_project_ids[code].hex}",
                    name=f"WS8 V0 {code}",
                )
            )

        # Upgrade legacy Task 2 rows in-place without touching another namespace.
        # Frozen B7 IDs remain benchmark truth, but database row IDs are namespace scoped.
        for item in memberships:
            legacy_id = UUID(item["membership_id"])
            scoped_id = membership_ids[item["fact_id"]]
            if legacy_id != scoped_id and hasattr(session, "get") and hasattr(session, "delete"):
                legacy = await session.get(ProjectMembershipModel, legacy_id)
                if (
                    legacy is not None
                    and legacy.project_id == project_ids[item["project_code"]]
                ):
                    await session.delete(legacy)
        await session.flush()

        for item in memberships:
            valid_from = _parse_datetime(item["valid_from"])
            if valid_from is None:
                raise ValueError("membership valid_from must be present")
            await session.merge(
                ProjectMembershipModel(
                    id=membership_ids[item["fact_id"]],
                    project_id=project_ids[item["project_code"]],
                    user_id=UUID(item["user_id"]),
                    role=item["role"],
                    valid_from=valid_from,
                    valid_to=_parse_datetime(item["valid_to"]),
                )
            )

        created_document_ids: set[UUID] = set()
        for code, doc in project_docs.items():
            document_id = document_ids[code]
            if document_id not in created_document_ids:
                await session.merge(
                    DocumentModel(
                        id=document_id,
                        company_id=company_id,
                        project_id=project_ids[doc.project_code],
                        document_category=doc.document_category,
                        title=doc.title,
                    )
                )
                created_document_ids.add(document_id)

        # Production uses autoflush=False. Persist project/document parents before
        # merging versions so FK ordering never depends on session configuration.
        await session.flush()

        ordered_codes = sorted(project_docs, key=lambda code: _version_no(code, project_docs))
        previous_version_no = 0
        for code in ordered_codes:
            doc = project_docs[code]
            version_no = _version_no(code, project_docs)
            if previous_version_no and version_no != previous_version_no:
                # A successor has a self-FK to the previous version. Flush the
                # preceding level first when production autoflush is disabled.
                await session.flush()
            supersedes = doc.supersedes_doc_code
            await session.merge(
                DocumentVersionModel(
                    id=document_version_ids[code],
                    document_id=document_ids[code],
                    version_no=version_no,
                    version_label=doc.version_label or "unversioned",
                    authority_level=doc.authority_level,
                    lifecycle_status=doc.lifecycle_status,
                    supersedes_version_id=(
                        document_version_ids[supersedes] if supersedes is not None else None
                    ),
                    source_uri=doc.source_path,
                    content_hash=doc.sha256,
                    created_by=next(iter(user_ids.values())),
                )
            )
            previous_version_no = version_no

        # Ensure every DocumentVersion exists in this transaction before seeding
        # its identifier children (autoflush is disabled by the production CLI).
        await session.flush()

        for code, doc in project_docs.items():
            identifier_targets = getattr(doc, "identifier_targets", ())
            for target in identifier_targets:
                await session.merge(
                    DocumentIdentifierModel(
                        id=fixture_uuid(
                            dataset.dataset_version,
                            (
                                f"identifier:{code}:"
                                f"{target['identifier_type']}:"
                                f"{target['normalized_value']}"
                            ),
                            evaluation_namespace=evaluation_namespace,
                        ),
                        company_id=company_id,
                        project_id=project_ids[doc.project_code],
                        document_version_id=document_version_ids[code],
                        identifier_type=target["identifier_type"],
                        normalized_value=target["normalized_value"],
                        raw_value=target.get(
                            "raw_value",
                            target["normalized_value"],
                        ),
                        source=target.get("source", "corpus-manifest"),
                        page_no=target.get("page_no"),
                        section=target.get("section"),
                        confidence=target.get("confidence"),
                    )
                )

        for item in issues:
            legacy_id = UUID(item["issue_id"])
            scoped_id = sandbox_issue_ids[item["issue_key"]]
            if legacy_id != scoped_id and hasattr(session, "get") and hasattr(session, "delete"):
                legacy_issue = await session.get(SandboxIssueModel, legacy_id)
                if (
                    legacy_issue is not None
                    and legacy_issue.project_id == project_ids[item["project_code"]]
                ):
                    await session.delete(legacy_issue)
        await session.flush()

        for item in issues:
            await session.merge(
                SandboxIssueModel(
                    id=sandbox_issue_ids[item["issue_key"]],
                    project_id=project_ids[item["project_code"]],
                    sandbox_project_id=sandbox_project_ids[item["project_code"]],
                    issue_key=item["issue_key"],
                    title=item["title"],
                    description=item["description"],
                    issue_type=item["issue_type"],
                    priority=item["priority"],
                    status=item["status"],
                    module=item["module"],
                    error_code=item["error_code"],
                    environment=item["environment"],
                    reporter_id=user_ids[item["reporter_alias"]],
                    assignee_id=(
                        user_ids[item["assignee_alias"]]
                        if item["assignee_alias"] is not None
                        else None
                    ),
                    source=item["source"],
                    client_request_id=item["client_request_id"],
                )
            )
        await _ensure_required_qa_prompt_config(
            session,
            updated_by=next(iter(user_ids.values())),
        )
        await session.commit()

    ragflow_documents: dict[str, dict[str, str]] = {}
    if ragflow_adapter is not None:
        ragflow_documents = await _ingest_published_corpus(
            adapter=ragflow_adapter,
            project_docs=project_docs,
            document_version_ids=document_version_ids,
            knowledge_space_ids=knowledge_space_ids,
        )

    return {
        "evaluation_namespace": evaluation_namespace,
        "company_id": company_id,
        "client_ids": client_ids,
        "project_ids": project_ids,
        "user_ids": user_ids,
        "membership_ids": membership_ids,
        "document_ids": document_ids,
        "document_version_ids": document_version_ids,
        "knowledge_space_ids": knowledge_space_ids,
        "ragflow_documents": ragflow_documents,
        "sandbox_issue_ids": sandbox_issue_ids,
        "integrity": dict(dataset.integrity),
    }


async def cleanup_v0(
    *,
    evaluation_namespace: str,
    session_factory: async_sessionmaker[AsyncSession],
    ragflow_adapter: RagflowAdapter | None,
) -> None:
    """Clean up only rows and datasets bound to this evaluation namespace."""
    project_ids = [
        fixture_uuid("v0", f"project:{code}", evaluation_namespace=evaluation_namespace)
        for code in PROJECT_CODES
    ]
    client_ids = [
        fixture_uuid("v0", f"client:{code}", evaluation_namespace=evaluation_namespace)
        for code in PROJECT_CODES
    ]
    if ragflow_adapter is not None:
        # Read only the deterministic evaluation project rows; never delete by
        # dataset name alone or enumerate unrelated provider datasets.
        async with session_factory() as session:
            for code, project_id in zip(PROJECT_CODES, project_ids, strict=True):
                stored_id = await session.scalar(
                    select(ProjectKnowledgeSpaceModel.external_space_id).where(
                        ProjectKnowledgeSpaceModel.project_id == project_id,
                        ProjectKnowledgeSpaceModel.provider == "ragflow",
                    )
                )
                bound_ids = ragflow_adapter.space_ids_for_project(code)
                if not bound_ids and stored_id is not None:
                    ragflow_adapter.bind_authorized_space(
                        project_id=code, dataset_id=stored_id
                    )
                    bound_ids = (stored_id,)
                for provider_id in bound_ids:
                    await ragflow_adapter.delete_owned_space(
                        project_id=code,
                        dataset_id=provider_id,
                        expected_name=_ragflow_dataset_name(evaluation_namespace, code),
                    )
    async with session_factory() as session:
        # Project deletion cascades into EvidenceSnapshot rows, while Citation
        # intentionally RESTRICTs deletion of a referenced snapshot. Delete
        # only citations that reference snapshots owned by these deterministic
        # evaluation projects before invoking the existing project cascade.
        evaluation_snapshot_ids = select(EvidenceSnapshotModel.id).where(
            EvidenceSnapshotModel.project_id.in_(project_ids)
        )
        await session.execute(
            delete(CitationModel).where(
                CitationModel.evidence_snapshot_id.in_(evaluation_snapshot_ids)
            )
        )
        await session.execute(delete(ProjectModel).where(ProjectModel.id.in_(project_ids)))
        await session.execute(delete(ClientModel).where(ClientModel.id.in_(client_ids)))
        await session.commit()
