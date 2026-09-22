# WS1 Production Bootstrap + Authentication Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V1 API production Runtime Envelope needed for document lifecycle operations so FastAPI owns real API-facing resources, authenticates Bearer JWTs, rebuilds authorization from current PostgreSQL `ProjectMembership` state on every protected request, and never relies on a production `app.state.document_actor` shortcut.

**Architecture:** Keep Task 0–13 modules intact and add a thin API Runtime Envelope. A FastAPI lifespan creates long-lived API resources (`Settings`, PostgreSQL engine/session factory, local object store, RAGFlow HTTP client/adapter, JWT verifier); request-scoped dependencies create one transactional `AsyncSession`, repositories, and application services. JWT establishes only `AuthenticatedIdentity`; `DocumentAccessService` then reloads the requested project's current membership and derives document-operation permissions from the frozen V1 role matrix before constructing the existing `DocumentActor` consumed by Task 6 use cases.

**Tech Stack:** Python 3.12, FastAPI, Pydantic/Pydantic Settings, SQLAlchemy asyncio + asyncpg, PostgreSQL, httpx, existing `JwtIdentityVerifier`, existing Task 6 document use cases, `LocalFileObjectStoreAdapter`, `RagflowAdapter`, pytest/pytest-asyncio, Ruff, MyPy.

**Spec:** `docs/superpowers/specs/2026-09-12-v1-completion-design.md`

## Source-of-Truth Preflight

The uploaded source snapshot used to write this plan does **not** contain `.git/`; therefore no `git log --oneline -15` or `git status` evidence is claimed here. Before executing Task 1 in the real worktree, run:

```bash
git status --short --branch
git log --oneline -15
```

Execution must stop if the implementer is not in the intended repository/worktree or if unrelated local changes make the task boundary unsafe. Do not fabricate Git evidence from README status text.

Read before implementation:

```text
docs/superpowers/specs/2026-09-12-v1-completion-design.md
docs/business/v1-scope.md
docs/adr/0004-v1-architecture-lock.md
docs/business/forbidden-claims.md
docs/business/roles-and-permissions.md
README.md
TASK1_README.md
TASK6_README.md
TASK9_README.md
pyproject.toml
src/project_agent/main.py
src/project_agent/config.py
src/project_agent/api/v1/documents.py
src/project_agent/application/services/authorization.py
src/project_agent/infrastructure/auth/jwt.py
src/project_agent/infrastructure/db/session.py
src/project_agent/infrastructure/db/repositories/authorization.py
src/project_agent/infrastructure/db/repositories/documents.py
tests/unit/auth/test_jwt.py
tests/security/test_non_member.py
tests/security/test_cross_client.py
tests/integration/auth/test_authorization_repository.py
tests/integration/api/test_health.py
```

## Global Constraints

- Do not rewrite Task 0–13; add the WS1 Runtime Envelope around existing modules.
- Keep the V1 architecture locked to FastAPI + LangGraph + PostgreSQL + PostgreSQL Job Queue + RAGFlow + `LocalFileObjectStoreAdapter` + `SandboxProjectTrackerAdapter`.
- Do not add Redis, ARQ, Celery, MinIO, a second vector database, multi-Agent orchestration, production Jira/禅道/飞书 writes, SaaS multi-tenancy, Kubernetes, GraphRAG, or RAPTOR.
- WS1 does **not** implement Run/SSE APIs, Worker `EXECUTE_AGENT_RUN`/`RESUME_AGENT_RUN`, a real LLM adapter, QA Graph changes, Issue Graph changes, retrieval changes, metrics, Docker closure, or evaluation.
- JWT is authentication-only. `role`, `project_ids`, document IDs, or any other authorization-like JWT claim must never grant access.
- Every protected document operation must reload current membership from PostgreSQL (or the injected `ProjectAuthorizationRepository` in isolated tests) using the authenticated `sub` and the target `project_id`.
- A membership is active only when `valid_from <= now` and (`valid_to is None` or `now < valid_to`) and the project is not `DELETION_PENDING`/`DELETED`.
- Revoking/expiring membership must take effect on the next request even when the caller reuses an otherwise-valid JWT.
- Production document routes must not read `request.state.document_actor` or `app.state.document_actor`.
- Preserve `create_app()` testability through an injectable runtime factory and standard FastAPI `app.dependency_overrides`; tests must not need live PostgreSQL/RAGFlow merely to exercise app construction or authentication failures.
- Use the existing `DocumentActor` type and existing Task 6 use cases. Do not move document lifecycle business rules into FastAPI routes.
- The production role-to-document-operation matrix for WS1 follows `docs/business/roles-and-permissions.md`:
  - `project_manager`: `upload_document`, `submit_review`, `approve_document`, `publish_document`, `archive_document`;
  - `developer`, `qa`, `implementation`, `support`: `upload_document`, `submit_review`;
  - `viewer`: none of the protected document write operations.
- Existing Task 6 use-case checks remain additional barriers. In particular, `ApproveDocumentUseCase` still requires the actor to be the document owner; WS1 does not weaken that rule.
- An upload payload's `company_id` must equal the company derived from current project membership; request data cannot override membership-derived company scope.
- Missing/malformed/invalid/expired JWT returns HTTP `401` with `WWW-Authenticate: Bearer`; authenticated users lacking current membership or the required project operation return HTTP `403`.
- Unknown document versions return HTTP `404`; authorization failures must not be translated into `404`.
- Request-scoped SQLAlchemy sessions commit after a successful request and roll back the current transaction on exceptions. Existing Task 6 durability barriers that must survive a later provider error (`document_publication_submitted`/failure audit and `DELETE_PENDING`) must explicitly commit before the external failure point via the WS1 commit-barrier port.
- Do not claim PostgreSQL/RAGFlow/live production validation unless the corresponding opt-in live command actually ran and its result is recorded.

## File Map Locked for WS1

### Create

- `src/project_agent/application/services/document_access.py` — current-membership document operation policy and conversion to existing `DocumentActor`.
- `src/project_agent/runtime/__init__.py` — exports the API runtime types/factory.
- `src/project_agent/runtime/api.py` — production API composition root and async resource lifecycle.
- `src/project_agent/api/dependencies.py` — request-scoped runtime, SQLAlchemy session, JWT identity, and authorization dependencies.
- `src/project_agent/application/ports/transaction.py` — minimal commit-barrier protocol needed to preserve existing Task 6 durability semantics under a request-scoped SQLAlchemy session.
- `tests/unit/auth/test_document_access.py` — role/membership/company/project operation-policy tests.
- `tests/unit/runtime/test_api_runtime.py` — production resource construction and lifespan teardown tests.
- `tests/integration/api/test_authentication.py` — HTTP Bearer/JWT behavior tests.
- `tests/integration/api/test_document_authorization.py` — offline document-route authorization tests using injected fakes.
- `tests/integration/api/test_document_auth_postgres.py` — opt-in real PostgreSQL end-to-end authorization/revocation gate.
- `tests/helpers/__init__.py` — test helper package marker.
- `tests/helpers/jwt.py` — deterministic HS256 token builder used by API tests.

### Modify

- `src/project_agent/main.py` — install API lifespan/runtime factory and remove production document actor/service state injection.
- `src/project_agent/api/v1/documents.py` — construct request-scoped production services, require authenticated identity/current membership/operation permission, and pass the derived `DocumentActor` to existing use cases.
- `src/project_agent/application/use_cases/publish_document.py` — accept an optional production commit barrier so submission/failure audits remain durable across provider failures.
- `src/project_agent/application/use_cases/delete_document.py` — accept an optional production commit barrier so `DELETE_PENDING` is durable before provider cleanup.
- `tests/e2e/test_document_lifecycle.py` — prove commit barriers occur before provider failure while retaining existing lifecycle tests.
- `tests/integration/api/test_health.py` — assert health endpoints stay external-service-free with the new lifespan seam.
- `README.md` — replace the Task 9 runtime implication with the accurate WS1 status after gates pass.
- `TASK9_README.md` — record that FastAPI JWT→current-membership wiring is supplied by WS1 and name the new live API gate.

### Explicitly Do Not Modify in WS1

```text
src/project_agent/agent/**
src/project_agent/workers/**
src/project_agent/application/ports/llm.py
src/project_agent/application/services/issue_*.py
src/project_agent/agent/graph.py
src/project_agent/agent/issue_graph.py
migrations/**
compose.yaml
evaluation/**
```

No schema migration is required for WS1.

---

### Task 1: Add Current-Membership Document Operation Authorization

**Files:**
- Create: `src/project_agent/application/services/document_access.py`
- Create: `tests/unit/auth/test_document_access.py`
- Reuse: `src/project_agent/application/services/authorization.py`
- Reuse: `src/project_agent/application/use_cases/upload_document.py`
- Reuse: `tests/fakes/authorization.py`
- Reuse: `tests/fakes/document_repository.py`

**Interfaces:**
- Consumes:
  - `AuthorizationService.authorize_identity(*, identity: AuthenticatedIdentity, project_id: UUID) -> AuthorizedProjectContext`
  - `DocumentWorkflowRepository.get_version(version_id: UUID) -> DocumentVersionRecord`
  - existing `DocumentActor(user_id: UUID, permissions: frozenset[str])`
- Produces:

```python
class DocumentOperation(StrEnum):
    UPLOAD = "upload_document"
    SUBMIT_REVIEW = "submit_review"
    APPROVE = "approve_document"
    PUBLISH = "publish_document"
    ARCHIVE = "archive_document"


@dataclass(frozen=True, slots=True)
class AuthorizedDocumentActor:
    context: AuthorizedProjectContext
    actor: DocumentActor


class DocumentAccessService:
    def __init__(
        self,
        *,
        authorization: AuthorizationService,
        repository: DocumentWorkflowRepository,
    ) -> None: ...

    async def authorize_project_operation(
        self,
        *,
        identity: AuthenticatedIdentity,
        project_id: UUID,
        operation: DocumentOperation,
        expected_company_id: UUID | None = None,
    ) -> AuthorizedDocumentActor: ...

    async def authorize_version_operation(
        self,
        *,
        identity: AuthenticatedIdentity,
        version_id: UUID,
        operation: DocumentOperation,
    ) -> AuthorizedDocumentActor: ...
```

The implementation must derive permissions only from `AuthorizedProjectContext.scope.role_ids`, which itself comes from current membership. It must reject unknown/multiple role values rather than guessing. For a valid single `ProjectRole`, construct the complete document permission set for that role, require `operation.value` to be present, and return an existing `DocumentActor` with the authenticated `user_id` plus that server-derived permission set.

- [x] **Step 1: Write the failing unit tests for role-derived document permissions**

Create `tests/unit/auth/test_document_access.py` with fixed IDs/time and tests equivalent to:

```python
@pytest.mark.asyncio
async def test_developer_gets_only_member_document_write_permissions() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = membership(ProjectRole.DEVELOPER)
    service = DocumentAccessService(
        authorization=AuthorizationService(repo, clock=lambda: NOW),
        repository=InMemoryDocumentWorkflowRepository(),
    )

    allowed = await service.authorize_project_operation(
        identity=AuthenticatedIdentity(user_id=USER),
        project_id=PROJECT,
        operation=DocumentOperation.UPLOAD,
        expected_company_id=COMPANY,
    )

    assert allowed.actor.user_id == USER
    assert allowed.actor.permissions == frozenset({"upload_document", "submit_review"})


@pytest.mark.asyncio
async def test_viewer_cannot_upload_even_if_identity_is_authenticated() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = membership(ProjectRole.VIEWER)
    service = DocumentAccessService(
        authorization=AuthorizationService(repo, clock=lambda: NOW),
        repository=InMemoryDocumentWorkflowRepository(),
    )

    with pytest.raises(AuthorizationDenied, match="upload_document"):
        await service.authorize_project_operation(
            identity=AuthenticatedIdentity(user_id=USER),
            project_id=PROJECT,
            operation=DocumentOperation.UPLOAD,
            expected_company_id=COMPANY,
        )


@pytest.mark.asyncio
async def test_project_manager_has_publish_approve_and_archive_permissions() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = membership(ProjectRole.PROJECT_MANAGER)
    service = DocumentAccessService(
        authorization=AuthorizationService(repo, clock=lambda: NOW),
        repository=InMemoryDocumentWorkflowRepository(),
    )

    allowed = await service.authorize_project_operation(
        identity=AuthenticatedIdentity(user_id=USER),
        project_id=PROJECT,
        operation=DocumentOperation.PUBLISH,
        expected_company_id=COMPANY,
    )

    assert {"approve_document", "publish_document", "archive_document"} <= allowed.actor.permissions
```

Also include exact tests for:

```text
- developer denied `approve_document`;
- payload `company_id` different from membership-derived company → AuthorizationDenied;
- no active membership → AuthorizationDenied;
- same AuthenticatedIdentity after fake membership valid_to is moved to NOW → AuthorizationDenied;
- authorize_version_operation loads the version's true project/company and denies a user who belongs only to another project.
```

- [x] **Step 2: Run the new tests and verify RED**

Run:

```bash
uv run pytest tests/unit/auth/test_document_access.py -v
```

Expected: collection/import failure because `project_agent.application.services.document_access` does not exist.

- [x] **Step 3: Implement the minimal document access policy**

Create `src/project_agent/application/services/document_access.py` with a constant role matrix exactly matching the Global Constraints and the interfaces above. The central logic must be equivalent to:

```python
_ROLE_DOCUMENT_PERMISSIONS: dict[ProjectRole, frozenset[str]] = {
    ProjectRole.PROJECT_MANAGER: frozenset(
        {
            DocumentOperation.UPLOAD.value,
            DocumentOperation.SUBMIT_REVIEW.value,
            DocumentOperation.APPROVE.value,
            DocumentOperation.PUBLISH.value,
            DocumentOperation.ARCHIVE.value,
        }
    ),
    ProjectRole.DEVELOPER: frozenset(
        {DocumentOperation.UPLOAD.value, DocumentOperation.SUBMIT_REVIEW.value}
    ),
    ProjectRole.QA: frozenset(
        {DocumentOperation.UPLOAD.value, DocumentOperation.SUBMIT_REVIEW.value}
    ),
    ProjectRole.IMPLEMENTATION: frozenset(
        {DocumentOperation.UPLOAD.value, DocumentOperation.SUBMIT_REVIEW.value}
    ),
    ProjectRole.SUPPORT: frozenset(
        {DocumentOperation.UPLOAD.value, DocumentOperation.SUBMIT_REVIEW.value}
    ),
    ProjectRole.VIEWER: frozenset(),
}
```

`authorize_project_operation()` must:

```text
1. call AuthorizationService.authorize_identity() for this request;
2. if expected_company_id is supplied, require equality with context.scope.company_id;
3. require exactly one role in context.scope.role_ids;
4. convert it to ProjectRole; unknown value → AuthorizationDenied;
5. derive permissions from the frozen map;
6. require operation.value in permissions;
7. return AuthorizedDocumentActor(context, DocumentActor(...)).
```

`authorize_version_operation()` must call `repository.get_version(version_id)` to obtain the authoritative `project_id` and `company_id`, then delegate to `authorize_project_operation()` with those values. It must not accept a caller-supplied project/company for an existing version.

- [x] **Step 4: Run Task 1 tests and existing authorization/security regression**

Run:

```bash
uv run pytest \
  tests/unit/auth/test_document_access.py \
  tests/unit/auth/test_jwt.py \
  tests/security/test_non_member.py \
  tests/security/test_cross_client.py \
  -v
```

Expected: all selected offline tests PASS.

- [x] **Step 5: Run static checks for the new application service**

Run:

```bash
uv run ruff check src/project_agent/application/services/document_access.py tests/unit/auth/test_document_access.py
uv run mypy src/project_agent/application/services/document_access.py
```

Expected: both commands PASS with zero errors.

- [x] **Step 6: Commit Task 1**

```bash
git add \
  src/project_agent/application/services/document_access.py \
  tests/unit/auth/test_document_access.py
git commit -m "feat(auth): add document operation access policy"
```

**Task 1 acceptance:** The server can convert a trusted user identity plus **current** project membership into an operation-specific existing `DocumentActor`; viewer/non-member/expired/wrong-project/wrong-company cases are denied without reading authorization from JWT claims.

---

### Task 2: Add the API Production Composition Root and FastAPI Lifespan

**Files:**
- Create: `src/project_agent/runtime/__init__.py`
- Create: `src/project_agent/runtime/api.py`
- Create: `tests/unit/runtime/test_api_runtime.py`
- Modify: `src/project_agent/main.py`
- Modify: `tests/integration/api/test_health.py`

**Interfaces:**
- Consumes:
  - `create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine`
  - `create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]`
  - `LocalFileObjectStoreAdapter(root: Path | str)`
  - `RagflowAdapter.from_http_client(...) -> RagflowAdapter`
  - `JwtIdentityVerifier(...)`
- Produces:

```python
class DocumentKnowledgePort(KnowledgeIngestionPort, KnowledgeAdminPort, Protocol):
    """Combined Task 6 knowledge boundary used by publish/delete routes."""


@dataclass(slots=True)
class ApiRuntime:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    object_store: ObjectStorePort
    knowledge: DocumentKnowledgePort
    jwt_verifier: JwtIdentityVerifier


ApiRuntimeFactory: TypeAlias = Callable[
    [Settings],
    AbstractAsyncContextManager[ApiRuntime],
]


@asynccontextmanager
async def build_api_runtime(settings: Settings) -> AsyncIterator[ApiRuntime]: ...
```

`create_app` becomes:

```python
def create_app(
    settings: Settings | None = None,
    *,
    runtime_factory: ApiRuntimeFactory = build_api_runtime,
) -> FastAPI: ...
```

The module-level `app = create_app()` remains valid and must not instantiate `Settings()` or contact external services at import time. `Settings()` is resolved when the app lifespan starts.

- [x] **Step 1: Write failing runtime/lifespan tests**

Create `tests/unit/runtime/test_api_runtime.py` covering both actual object construction (without network calls) and injected lifecycle behavior.

Actual construction test:

```python
@pytest.mark.asyncio
async def test_build_api_runtime_constructs_api_resources_without_network(tmp_path: Path) -> None:
    settings = make_settings(
        database_url="postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent",
        local_storage_root=tmp_path,
    )

    async with build_api_runtime(settings) as runtime:
        assert runtime.settings is settings
        assert runtime.engine.url.render_as_string(hide_password=False) == settings.database_url
        assert isinstance(runtime.object_store, LocalFileObjectStoreAdapter)
        assert isinstance(runtime.knowledge, RagflowAdapter)
        assert isinstance(runtime.jwt_verifier, JwtIdentityVerifier)
```

This test must not execute a SQL statement or RAGFlow request; SQLAlchemy engine creation and `httpx.AsyncClient` creation are lazy with respect to those external services.

Injected lifespan test must use a fake `runtime_factory` context manager with `entered`/`exited` booleans and yield a real `ApiRuntime` value whose `object_store`/`knowledge` are test fakes. Assert that `TestClient(create_app(settings, runtime_factory=fake_factory))` enters once and exits once.

Modify `tests/integration/api/test_health.py` so `_test_settings()` uses a syntactically valid PostgreSQL async URL and a `tmp_path` local root (not `sqlite+aiosqlite`, because WS1 production bootstrap intentionally constructs the real PostgreSQL engine). Keep the existing assertions that `/live` and `/ready` succeed without contacting PostgreSQL/RAGFlow/LLM. Add a regression proving invalid environment configuration still permits `/live` and makes `/ready` return `503` without entering the production runtime factory; this preserves Task 1 readiness semantics rather than turning a configuration error into an import/startup crash.

- [x] **Step 2: Run the new runtime tests and verify RED**

Run:

```bash
uv run pytest \
  tests/unit/runtime/test_api_runtime.py \
  tests/integration/api/test_health.py \
  -v
```

Expected: FAIL because `project_agent.runtime.api`, `ApiRuntime`, `build_api_runtime`, and the `runtime_factory` `create_app` argument do not exist yet.

- [x] **Step 3: Implement `build_api_runtime()`**

`src/project_agent/runtime/api.py` must construct only API-facing WS1 resources:

```python
@asynccontextmanager
async def build_api_runtime(settings: Settings) -> AsyncIterator[ApiRuntime]:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    object_store = LocalFileObjectStoreAdapter(settings.local_storage_root)
    jwt_verifier = JwtIdentityVerifier(
        secret=settings.jwt_hs256_secret.get_secret_value(),
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        leeway_seconds=settings.jwt_leeway_seconds,
    )

    async with httpx.AsyncClient(
        base_url=settings.ragflow_base_url,
        timeout=settings.ragflow_request_timeout_seconds,
    ) as ragflow_http:
        knowledge = RagflowAdapter.from_http_client(
            ragflow_http,
            api_key=settings.ragflow_api_key.get_secret_value(),
            object_store=object_store,
            embedding_model=settings.ragflow_embedding_model,
            chunk_method=settings.ragflow_chunk_method,
            retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
        )
        try:
            yield ApiRuntime(
                settings=settings,
                engine=engine,
                session_factory=session_factory,
                object_store=object_store,
                knowledge=knowledge,
                jwt_verifier=jwt_verifier,
            )
        finally:
            await engine.dispose()
```

Do not create a Worker, Job handler registry, LLM client, LangGraph graph/checkpointer, Run Orchestrator, or Sandbox write service in WS1.

- [x] **Step 4: Replace app-state test shortcuts with the runtime lifespan seam in `create_app()`**

Modify `src/project_agent/main.py` so its lifespan:

```text
1. if an explicit Settings object was passed, use it; otherwise attempt Settings() at startup;
2. if Settings() raises pydantic.ValidationError, do not enter runtime_factory, leave runtime unavailable, yield so /live remains live and /ready can return the existing 503 invalid-configuration response;
3. for valid settings, enter runtime_factory(resolved_settings);
4. store only app.state.settings and app.state.runtime for infrastructure access;
5. yield control to FastAPI;
6. let the runtime context manager close the HTTP client/engine;
7. remove the old document_api_services and document_actor create_app arguments and app-state assignments.
```

`app.state.runtime` is a composition resource, not an authenticated actor. No per-user identity may be stored on application state.

- [x] **Step 5: Run Task 2 tests**

Run:

```bash
uv run pytest \
  tests/unit/runtime/test_api_runtime.py \
  tests/integration/api/test_health.py \
  -v
uv run ruff check src/project_agent/runtime src/project_agent/main.py tests/unit/runtime tests/integration/api/test_health.py
uv run mypy src/project_agent/runtime src/project_agent/main.py
```

Expected: all commands PASS. `/live` and `/ready` still require no live PostgreSQL/RAGFlow/LLM calls.

- [x] **Step 6: Commit Task 2**

```bash
git add \
  src/project_agent/runtime/__init__.py \
  src/project_agent/runtime/api.py \
  src/project_agent/main.py \
  tests/unit/runtime/test_api_runtime.py \
  tests/integration/api/test_health.py
git commit -m "feat(runtime): add API production bootstrap"
```

**Task 2 acceptance:** `create_app()` has a real async production resource lifecycle, import-time construction remains side-effect free, tests can inject a runtime factory, and no WS2+ runtime is accidentally composed.

---

### Task 3: Add Request-Scoped PostgreSQL and JWT FastAPI Dependencies

**Files:**
- Create: `src/project_agent/api/dependencies.py`
- Create: `tests/helpers/__init__.py`
- Create: `tests/helpers/jwt.py`
- Create: `tests/integration/api/test_authentication.py`
- Reuse: `src/project_agent/runtime/api.py`
- Reuse: `src/project_agent/infrastructure/db/repositories/authorization.py`

**Interfaces:**
- Consumes: `ApiRuntime`, `AuthenticatedIdentity`, `AuthorizationService`, `SqlAlchemyProjectAuthorizationRepository`, `JwtIdentityError`.
- Produces:

```python
def get_api_runtime(request: Request) -> ApiRuntime: ...


async def get_db_session(
    runtime: Annotated[ApiRuntime, Depends(get_api_runtime)],
) -> AsyncIterator[AsyncSession]: ...


def get_authenticated_identity(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(HTTPBearer(auto_error=False)),
    ],
    runtime: Annotated[ApiRuntime, Depends(get_api_runtime)],
) -> AuthenticatedIdentity: ...


def get_authorization_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthorizationService: ...
```

`get_db_session()` must create one session from `runtime.session_factory`, yield it, commit only after the route/dependencies succeed, and rollback on any `BaseException` before re-raising.

`get_authenticated_identity()` must:

```text
missing Bearer credentials                  -> 401 + WWW-Authenticate: Bearer
wrong auth scheme / malformed credentials   -> 401 + WWW-Authenticate: Bearer
JwtIdentityError from existing verifier     -> 401 + WWW-Authenticate: Bearer
valid token                                 -> AuthenticatedIdentity(user_id=<JWT sub>)
```

It must call `runtime.jwt_verifier.verify(credentials.credentials)` and must not deserialize or trust authorization claims itself.

- [x] **Step 1: Add deterministic JWT test helper and failing API authentication tests**

Create `tests/helpers/jwt.py`:

```python
def make_hs256_token(
    *,
    user_id: UUID,
    secret: str,
    issuer: str,
    audience: str,
    expires_at: datetime,
    not_before: datetime | None = None,
    extra_claims: Mapping[str, object] | None = None,
) -> str:
    """Build a deterministic HS256 token for tests only."""
```

The helper must use stdlib `base64`, `hashlib`, `hmac`, and `json`; it must not add a JWT package dependency.

Create `tests/integration/api/test_authentication.py` with a tiny test-only protected router or endpoint that depends on `get_authenticated_identity` and returns only `{"user_id": str(identity.user_id)}`. Use `create_app(settings, runtime_factory=fake_runtime_factory)` and attach the test router before opening `TestClient`. The fake factory must yield an actual `ApiRuntime`; use a lazy PostgreSQL `AsyncEngine`/session factory plus `InMemoryObjectStore`, `FakeKnowledgePort`, and the real `JwtIdentityVerifier`, then dispose the lazy engine in the fake factory's `finally` block. This keeps `get_api_runtime()`'s concrete type check valid in tests.

Required tests:

```text
GET protected endpoint without Authorization header -> 401 + Bearer challenge
invalid signature -> 401 + Bearer challenge
expired token -> 401 + Bearer challenge
valid token with forged role/project claims -> 200 and response contains only user_id
```

The valid-token test must add forged claims such as:

```python
extra_claims={
    "role": "project_manager",
    "project_ids": [str(uuid4())],
}
```

and prove those values do not appear in the returned authentication object/response.

- [x] **Step 2: Run authentication tests and verify RED**

Run:

```bash
uv run pytest tests/integration/api/test_authentication.py -v
```

Expected: FAIL because `project_agent.api.dependencies` does not exist.

- [x] **Step 3: Implement the FastAPI runtime/session/authentication dependencies**

Create `src/project_agent/api/dependencies.py` with the exact interfaces above. `get_api_runtime()` returns `request.app.state.runtime` only when it is an `ApiRuntime`; otherwise raise HTTP `503` with `detail="API runtime is not configured"`.

Implement transaction semantics explicitly:

```python
async with runtime.session_factory() as session:
    try:
        yield session
    except BaseException:
        await session.rollback()
        raise
    else:
        await session.commit()
```

Construct `AuthorizationService` from a new `SqlAlchemyProjectAuthorizationRepository(session)` for each request. Do not cache an authorization context across requests.

- [x] **Step 4: Run Task 3 tests and static checks**

Run:

```bash
uv run pytest \
  tests/integration/api/test_authentication.py \
  tests/unit/auth/test_jwt.py \
  -v
uv run ruff check src/project_agent/api/dependencies.py tests/helpers tests/integration/api/test_authentication.py
uv run mypy src/project_agent/api/dependencies.py
```

Expected: PASS.

- [x] **Step 5: Commit Task 3**

```bash
git add \
  src/project_agent/api/dependencies.py \
  tests/helpers/__init__.py \
  tests/helpers/jwt.py \
  tests/integration/api/test_authentication.py
git commit -m "feat(api): add JWT and database dependencies"
```

**Task 3 acceptance:** FastAPI has a standard Bearer JWT dependency, request-scoped transactional PostgreSQL session, and request-scoped `AuthorizationService`; authentication returns only trusted user identity and is independently overrideable in tests.

---

### Task 4: Wire Document Routes to Current Membership and Prove Revocation End-to-End

**Files:**
- Create: `src/project_agent/application/ports/transaction.py`
- Modify: `src/project_agent/application/use_cases/publish_document.py`
- Modify: `src/project_agent/application/use_cases/delete_document.py`
- Modify: `src/project_agent/api/v1/documents.py`
- Modify: `tests/e2e/test_document_lifecycle.py`
- Create: `tests/integration/api/test_document_authorization.py`
- Create: `tests/integration/api/test_document_auth_postgres.py`
- Modify: `README.md`
- Modify: `TASK9_README.md`
- Reuse: `src/project_agent/api/dependencies.py`
- Reuse: `src/project_agent/application/services/document_access.py`
- Reuse: existing Task 6 use cases and test fakes

**Interfaces:**
- Consumes:
  - `get_api_runtime()`
  - `get_db_session()`
  - `get_authenticated_identity()`
  - `get_authorization_service()`
  - `DocumentAccessService.authorize_project_operation()`
  - `DocumentAccessService.authorize_version_operation()`
- Produces a minimal transaction boundary used only where existing Task 6 semantics require durability before a later provider call:

```python
@runtime_checkable
class TransactionCommitPort(Protocol):
    async def commit(self) -> None: ...
```

`PublishDocumentUseCase.__init__` becomes:

```python
def __init__(
    self,
    repository: DocumentWorkflowRepository,
    knowledge: KnowledgeIngestionPort,
    *,
    commit_barrier: TransactionCommitPort | None = None,
) -> None: ...
```

`DeleteDocumentUseCase.__init__` becomes:

```python
def __init__(
    self,
    repository: DocumentWorkflowRepository,
    knowledge: KnowledgeAdminPort,
    *,
    commit_barrier: TransactionCommitPort | None = None,
) -> None: ...
```

The default `None` preserves current isolated/fake use-case construction. Production API composition passes the request `AsyncSession`, whose `commit()` satisfies the protocol structurally. This is not a new lifecycle feature: it makes the existing Task 6 durability rules true with real SQLAlchemy transactions.

- Produces two overrideable FastAPI dependencies in `documents.py`:

```python
def get_document_api_services(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    runtime: Annotated[ApiRuntime, Depends(get_api_runtime)],
) -> DocumentApiServices: ...


def get_document_access_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> DocumentAccessService: ...
```

`get_document_api_services()` must create one `SqlAlchemyDocumentWorkflowRepository(session)` and reuse that same repository instance for all five Task 6 use cases for the request:

```python
DocumentApiServices(
    upload=UploadDocumentUseCase(repository, runtime.object_store),
    submit_review=SubmitDocumentReviewUseCase(repository),
    approve=ApproveDocumentUseCase(repository),
    publish=PublishDocumentUseCase(
        repository, runtime.knowledge, commit_barrier=session
    ),
    delete=DeleteDocumentUseCase(
        repository, runtime.knowledge, commit_barrier=session
    ),
)
```

`get_document_access_service()` must create a `SqlAlchemyDocumentWorkflowRepository(session)` backed by the same request-cached `AsyncSession` and combine it with the request-scoped `AuthorizationService`.

- [x] **Step 1: Write the failing offline and live document authorization tests before changing routes**

Create `tests/integration/api/test_document_authorization.py`. Build an app with an injected fake runtime factory that yields a real `ApiRuntime` with the real `JwtIdentityVerifier`, and override `get_document_api_services` plus `get_document_access_service` to use:

```text
FakeProjectAuthorizationRepository
InMemoryDocumentWorkflowRepository
InMemoryObjectStore
FakeKnowledgePort
AuthorizationService(clock=lambda: NOW)
DocumentAccessService
```

Before the HTTP cases, add two RED regressions to `tests/e2e/test_document_lifecycle.py` for the production transaction boundary:

```text
A. delete: a commit spy must have exactly one commit before the fake knowledge adapter raises during delete; after the exception the in-memory record remains DELETE_PENDING.
B. publish failure: the commit spy must be at one before `get_ingestion_status()` returns FAILED (submission audit durable), and at two after `DocumentPublishFailed` is raised (failure audit durable).
```

Use a test-local `CommitSpy` with `async def commit()` and test-local `FakeKnowledgePort` subclasses/callbacks that assert the commit count at the external failure/status boundary. These tests initially fail because the Task 6 constructors do not accept `commit_barrier`.

Required offline HTTP tests:

```text
1. missing JWT on POST /api/v1/documents -> 401; no draft created.
2. valid JWT whose payload forges role=project_manager, but DB/fake membership is viewer -> 403; no draft created.
3. valid JWT + current developer membership + matching company/project -> 201 DRAFT; created_by equals JWT sub.
4. valid JWT + membership only in Project Alpha + upload body for Project Beta -> 403.
5. valid JWT + current developer membership but body company_id differs from membership company -> 403.
6. same valid JWT succeeds once; after the fake membership valid_to is changed to NOW, the next request -> 403 and creates no second draft.
7. developer calling an existing version's /publish endpoint -> 403 before FakeKnowledgePort ingest is called.
8. project_manager calling /publish passes API operation authorization and the existing Task 6 publish use case executes successfully.
9. unknown document version on a version route -> 404, while a known version without current membership -> 403.
```

For case 8, seed an `APPROVED` version in `InMemoryDocumentWorkflowRepository`, bind that project to `ks-alpha`, configure `FakeKnowledgePort` to return `SUCCEEDED`, and give the authenticated user a current `project_manager` membership. Assert HTTP 200 with `status=PUBLISHED` and exactly one fake ingestion request. Do not alter the Task 6 publish use case.

Create `tests/integration/api/test_document_auth_postgres.py` in the same RED step, with module-level opt-in:

```python
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL document auth integration",
)
```

The live test must use the real production path and no fake authorization repository:

```text
HTTP Authorization: Bearer <JWT>
→ get_authenticated_identity
→ SqlAlchemyProjectAuthorizationRepository
→ AuthorizationService
→ DocumentAccessService
→ SqlAlchemyDocumentWorkflowRepository
→ UploadDocumentUseCase
→ LocalFileObjectStoreAdapter
→ PostgreSQL commit
```

Seed a unique `ClientModel`, `ProjectModel`, and active `ProjectMembershipModel(role="developer")` in the migrated `DATABASE_URL`. Build real `Settings` with `LOCAL_STORAGE_ROOT=tmp_path`, a non-network test RAGFlow URL/key, and a fixed >=32-byte JWT secret. Create one unexpired JWT for the seeded user; include forged `role="project_manager"` if desired to prove the claim is ignored.

The first real request must be:

```http
POST /api/v1/documents
Authorization: Bearer <same-token-used-again-later>
```

with matching `company_id`/`project_id`, valid document metadata, and a small base64 payload. Assert:

```text
status = 201
response status = DRAFT
exactly one DocumentVersion exists for the seeded project
created_by = JWT sub
```

Then, in a separate committed SQLAlchemy session, set:

```python
membership.valid_to = datetime.now(UTC) - timedelta(seconds=1)
```

Reuse the **same unexpired JWT** for a second otherwise-valid upload and assert:

```text
status = 403
DocumentVersion count for the project is still exactly one
exactly one document_metadata_confirmed audit exists for the project
```

The live test must clean up explicitly in `finally`: delete `AuditLogModel` rows for the seeded project first, delete the seeded `ProjectModel` so its project/document/membership cascades run, then delete the seeded `ClientModel`; commit and dispose the cleanup engine.

- [x] **Step 2: Run the new tests and verify RED**

Always run the new RED tests together:

```bash
uv run pytest \
  tests/e2e/test_document_lifecycle.py \
  tests/integration/api/test_document_authorization.py \
  -v
```

Expected: FAIL for both newly added concerns: the Task 6 use-case constructors do not yet accept `commit_barrier`, and document routes still depend on `app.state.document_actor`/`app.state.document_api_services` instead of JWT/current-membership dependencies. Existing pre-WS1 lifecycle cases should remain green.

If PostgreSQL is available, also run the live module **before implementation**:

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
uv run pytest tests/integration/api/test_document_auth_postgres.py -v
```

Expected before route implementation: FAIL on the protected API contract. If PostgreSQL is not available, run without the flag and record the explicit SKIP; that SKIP is not live evidence and does not replace the mandatory RED offline test.

- [x] **Step 3: Add the minimal Task 6 commit barrier required by production transactions**

Create `src/project_agent/application/ports/transaction.py` with `TransactionCommitPort`. Modify `PublishDocumentUseCase` and `DeleteDocumentUseCase` only as follows:

```text
PublishDocumentUseCase:
1. after `document_publication_submitted` audit is flushed, call commit_barrier.commit() when configured, before polling/finalizing provider state;
2. if provider status is FAILED, add `document_publication_failed`, call commit_barrier.commit() when configured, then raise the existing DocumentPublishFailed;
3. do not add a commit between complete_publication() and document_published audit; they remain one final request transaction.

DeleteDocumentUseCase:
1. transition to DELETE_PENDING;
2. add document_delete_pending audit;
3. call commit_barrier.commit() when configured;
4. only then invoke knowledge.delete_document();
5. preserve the existing behavior of surfacing provider cleanup failure to the caller.
```

Do not add commits to upload/submit-review/approve; those remain ordinary request transactions. Do not add retries or Worker jobs in WS1.

- [x] **Step 4: Replace the document service app-state shortcut with request-scoped production construction**

Modify `src/project_agent/api/v1/documents.py`:

```text
- keep DocumentApiServices as the small route-facing use-case bundle;
- delete _services(request) that reads app.state.document_api_services;
- delete _actor(request) entirely;
- add get_document_api_services() and get_document_access_service() with the exact signatures above;
- keep these functions importable so tests can use app.dependency_overrides.
```

No route may read `request.state.document_actor`, `app.state.document_actor`, or an actor/role from request JSON.

- [x] **Step 5: Add membership/operation authorization to every document route**

Use the following exact mapping:

```text
POST   /api/v1/documents                         -> DocumentOperation.UPLOAD
POST   /api/v1/documents/{id}/submit-review      -> DocumentOperation.SUBMIT_REVIEW
POST   /api/v1/documents/{id}/approve            -> DocumentOperation.APPROVE
POST   /api/v1/documents/{id}/publish            -> DocumentOperation.PUBLISH
DELETE /api/v1/documents/{id}                    -> DocumentOperation.ARCHIVE
```

Every route must accept:

```python
identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)]
access: Annotated[DocumentAccessService, Depends(get_document_access_service)]
services: Annotated[DocumentApiServices, Depends(get_document_api_services)]
```

Upload must call:

```python
authorized = await access.authorize_project_operation(
    identity=identity,
    project_id=payload.project_id,
    operation=DocumentOperation.UPLOAD,
    expected_company_id=payload.company_id,
)
```

and pass only `authorized.actor` into `UploadDocumentCommand.actor`.

Version routes must call:

```python
authorized = await access.authorize_version_operation(
    identity=identity,
    version_id=version_id,
    operation=<mapped operation>,
)
```

and pass only `authorized.actor` to the existing use case.

HTTP mapping in this module must be explicit:

```text
AuthorizationDenied                     -> 403
DocumentPermissionDenied                -> 403
LookupError/KeyError from version lookup -> 404
DocumentPublishPending                  -> existing pending response
DocumentPublishFailed                   -> existing 502 response
```

Do not catch generic `Exception`.

- [x] **Step 6: Run the offline document/auth/lifecycle GREEN gate**

Run:

```bash
uv run pytest \
  tests/integration/api/test_authentication.py \
  tests/integration/api/test_document_authorization.py \
  tests/e2e/test_document_lifecycle.py \
  tests/security/test_non_member.py \
  tests/security/test_cross_client.py \
  -v
```

Expected: all PASS.

- [x] **Step 7: Run the real PostgreSQL revocation GREEN gate**

With the repository migrations applied to the test PostgreSQL instance:

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

uv run pytest \
  tests/integration/auth/test_authorization_repository.py \
  tests/integration/api/test_document_auth_postgres.py \
  -v
```

Expected: both modules PASS with **0 skipped tests**. This is the WS1 live gate proving that current PostgreSQL membership is re-read and the same still-valid JWT cannot bypass revocation.

If no PostgreSQL instance is available during implementation, the commit may still be prepared after all offline gates pass, but documentation must leave the live PostgreSQL API gate `PENDING`; WS1 must not be called live-verified until this command is run successfully.

- [x] **Step 8: Update status documentation without overstating evidence**

Modify `README.md` and `TASK9_README.md` to distinguish exactly:

```text
Task 9 authorization primitives      : implemented
WS1 FastAPI auth/runtime wiring       : implemented
WS1 offline gate                     : PASS only if Step 6 actually passed
WS1 live PostgreSQL API gate         : PASS only if Step 7 actually ran with 0 skip; otherwise PENDING
```

Do not state that RAGFlow live publication, Worker, Run API, LLM, QA Graph, Issue Graph, Docker, metrics, or evaluation are production-complete because WS1 does not validate them.

- [ ] **Step 9: Run static and repository regression gates**

Run:

```bash
uv run ruff check \
  src/project_agent/application/ports/transaction.py \
  src/project_agent/application/use_cases/publish_document.py \
  src/project_agent/application/use_cases/delete_document.py \
  src/project_agent/api/v1/documents.py \
  tests/e2e/test_document_lifecycle.py \
  tests/integration/api/test_document_authorization.py \
  tests/integration/api/test_document_auth_postgres.py
uv run mypy \
  src/project_agent/application/ports/transaction.py \
  src/project_agent/application/use_cases/publish_document.py \
  src/project_agent/application/use_cases/delete_document.py \
  src/project_agent/api/v1/documents.py

uv run ruff check src tests
uv run mypy src
python scripts/run_checks.py
git diff --check
```

Expected: all enabled gates PASS. Environment-gated PostgreSQL/RAGFlow tests may skip only for their documented opt-in reason; a skip must not be reported as live validation.

- [x] **Step 10: Verify WS1 scope isolation before commit**

Run:

```bash
git status --short
git diff --name-only HEAD
```

The WS1 Task 4 diff must contain only the files listed under Task 4. It must not contain changes under:

```text
src/project_agent/agent/
src/project_agent/workers/
migrations/
evaluation/
compose.yaml
```

Also run:

```bash
rg -n "EXECUTE_AGENT_RUN|RESUME_AGENT_RUN|/api/v1/runs|StructuredLLM|prometheus|evaluation" \
  src/project_agent/runtime \
  src/project_agent/api/dependencies.py \
  src/project_agent/api/v1/documents.py
```

Expected: no WS2+ implementation symbols are introduced by the new WS1 files. References in comments that explicitly describe prohibited scope should be reviewed manually rather than treated as implementation.

- [x] **Step 11: Commit Task 4**

```bash
git add \
  src/project_agent/application/ports/transaction.py \
  src/project_agent/application/use_cases/publish_document.py \
  src/project_agent/application/use_cases/delete_document.py \
  src/project_agent/api/v1/documents.py \
  tests/e2e/test_document_lifecycle.py \
  tests/integration/api/test_document_authorization.py \
  tests/integration/api/test_document_auth_postgres.py \
  README.md \
  TASK9_README.md
git commit -m "feat(api): wire current membership document authorization"
```

**Task 4 acceptance:** All document write endpoints require Bearer authentication, authorize the target project/operation from current membership, reject forged JWT authorization claims, and feed existing Task 6 use cases a server-derived `DocumentActor`. Existing Task 6 `DELETE_PENDING` and publication-audit durability semantics survive later provider failures under the real request-scoped SQLAlchemy transaction model. A real migrated PostgreSQL gate proves that the same valid JWT is rejected immediately after membership revocation with no second document/audit side effect. No production actor/service shortcut remains on FastAPI app state.

---

## WS1 Final Acceptance Gate

After all four task commits, run this from the real worktree:

```bash
git status --short --branch
git log --oneline -10

uv run pytest \
  tests/unit/auth \
  tests/unit/runtime \
  tests/integration/api \
  tests/security/test_non_member.py \
  tests/security/test_cross_client.py \
  tests/e2e/test_document_lifecycle.py \
  -v

uv run ruff check src tests
uv run mypy src
python scripts/run_checks.py
git diff --check
```

If PostgreSQL is available, additionally require:

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
uv run pytest \
  tests/integration/auth/test_authorization_repository.py \
  tests/integration/api/test_document_auth_postgres.py \
  -v
```

WS1 is accepted only when all of the following are true:

```text
[x] create_app() remains import-safe and testable through runtime_factory/dependency overrides.
[x] FastAPI lifespan constructs and closes API-facing production resources.
[x] One request uses one transactional AsyncSession for authorization/document repositories.
[x] Missing/invalid/expired Bearer JWT -> 401 + Bearer challenge.
[x] JWT output contains only user identity; forged role/project claims grant nothing.
[x] Current PostgreSQL membership is loaded for every protected document request.
[x] Viewer/non-member/expired/revoked/wrong-project/wrong-company access -> 403.
[x] Same still-valid JWT is denied on the request immediately after membership revocation.
[x] DocumentActor is built server-side from authenticated user + current membership-derived permissions.
[x] app.state.document_actor and request.state.document_actor are absent from production document routing.
[x] Existing Task 6 document lifecycle tests remain green.
[x] No Run API, worker execute/resume handler, real LLM, QA/Issue Graph change, observability, Docker, or evaluation code is introduced.
[x] No prohibited architecture component is added.
[ ] README/TASK9 claims match evidence actually produced by the executed gates.
```

## WS1 Completion Evidence — 2026-09-14

**Current status:** Implementation complete and core WS1 verification gates PASS. Final repository/documentation wrap-up remains before declaring the plan fully closed.

### Verified gates

- [x] `ruff check src tests` — PASS on the server.
- [x] `mypy src` — PASS on the server.
- [x] `python -m pytest -q` — PASS on the server.
- [x] WS1 live PostgreSQL authorization/revocation gate — PASS with **2 passed, 0 failed, 0 skipped**.

Live PostgreSQL command executed:

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

python -m pytest \
  tests/integration/auth/test_authorization_repository.py \
  tests/integration/api/test_document_auth_postgres.py \
  -v
```

Observed result:

```text
tests/integration/auth/test_authorization_repository.py::test_repository_returns_only_active_membership_published_versions_and_spaces PASSED
tests/integration/api/test_document_auth_postgres.py::test_same_valid_jwt_is_rejected_after_postgres_membership_revocation PASSED

2 passed in 1.19s
```

This closes the previously pending live WS1 security gate: the same still-valid JWT is rejected immediately after the backing PostgreSQL `ProjectMembership` is revoked.

### Remaining close-out items

- [ ] Run the aggregate repository gate exactly as written in Task 4 Step 9: `python scripts/run_checks.py` and `git diff --check`. The individual Ruff/MyPy/full-pytest commands are already PASS, but no execution evidence for these two aggregate/final commands was supplied when this Plan status was updated.
- [ ] Synchronize `README.md` and `TASK9_README.md` from `WS1 live PostgreSQL API gate: PENDING` to `PASS`, then verify that their claims still remain limited to WS1 evidence.
- [ ] After those two close-out items, run `git status --short --branch` and record/commit the documentation-only WS1 completion update before starting WS2 implementation work.

Because the current `README.md` / `TASK9_README.md` in the reviewed ZIP still record the live PostgreSQL API gate as `PENDING`, the final acceptance item **“README/TASK9 claims match evidence actually produced by the executed gates”** intentionally remains unchecked above until those files are synchronized.

## Commit Sequence

The intended reviewable history is exactly one commit boundary per implementation task:

```text
1. feat(auth): add document operation access policy
2. feat(runtime): add API production bootstrap
3. feat(api): add JWT and database dependencies
4. feat(api): wire current membership document authorization
```

Do not squash these during task execution; each commit is an independent review gate. Integration/merge policy after WS1 completion is outside this implementation plan.
