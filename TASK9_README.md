# Task 9 — 项目权限

## 状态

```text
TASK9_IMPLEMENTATION = COMPLETE
TASK9_OFFLINE_GATE = PASS
TASK9_LIVE_POSTGRES_GATE = PENDING until RUN_POSTGRES_INTEGRATION=1
WS1_FASTAPI_AUTH_RUNTIME_WIRING = IMPLEMENTED
WS1_OFFLINE_GATE = PASS
WS1_LIVE_POSTGRES_API_GATE = PENDING until RUN_POSTGRES_INTEGRATION=1
```


## WS1 补全：FastAPI 生产认证接线

WS1 在 Task 9 已有授权原语之上补齐 API 生产接线：

```text
Bearer JWT
→ AuthenticatedIdentity(user_id only)
→ 当前 PostgreSQL ProjectMembership
→ DocumentAccessService 角色权限矩阵
→ 服务端构造 DocumentActor
→ Task 6 文档用例
```

当前证据边界：

```text
Task 9 authorization primitives      : implemented
WS1 FastAPI auth/runtime wiring       : implemented
WS1 offline gate                     : PASS
WS1 live PostgreSQL API gate         : PENDING
```

`PENDING` 表示尚未在本次实现环境中使用真实迁移后的 PostgreSQL 运行 `tests/integration/api/test_document_auth_postgres.py`；不得把离线 fake-membership 回归或 skip 结果描述为 live validation。WS1 不包含 Run API/SSE、Worker EXECUTE/RESUME、真实 Structured LLM、QA/Issue Graph 改造、Observability、Docker Completion 或 Evaluation。

## 本阶段目标

将前面各模块已经存在的 `project_id` 约束升级为完整的授权链：

```text
JWT / Bearer Token
→ 仅验证可信 user_id
→ PostgreSQL ProjectMembership
→ membership 有效期
→ ProjectAccessScope
→ 当前 PUBLISHED document_version_ids
→ active RAGFlow knowledge_space_ids
→ Retrieval 下推
→ Evidence Post-filter
```

## 新增代码

```text
src/project_agent/application/services/authorization.py
src/project_agent/infrastructure/auth/__init__.py
src/project_agent/infrastructure/auth/jwt.py
src/project_agent/infrastructure/db/repositories/authorization.py
src/project_agent/agent/__init__.py
src/project_agent/agent/policies/__init__.py
src/project_agent/agent/policies/access.py
```

## 新增测试

```text
tests/unit/auth/test_jwt.py
tests/security/test_cross_client.py
tests/security/test_non_member.py
tests/security/test_evidence_postfilter.py
tests/integration/auth/test_authorization_repository.py
tests/fakes/authorization.py
```

## 核心安全不变量

1. JWT 只输出 `AuthenticatedIdentity(user_id)`。
2. Token 中的 role/project/document Claim 一律不作为授权依据。
3. Membership 必须来自 PostgreSQL，并满足 `valid_from <= now < valid_to`。
4. 当前请求只生成一个项目的 least-privilege Scope，不把用户其他项目一起带入。
5. 只有 `PUBLISHED` document_version 能进入 `allowed_document_version_ids`。
6. 只有 active project knowledge space 才能进入 Dataset 范围。
7. 如果允许文档版本或 Dataset 为空，直接不调用 Knowledge Provider。
8. Provider 返回后再次按 project/document_version/dataset 三个维度过滤。
9. `knowledge_space_id=None` 的 Evidence 因无法验证 Provider Scope，被直接丢弃。
10. Citation Guard 的最终引用级校验属于后续 Task 11，本阶段不提前实现。

## 为什么空授权列表不能传给 RAGFlow

Task 5 的 `KnowledgeRetrievalRequest` 中：

```text
document_version_ids = ()
knowledge_space_ids = ()
```

表示 Provider 不按对应字段限制。

因此 Task 9 在用户没有任何 PUBLISHED 文档、没有 active Dataset，或请求的 document/dataset 与授权集合交集为空时，`ProjectAccessPolicy.constrain_retrieval()` 返回 `None`，调用方必须跳过 Provider Retrieval。

这避免：

```text
没有权限
→ 空 tuple
→ Provider 解释成“不限制”
→ 反而查询全部
```

## JWT V1 说明

V1 提供一个最小 HS256 verifier，用于内部部署和工程验证：

- 校验签名；
- 固定 `alg=HS256`；
- 校验 `iss`；
- 校验 `aud`；
- 强制 `exp`；
- 支持 `nbf`；
- `sub` 必须是 UUID；
- secret 至少 32 bytes。

Verifier 最终只返回 `user_id`。

后续如接企业 OIDC/JWKS，可以替换 authentication adapter，但 `AuthorizationService` 与 `ProjectAccessPolicy` 不需要改变。

## 配置

`.env` 增加：

```dotenv
JWT_HS256_SECRET=<至少32字节的随机密钥>
JWT_ISSUER=project-agent
JWT_AUDIENCE=project-agent-api
JWT_LEEWAY_SECONDS=30
```

Staging 会拒绝默认 `replace-me...` JWT secret。

## 专项 Gate 9

```bash
uv run pytest \
  tests/unit/auth \
  tests/security/test_cross_client.py \
  tests/security/test_non_member.py \
  tests/security/test_evidence_postfilter.py \
  tests/integration/auth/test_authorization_repository.py \
  -v
```

在没有设置 PostgreSQL 在线测试时，最后一个测试会 SKIP。

真实 Gate：

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

uv run pytest \
  tests/unit/auth \
  tests/security/test_cross_client.py \
  tests/security/test_non_member.py \
  tests/security/test_evidence_postfilter.py \
  tests/integration/auth/test_authorization_repository.py \
  -v
```

目标：0 skip。

## 本阶段没有 Schema Migration

Task 9 复用：

```text
projects
project_memberships
documents
document_versions
project_knowledge_spaces
```

所以 Alembic head 仍为：

```text
0003_background_job_leases
```

## 提交建议

```bash
git add \
  .env.example \
  .github/workflows/ci.yml \
  src/project_agent/application/services/authorization.py \
  src/project_agent/infrastructure/auth \
  src/project_agent/infrastructure/db/repositories/authorization.py \
  src/project_agent/agent \
  tests/unit/auth \
  tests/security/test_cross_client.py \
  tests/security/test_non_member.py \
  tests/security/test_evidence_postfilter.py \
  tests/integration/auth \
  tests/fakes/authorization.py \
  scripts/run_checks.py \
  README.md \
  TASK9_README.md

git commit -m "feat: enforce project membership access"
```
