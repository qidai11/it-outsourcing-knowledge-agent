"""Task 4 canonical WS8 Runner: frozen inputs -> real Run API -> raw trials.

Exactly one secret-safe artifact is written for every selected case. The only
non-API write path is the explicitly frozen Q044/Q045 evaluation fault driver,
which reuses production Issue services and the same evaluation PostgreSQL DB.
"""
from __future__ import annotations

import hashlib
import platform
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_agent.evaluation.artifacts import ArtifactStore, SecretArtifactError
from project_agent.evaluation.client import (
    EvaluationClient,
    EvaluationHttpError,
    EvaluationTimeout,
    HttpRunResult,
)
from project_agent.evaluation.collector import (
    RunObservation,
    SideEffectSnapshot,
    SqlAlchemyTrialReader,
    TrialCollector,
)
from project_agent.evaluation.dataset import EvaluationDataset
from project_agent.evaluation.models import (
    EvaluationCase,
    EvaluationRunManifest,
    GoldScoringStatus,
    RunProtocol,
    TrialArtifact,
    TrialClassification,
)
from project_agent.evaluation.scenarios import (
    ScenarioOutcome,
    load_frozen_scenarios,
)
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    IssueDraftModel,
)

RUNNER_VERSION = "ws8-task4-v0"
FROZEN_UNSCORABLE = frozenset({"Q014", "Q046", "Q049"})


def select_cases(
    dataset: EvaluationDataset,
    *,
    case_ids: Sequence[str] | None = None,
    split: str | None = None,
    priority: str | None = None,
    business_mode: str | None = None,
) -> tuple[EvaluationCase, ...]:
    """Deterministic catalog-order selection; unknown IDs are an operator error."""
    requested = set(case_ids or ())
    known = {case.case_id for case in dataset.cases}
    if unknown := requested.difference(known):
        raise ValueError(f"unknown frozen evaluation case(s): {', '.join(sorted(unknown))}")
    if case_ids is not None and len(requested) != len(case_ids):
        raise ValueError("duplicate selected evaluation case")
    result = tuple(
        case for case in dataset.cases
        if (case_ids is None or case.case_id in requested)
        and (split is None or case.split == split)
        and (priority is None or case.priority == priority)
        and (
            business_mode is None
            or dataset.gold_for(case.case_id).execution.business_mode == business_mode
        )
    )
    if not result:
        raise ValueError("selection matched zero frozen evaluation cases")
    return result


def fallback_trial(
    case: EvaluationCase,
    trial_no: int,
    classification: TrialClassification,
    *,
    business_mode: str | None = None,
    http_status: int | None = None,
    run_id: UUID | None = None,
    thread_id: UUID | None = None,
    error_category: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    started_at: datetime | None = None,
) -> TrialArtifact:
    """No fabricated answer, status, telemetry, citations or side effects."""
    return TrialArtifact(
        case_id=case.case_id,
        trial_no=trial_no,
        classification=classification,
        business_mode=business_mode or case.question_type,
        project_code=case.project_code,
        user_alias=case.user_alias,
        query=case.question,
        query_sha256=hashlib.sha256(case.question.encode("utf-8")).hexdigest(),
        run_id=str(run_id) if run_id is not None else None,
        thread_id=str(thread_id) if thread_id is not None else None,
        http_status=http_status,
        error_category=error_category,
        started_at=started_at.isoformat() if started_at is not None else None,
        finished_at=datetime.now(UTC).isoformat(),
        metadata=metadata or {},
    )


class EvaluationBackend(Protocol):
    async def capture_side_effects(
        self, *, project_id: UUID, request_id: str
    ) -> SideEffectSnapshot: ...
    async def collect(
        self,
        *,
        case: EvaluationCase,
        observation: RunObservation,
        fixture_state: Mapping[str, Any],
        before_state: SideEffectSnapshot,
        after_state: SideEffectSnapshot,
    ) -> TrialArtifact: ...
    async def count_runs(self, *, project_id: UUID, user_id: UUID) -> int: ...
    async def waiting_hash(self, *, run_id: UUID, project_id: UUID) -> str: ...


class IssueScenario(Protocol):
    def request_id(self, case: EvaluationCase) -> str: ...
    async def execute(self, case: EvaluationCase, run_id: UUID) -> ScenarioOutcome: ...


class PostgresEvaluationBackend:
    """Read-only, short-lived sessions; every query is evaluation-project scoped."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def capture_side_effects(
        self, *, project_id: UUID, request_id: str
    ) -> SideEffectSnapshot:
        async with self._sessions() as session:
            return await SqlAlchemyTrialReader(session).capture_side_effects(
                project_id=project_id, request_id=request_id,
            )

    async def count_runs(self, *, project_id: UUID, user_id: UUID) -> int:
        async with self._sessions() as session:
            value = await session.scalar(select(func.count(AgentRunModel.id)).where(
                AgentRunModel.project_id == project_id,
                AgentRunModel.user_id == user_id,
            ))
            return int(value or 0)

    async def waiting_hash(self, *, run_id: UUID, project_id: UUID) -> str:
        async with self._sessions() as session:
            run = await session.get(AgentRunModel, run_id)
            if run is None or run.project_id != project_id:
                raise ValueError("waiting Run not owned by the evaluation project")
            event = await session.scalar(
                select(AgentEventModel).where(
                    AgentEventModel.run_id == run_id,
                    AgentEventModel.event_type == "WAITING_CONFIRMATION",
                ).order_by(AgentEventModel.sequence_no.desc()).limit(1)
            )
            if event is None or not isinstance(event.payload_json, dict):
                raise ValueError("persisted WAITING_CONFIRMATION event not found")
            import re

            value = event.payload_json.get("request_payload_hash")
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("persisted WAITING_CONFIRMATION hash is missing/invalid")
            return value

    async def request_id_for_run(self, *, run_id: UUID, project_id: UUID) -> str | None:
        async with self._sessions() as session:
            value = await session.scalar(select(IssueDraftModel.id).where(
                IssueDraftModel.run_id == run_id, IssueDraftModel.project_id == project_id,
            ).order_by(IssueDraftModel.created_at.desc(), IssueDraftModel.id.desc()).limit(1))
            return str(value) if value is not None else None

    async def collect(
        self, *, case: EvaluationCase, observation: RunObservation,
        fixture_state: Mapping[str, Any], before_state: SideEffectSnapshot,
        after_state: SideEffectSnapshot,
    ) -> TrialArtifact:
        async with self._sessions() as session:
            return await TrialCollector(SqlAlchemyTrialReader(session)).collect(
                case=case, run_observation=observation, fixture_state=fixture_state,
                before_state=before_state, after_state=after_state,
            )


class EvaluationRunner:
    """Orchestrate frozen protocols and never silently skip an attempted case."""

    def __init__(
        self,
        dataset: EvaluationDataset,
        fixture_state: Mapping[str, Any],
        store: ArtifactStore,
        client: EvaluationClient,
        backend: EvaluationBackend,
        *,
        scenario_driver: IssueScenario | None = None,
        git_commit: str = "unavailable",
        dirty_worktree: bool = True,
        model_alias: str | None = None,
    ) -> None:
        if fixture_state.get("evaluation_namespace") is None:
            raise ValueError("evaluation fixture namespace is required")
        self._dataset = dataset
        self._state = fixture_state
        self._store = store
        self._client = client
        self._backend = backend
        self._scenarios = load_frozen_scenarios(dataset.root)
        self._issue_driver = scenario_driver
        self._git_commit = git_commit
        self._dirty_worktree = dirty_worktree
        self._model_alias = model_alias
        self._last_response: HttpRunResult | None = None
        self._setup_run_id: UUID | None = None
        frozen_scopes = {
            case.case_id for case in dataset.cases
            if dataset.gold_for(case.case_id).scoring.status
            is GoldScoringStatus.UNSCORABLE_RUNTIME_SCOPE
        }
        if frozen_scopes != FROZEN_UNSCORABLE:
            raise ValueError("B7 runtime-scope set changed; refuse evaluation")

    async def run(
        self,
        *,
        case_ids: Sequence[str] | None = None,
        split: str | None = None,
        priority: str | None = None,
        business_mode: str | None = None,
    ) -> tuple[TrialArtifact, ...]:
        selected = select_cases(
            self._dataset, case_ids=case_ids, split=split, priority=priority,
            business_mode=business_mode,
        )
        if self._store.run_manifest_path.exists():
            raise FileExistsError("evaluation run already contains a manifest; refuse overwrite")
        integrity = self._dataset.integrity
        manifest = EvaluationRunManifest(
            evaluation_run_id=self._store.evaluation_run_id,
            dataset_version=self._dataset.dataset_version,
            data_provenance=self._dataset.data_provenance,
            corpus_version=self._dataset.corpus_version,
            gold_schema_version=self._dataset.gold_schema_version,
            metric_definition_version=self._dataset.metric_definition_version,
            git_commit=self._git_commit,
            dirty_worktree=self._dirty_worktree,
            selected_case_ids=tuple(case.case_id for case in selected),
            started_at=datetime.now(UTC).isoformat(),
            python_version=platform.python_version(),
            model_alias=self._model_alias,
            ragflow_expected_version=str(
                self._dataset.manifest.get("project_baseline", {}).get("ragflow_version", "")
            ),
            runner_version=RUNNER_VERSION,
            dataset_sha256=str(integrity["question_catalog_sha256"]),
            corpus_sha256=str(integrity["corpus_sha256"]),
            gold_sha256=str(integrity["gold_manifest_sha256"]),
            metadata={"evaluation_namespace": self._state["evaluation_namespace"]},
        )
        self._store.write_json(self._store.run_manifest_path, manifest)
        results: list[TrialArtifact] = []
        for case in selected:
            gold = self._dataset.gold_for(case.case_id)
            started = datetime.now(UTC)
            self._last_response = None
            self._setup_run_id = None
            mode = gold.execution.business_mode
            try:
                trial = await self._execute_case(case)
            except (TimeoutError, EvaluationTimeout, EvaluationHttpError, ConnectionError, OSError):
                trial = fallback_trial(
                    case, 1, TrialClassification.INFRA_FAILURE, business_mode=mode,
                    error_category="INFRA_OR_TIMEOUT", started_at=started,
                    run_id=self._last_response.run_id if self._last_response else None,
                    thread_id=self._last_response.thread_id if self._last_response else None,
                    http_status=self._last_response.http_status if self._last_response else None,
                    metadata=self._failure_metadata(gold.execution.run_protocol),
                )
            except Exception:
                # Never put exception messages or raw transport payloads into artifacts.
                trial = fallback_trial(
                    case, 1, TrialClassification.RUNNER_FAILURE, business_mode=mode,
                    error_category="SCENARIO_OR_COLLECTOR_FAILURE", started_at=started,
                    run_id=self._last_response.run_id if self._last_response else None,
                    thread_id=self._last_response.thread_id if self._last_response else None,
                    http_status=self._last_response.http_status if self._last_response else None,
                    metadata=self._failure_metadata(gold.execution.run_protocol),
                )
            try:
                self._store.write_json(self._store.trial_path(case.case_id, 1), trial)
            except (SecretArtifactError, TypeError):
                # Reject all unsafe/unserializable Collector output. Still write
                # one safe, traceable failure artifact and process the next case.
                trial = fallback_trial(
                    case, 1, TrialClassification.RUNNER_FAILURE, business_mode=mode,
                    error_category="UNSAFE_OR_UNSERIALIZABLE_ARTIFACT", started_at=started,
                    run_id=self._last_response.run_id if self._last_response else None,
                    thread_id=self._last_response.thread_id if self._last_response else None,
                    http_status=self._last_response.http_status if self._last_response else None,
                    metadata=self._failure_metadata(gold.execution.run_protocol),
                )
                self._store.write_json(self._store.trial_path(case.case_id, 1), trial)
            results.append(trial)
        return tuple(results)

    def _failure_metadata(self, protocol: RunProtocol) -> dict[str, str]:
        metadata = {"run_protocol": protocol.value}
        if self._setup_run_id is not None:
            metadata["setup_run_id"] = str(self._setup_run_id)
        return metadata

    async def _create_run(
        self,
        *,
        user_alias: str,
        project_id: UUID,
        business_mode: str,
        query: str,
        thread_id: UUID | None = None,
        overrides: Mapping[str, Any] | None = None,
        allow_denial: bool = False,
    ) -> HttpRunResult:
        result = await self._client.create_run(
            user_alias=user_alias, project_id=project_id, business_mode=business_mode,
            query=query, thread_id=thread_id, overrides=overrides, allow_denial=allow_denial,
        )
        self._last_response = result
        return result

    async def _execute_case(self, case: EvaluationCase) -> TrialArtifact:
        gold = self._dataset.gold_for(case.case_id)
        protocol = gold.execution.run_protocol
        mode = gold.execution.business_mode
        meta: dict[str, Any] = {"run_protocol": protocol.value}
        if gold.scoring.status is GoldScoringStatus.UNSCORABLE_RUNTIME_SCOPE:
            if protocol is not RunProtocol.UNSCORABLE_RUNTIME_SCOPE:
                raise ValueError("scope Gold/protocol mismatch")
            return fallback_trial(
                case, 1, TrialClassification.UNSCORABLE_RUNTIME_SCOPE,
                business_mode=mode, error_category="FROZEN_RUNTIME_SCOPE",
                metadata={**meta, "reason": gold.scoring.reason or "frozen runtime mismatch"},
            )
        if gold.scoring.status is GoldScoringStatus.UNSCORABLE_GOLD:
            return fallback_trial(
                case, 1, TrialClassification.UNSCORABLE_GOLD, business_mode=mode,
                error_category="FROZEN_GOLD_UNSCORABLE", metadata=meta,
            )
        project_id = UUID(str(self._state["project_ids"][gold.execution.project_code]))
        user_alias = gold.execution.user_alias
        user_id = UUID(str(self._state["user_ids"][user_alias]))
        request_id = f"eval-v0-{case.case_id.lower()}-trial-001"
        overrides = gold.execution.request_overrides or {}
        if protocol is RunProtocol.AUTHORIZATION_DENIAL:
            target = overrides.get("requested_project_code") or gold.execution.project_code
            project_id = UUID(str(self._state["project_ids"][str(target)]))
            run_count_before = await self._backend.count_runs(
                project_id=project_id, user_id=user_id
            )
            response = await self._create_run(
                user_alias=user_alias, project_id=project_id,
                business_mode=mode, query=case.question,
                overrides=overrides.get("extra_json_fields"), allow_denial=True,
            )
            run_count_after = await self._backend.count_runs(
                project_id=project_id, user_id=user_id
            )
            expected = tuple(int(item) for item in gold.expected["expected_http_statuses"])
            if (
                response.http_status not in expected
                or response.run_id is not None
                or run_count_after != run_count_before
            ):
                raise ValueError("authorization denial or no-Run invariant violated")
            trial = await self._collect(
                case, project_id=project_id,
                observation=RunObservation(
                    trial_no=1, business_mode=mode, http_status=response.http_status,
                    request_id=request_id,
                ),
                request_id=request_id,
            )
            return replace(trial, metadata={**trial.metadata, **meta,
                                            "run_count_before": run_count_before,
                                            "run_count_after": run_count_after})
        if protocol is RunProtocol.SETUP_THEN_RUN:
            setup_id = gold.execution.setup_scenario
            if setup_id is None or setup_id not in self._scenarios.setups:
                raise ValueError("unknown frozen setup protocol")
            setup_config = self._scenarios.setups[setup_id]
            if setup_config["project_code"] != case.project_code:
                raise ValueError("setup project differs from measured case")
            if setup_id == "SETUP_ALPHA_VIEWER_CONTEXT":
                # Q001 is already a frozen QA catalog input; no viewer draft/write.
                setup_query = next(c.question for c in self._dataset.cases if c.case_id == "Q001")
            elif setup_id == "SETUP_ALPHA_DATE_DEFECT_CONTEXT":
                setup_query = str(setup_config["context"]["summary"])
            else:
                raise ValueError("unsupported setup_then_run protocol")
            prior = await self._create_run(
                user_alias=user_alias, project_id=project_id,
                business_mode="qa", query=setup_query,
            )
            if prior.run_id is None or prior.thread_id is None:
                raise ValueError("prior context Run not created")
            self._setup_run_id = prior.run_id
            prior_terminal = await self._client.poll_run(user_alias=user_alias, run_id=prior.run_id)
            # The setup Run materializes evaluation-owned prior context.
            # A terminal FAILED status is still an observable product outcome;
            # it must not prevent the measured case from being submitted.
            # Transport/polling failures remain pipeline failures before this point.
            if prior_terminal.status not in {"SUCCEEDED", "REFUSED", "FAILED"}:
                raise ValueError("prior context setup did not reach a terminal state")
            meta.update({"setup_scenario": setup_id, "setup_run_id": str(prior.run_id)})
            thread_id = prior.thread_id
        else:
            thread_id = None
        if protocol is RunProtocol.WAITING_CONFIRMATION_RESUME:
            if gold.execution.setup_scenario != "SETUP_ALPHA_DATE_DRAFT_WAITING":
                raise ValueError("unknown frozen waiting setup")
            setup_query = next(c.question for c in self._dataset.cases if c.case_id == "Q016")
            waiting_setup = await self._create_run(
                user_alias=user_alias, project_id=project_id,
                business_mode="issue_create", query=setup_query,
            )
            if waiting_setup.run_id is None:
                raise ValueError("waiting setup Run not created")
            self._setup_run_id = waiting_setup.run_id
            waiting = await self._client.poll_run(
                user_alias=user_alias, run_id=waiting_setup.run_id, until_waiting=True,
            )
            if waiting.status != "WAITING_CONFIRMATION":
                raise ValueError("waiting setup did not reach WAITING_CONFIRMATION")
            hash_from_event = await self._backend.waiting_hash(
                run_id=waiting_setup.run_id, project_id=project_id,
            )
            find_request_id = getattr(self._backend, "request_id_for_run", None)
            if callable(find_request_id):
                persisted_id = await find_request_id(
                    run_id=waiting_setup.run_id, project_id=project_id
                )
                if persisted_id is not None:
                    request_id = persisted_id
            before_state = await self._backend.capture_side_effects(
                project_id=project_id, request_id=request_id,
            )
            if before_state.count != 0:
                raise ValueError("sandbox side effect occurred before confirmation")
            resumed = await self._client.resume_run(
                user_alias=user_alias, run_id=waiting_setup.run_id,
                request_payload_hash=hash_from_event,
            )
            terminal = await self._client.poll_run(
                user_alias=user_alias, run_id=waiting_setup.run_id
            )
            after_state = await self._backend.capture_side_effects(
                project_id=project_id, request_id=request_id,
            )
            trial = await self._backend.collect(
                case=case, observation=RunObservation(
                    trial_no=1, run_id=waiting_setup.run_id, business_mode=mode,
                    http_status=resumed.http_status, request_id=request_id,
                ),
                fixture_state=self._state,
                before_state=before_state, after_state=after_state,
            )
            return replace(trial, metadata={**trial.metadata, **meta,
                                            "setup_scenario": gold.execution.setup_scenario,
                                            "setup_run_id": str(waiting_setup.run_id),
                                            "resume_terminal_status": terminal.status,
                                            "payload_hash_source": "persisted_waiting_event"})
        if protocol in {RunProtocol.SAME_REQUEST_REPLAY, RunProtocol.RESPONSE_LOSS_RECONCILE}:
            if self._issue_driver is None:
                raise ValueError("frozen fault protocol requires a PostgreSQL Issue driver")
            request_id = self._issue_driver.request_id(case)
            before_state = await self._backend.capture_side_effects(
                project_id=project_id, request_id=request_id,
            )
            if before_state.count != 0:
                raise ValueError("fixed request ID already has side effects")
            response = await self._create_run(
                user_alias=user_alias, project_id=project_id,
                business_mode=mode, query=case.question,
            )
            if response.run_id is None:
                raise ValueError("fault trial Run was not created")
            outcome = await self._issue_driver.execute(case, response.run_id)
            if outcome.request_id != request_id:
                raise ValueError("fault driver changed fixed logical request ID")
            after_state = await self._backend.capture_side_effects(
                project_id=project_id, request_id=request_id,
            )
            if after_state.count != before_state.count + 1:
                raise ValueError("fault protocol did not produce exactly one side effect")
            trial = await self._backend.collect(
                case=case,
                observation=RunObservation(
                    trial_no=1, run_id=response.run_id, http_status=response.http_status,
                    business_mode=mode, request_id=request_id,
                    reconciliation_outcome=outcome.status,
                ),
                fixture_state=self._state,
                before_state=before_state, after_state=after_state,
            )
            return replace(trial, metadata={**trial.metadata, **meta,
                                            "fault_scenario": gold.execution.fault_scenario,
                                            "setup_scenario": gold.execution.setup_scenario,
                                            "observed_creation_outcome": outcome.status})
        if protocol not in {RunProtocol.SINGLE_RUN, RunProtocol.SETUP_THEN_RUN}:
            raise ValueError("unsupported frozen run protocol")
        # For issue-create, the authoritative logical request ID is persisted
        # by the production run. It is not known until the measured Run reaches
        # its waiting/terminal observation, so defer BOTH side-effect snapshots
        # until that ID has been resolved. Mixing the synthetic evaluation ID
        # with the persisted ID violates Collector's request-scoping invariant.
        measured_before_state: SideEffectSnapshot | None = None
        if mode != "issue_create":
            measured_before_state = await self._backend.capture_side_effects(
                project_id=project_id, request_id=request_id,
            )

        # A preceding setup Run is context, not the measured Run: an HTTP
        # failure creating the latter must not claim the setup ID as its trace.
        if protocol is RunProtocol.SETUP_THEN_RUN:
            self._last_response = None
        response = await self._create_run(
            user_alias=user_alias, project_id=project_id,
            business_mode=mode, query=case.question, thread_id=thread_id,
        )
        if response.run_id is None:
            raise ValueError("API accepted Run without an identifier")
        terminal = await self._client.poll_run(
            user_alias=user_alias, run_id=response.run_id,
            until_waiting=mode == "issue_create",
        )
        if mode == "issue_create":
            find_request_id = getattr(self._backend, "request_id_for_run", None)
            if callable(find_request_id):
                persisted_id = await find_request_id(
                    run_id=response.run_id, project_id=project_id,
                )
                if persisted_id is not None:
                    request_id = persisted_id

            measured_before_state = await self._backend.capture_side_effects(
                project_id=project_id, request_id=request_id,
            )

        if measured_before_state is None:
            raise AssertionError("side-effect baseline was not captured")

        after_state = await self._backend.capture_side_effects(
            project_id=project_id, request_id=request_id,
        )
        if mode == "issue_create" and after_state.count:
            raise ValueError("issue_create produced unconfirmed side effect")
        trial = await self._backend.collect(
            case=case, observation=RunObservation(
                trial_no=1, run_id=response.run_id, business_mode=mode,
                http_status=response.http_status, request_id=request_id,
            ),
            fixture_state=self._state,
            before_state=measured_before_state, after_state=after_state,
        )
        return replace(trial, metadata={**trial.metadata, **meta,
                                        "terminal_observation": terminal.status})

    async def _collect(
        self,
        case: EvaluationCase,
        *, project_id: UUID,
        observation: RunObservation,
        request_id: str,
    ) -> TrialArtifact:
        before_state = await self._backend.capture_side_effects(
            project_id=project_id, request_id=request_id,
        )
        after_state = await self._backend.capture_side_effects(
            project_id=project_id, request_id=request_id,
        )
        return await self._backend.collect(
            case=case, observation=observation, fixture_state=self._state,
            before_state=before_state, after_state=after_state,
        )
