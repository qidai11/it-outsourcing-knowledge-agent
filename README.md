# IT Outsourcing Knowledge and Ticket Collaboration Agent

> 面向 IT 外包 / 软件交付团队的多项目知识与工单协同 Agent。
> 当前阶段：**Internal PoC / MVP**。核心目标不是让 LLM “自动做更多”，而是在多项目、多版本、多权限和有副作用操作的企业场景中，让 Agent 的结果**可追溯、可复核、可恢复、可约束**。

**Repository:** https://github.com/qidai11/it-outsourcing-knowledge-agent

---

## 项目概览

IT 外包交付通常同时维护多个客户、多个项目。需求文档、接口说明、测试记录、实施手册和历史工单分散在不同位置，并长期存在以下问题：

- 同一项目中存在多个文档版本，旧版本容易被误用；
- `REQ-3.2.1`、`API-ORDER-017`、`ERR-IMPORT-004` 等精确业务编号不适合只靠语义检索；
- 不同客户 / 项目的知识必须严格隔离；
- “语义更相似”不等于“业务上更权威”；
- 回答中的引用需要能够回溯到当时真正使用的证据；
- 创建 Issue 属于有副作用操作，不能由模型直接执行；
- Agent 执行时间可能超过一次 HTTP 请求，需要支持状态持久化、恢复、重试和审计。

因此，本项目采用：

- **FastAPI**：对外提供 Document / Run / SSE / Health / Metrics API；
- **LangGraph**：编排 QA、Issue Lookup、Issue Create 流程；
- **PostgreSQL**：保存权限、文档、Identifier、Run、Evidence、Issue、审计和 Checkpoint；
- **RAGFlow `v0.26.4`**：承担文档解析、Chunk、检索和项目知识空间；
- **Structured LLM API**：负责 Query Analysis、结构化生成、回答与有限修订；
- **确定性业务约束**：负责 Authorization、版本治理、Evidence、Citation、HITL、Idempotency 和 Recovery。

项目当前定位为：

> **internal-first, external-ready**

V1 面向公司内部项目成员，不是通用企业 AI 平台，也不直接连接生产 Jira / 禅道 / 飞书项目执行真实写操作。

---

## 核心业务场景

### 1. 项目交付知识问答

用户在已授权项目范围内查询需求、接口、数据库、测试、实施和历史交付资料。

```mermaid
flowchart LR
    A[Bearer JWT] --> B[Project Membership]
    B --> C[Query Analysis]
    C --> D[Project Scope]
    D --> E[Exact Identifier Resolver]
    E --> F[RAGFlow Retrieval]
    F --> G[ACL / Version / Authority Filter]
    G --> H[Evidence Snapshot]
    H --> I[LLM Answer]
    I --> J[Citation Guard]
    J --> K[Answer / Revision / Refusal]
```

这条链路不是简单的 `Vector Top-K -> LLM`：

1. JWT 只负责确认用户身份；
2. 当前项目权限从 PostgreSQL 中的 `ProjectMembership` 重新计算；
3. 对业务 Identifier 尝试走项目范围内的精确解析；
4. 项目、知识空间、文档版本等约束下推到检索层；
5. 检索结果返回后再次执行 Evidence ACL / Version / Authority 治理；
6. 只有满足治理规则的证据才能进入回答；
7. 最终 Citation 绑定冻结的 Evidence Snapshot；
8. Citation Guard 校验 claim / citation 关系，不满足约束时进行有限修订或拒答。

### 2. 历史 Issue 查询与重复候选

系统可以在当前项目内查询 Sandbox 历史 Issue，并结合 `error_code`、`module`、关键词、状态等信号形成 `possible_duplicates`。

```mermaid
flowchart LR
    A[Authorized Project] --> B[Issue Query]
    B --> C[Same-project Candidate Search]
    C --> D[possible_duplicates]
    D --> E[View / Link / Continue / Cancel]
```

相似候选只是提供给人的决策证据，系统不会把“语义相似”直接等价成“真实重复 Issue”。

### 3. 基于证据的 Issue 草稿与受控创建

当用户需要创建 Issue 时，Agent 先组织证据并生成 Draft，再进入人工确认。

```mermaid
flowchart LR
    A[Authorized Scope] --> B[Retrieve Evidence]
    B --> C[Search Similar Issues]
    C --> D[Issue Draft]
    D --> E[LangGraph Interrupt]
    E --> F{User Confirmation}
    F -->|Confirm| G[Permission Re-check]
    F -->|Cancel| H[No Side Effect]
    G --> I[Idempotency Barrier]
    I --> J[Sandbox Create]
    J --> K[Created / Reconciled]
```

关键约束：

- 没有明确确认，不产生创建副作用；
- Resume 请求绑定确认时的 payload；
- 真正执行前重新检查当前权限；
- 应用层和 Sandbox Provider 均存在幂等边界；
- 对“请求已发出但响应丢失”的未知结果执行 reconciliation；
- 当前只写入 `SandboxProjectTrackerAdapter`。

---

## 系统架构

```mermaid
flowchart TB
    Client[Client / Internal UI]

    subgraph API[FastAPI]
        Auth[JWT Authentication]
        Docs[Document API]
        Runs[Run API + SSE]
    end

    subgraph App[Application / Domain]
        Authorization[Authorization Service]
        DocumentLifecycle[Document Lifecycle]
        Identifier[Identifier Registry]
        Evidence[Evidence Governance]
        Issue[Issue Draft / Confirmation / Creation]
    end

    subgraph Graph[LangGraph Runtime]
        QA[QA Graph]
        IssueLookup[Issue Lookup Graph]
        IssueCreate[Issue Create Graph]
    end

    subgraph Worker[Background Worker]
        Queue[PostgreSQL Job Queue]
        Runner[Run Executor]
        Reaper[Lease / Retry / Reaper]
    end

    subgraph Infra[Infrastructure]
        PG[(PostgreSQL)]
        RAG[RAGFlow]
        LLM[OpenAI-compatible Structured LLM]
        Store[Local Object Store]
        Tracker[Sandbox Project Tracker]
    end

    Client --> API
    API --> App
    App --> PG

    Runs --> Queue
    Queue --> Runner
    Runner --> Graph

    Graph --> Authorization
    Graph --> Identifier
    Graph --> Evidence
    Graph --> RAG
    Graph --> LLM
    Graph --> Tracker

    Docs --> DocumentLifecycle
    DocumentLifecycle --> Store
    DocumentLifecycle --> RAG

    Reaper --> PG
```

### 技术栈

| 层 | 技术 | 作用 |
|---|---|---|
| API | FastAPI | Document、Run、SSE、Health、Metrics |
| Agent Orchestration | LangGraph | QA / Issue 流程、Interrupt、Resume、Checkpoint |
| Database | PostgreSQL 16 | 权限、文档、Identifier、Run、Evidence、Issue、审计等业务事实 |
| Background Jobs | PostgreSQL Job Queue | Worker、Lease、Heartbeat、Retry、Reaper |
| Knowledge | RAGFlow `v0.26.4` | 文档解析、Chunk、检索、项目知识空间 |
| LLM | OpenAI-compatible Structured API | Query Analysis、结构化输出、Answer、Revision |
| Object Storage | `LocalFileObjectStoreAdapter` | V1 源文件存储 |
| Issue Provider | `SandboxProjectTrackerAdapter` | Issue 查询、创建、幂等和恢复验证 |
| Persistence | SQLAlchemy + Alembic | 异步数据访问、Schema Migration |
| Observability | structlog + Prometheus | JSON Logging、Run / Provider / Queue / Token Metrics |
| Tooling | uv + Ruff + MyPy + Pytest | 依赖、静态检查、自动化测试 |

---

## 关键工程设计

### 1. 权限隔离不是 Prompt 约束

系统不会只在 Prompt 中告诉模型“只能访问项目 A”。

真实授权链路为：

```text
JWT sub
  ↓
active ProjectMembership
  ↓
ProjectAccessScope
  ↓
allowed knowledge spaces / document versions
  ↓
retrieval constraint
  ↓
Evidence post-filter
```

即使检索服务或 LLM 返回了越权内容，未经服务端治理也不能进入最终回答。

### 2. Exact Identifier + 范围受限检索

针对需求号、接口号、错误码等业务 Identifier，设计目标是：

```text
Query
  ↓
Identifier Extraction
  ↓
Project-scoped Exact Registry
  ↓
Constrained Retrieval
  ↓
Evidence Governance
```

精确 Identifier 的目标是避免：

```text
REQ-3.2.1  ≠  REQ-3.2.2
```

仅凭 embedding 相似度不能替代业务对象精确匹配。

> **Evaluation 现状：** 当前 V0 live gate 发现 Exact Identifier 集成路径存在明显回归，详见下方 Evaluation。该设计仍保留，但当前实现需要继续修复和验证。

### 3. 文档生命周期与人工 Authority

文档生命周期：

```text
DRAFT
  ↓
UNDER_REVIEW
  ↓
APPROVED
  ↓
PUBLISHED
  ↓
SUPERSEDED / ARCHIVED / DELETE_PENDING / DELETED
```

主要规则：

- 普通知识检索只允许使用可用的正式版本；
- 新版本发布后，旧版本可进入 `SUPERSEDED`；
- 模型可以提出 Metadata Suggestion；
- 模型不能自行批准 Authority；
- 模型不能自行发布正式文档。

### 4. Evidence Snapshot + Citation Guard

系统不只保存最终自然语言回答，而是保存当时真正参与回答的治理后证据。

```text
Retrieval Candidate
  ↓
ACL / Version / Authority Governance
  ↓
Evidence Bundle
  ↓
Evidence Snapshot
  ↓
Answer
  ↓
Citation
```

这样即使后续知识库内容发生变化，也可以复核某次 Run 当时基于哪些证据生成回答。

### 5. Human-in-the-loop 写操作

知识问答可以自动执行，但 Issue 创建属于有副作用操作。

因此：

```text
Draft
  ↓
Interrupt
  ↓
Human Confirmation
  ↓
Permission Re-check
  ↓
Idempotency Barrier
  ↓
Provider Write
```

模型不能绕过确认直接执行写操作。

### 6. Durable Run

一次 Agent 执行被建模成持久化 `AgentRun`，而不是绑定在单次 HTTP 请求生命周期内。

当前支持：

```text
qa
issue_lookup
issue_create
```

Run 通过 PostgreSQL Job Queue 交给 Worker 执行，状态和事件持续写入数据库。客户端可以通过 SSE 消费事件，并通过 `Last-Event-ID` 继续读取。

这样为以下能力提供稳定边界：

- 长链路执行；
- Retry / Recovery；
- HITL Resume；
- Queue Lease；
- Crash Reaper；
- Observability；
- Audit。

---

## Evaluation

项目已经接入正式 V0 Evaluation 流程，并完成一次真实 live gate。

### Evaluation Snapshot

| 项目 | 值 |
|---|---|
| Evaluation Run | `eval-v0-ws8-v0-live-gate-fa3773c46efd470aa20b03006f85b556` |
| Dataset | `v0 / Synthetic V0` |
| Selected Cases | 50 |
| Scored | 47 |
| Unscorable | 3 |
| Infra Failure | 0 |
| Runner Failure | 0 |
| Pipeline Status | **COMPLETE** |
| Product Status | **FAIL** |
| Model | `deepseek-ai/DeepSeek-V4-Flash` |
| RAGFlow | `v0.26.4` |
| Python | `3.12.14` |
| Git Commit | `13216b8a92272c04942d26d6d0e322bafdf769c8` |
| Worktree | `dirty=true` |

> 这次 Evaluation 的意义是建立真实基线和暴露系统缺陷，而不是为了得到“全绿”的展示结果。
> Benchmark 为 Synthetic V0，不代表生产客户数据上的真实准确率；同时该 run 记录为 dirty worktree，因此更适合作为诊断基线，而不是 release benchmark。

### V1 Acceptance Metrics

| Metric | Target | V0 Measured | Result |
|---|---:|---:|---|
| Exact-Identifier Hit@10 | ≥ 95% | **13.3%** `2/15` | ❌ |
| Evidence Recall@10 | ≥ 90% | **37.0%** `10/27` | ❌ |
| Current-Version Hit Rate | ≥ 95% | **42.9%** `3/7` | ❌ |
| Citation ID Validity | 100% | **48.0%** `12/25` | ❌ |
| No-answer Refusal Accuracy | ≥ 90% | **100%** `3/3` | ✅ |
| Cross-project Evidence | 0 | **0** `0/9` | ✅ |
| Unconfirmed Issue Creation | 0 | **0** `0/5` | ✅ |
| Duplicate Issue Side Effects | 0 | **0** `0/2` | ✅ |
| Critical Regression | 100% | **60.0%** `9/15` | ❌ |

Case-level behavior scoring：

```text
PASS        24
FAIL        23
UNSCORABLE   3
```

该统计用于辅助诊断，不替代上面的正式 Acceptance Metrics。

### 当前已经验证的安全边界

这次 V0 Evaluation 已验证：

- **Cross-project Evidence = 0**
- **Unconfirmed Issue Creation = 0**
- **Duplicate Issue Side Effects = 0**
- **No-answer Refusal Accuracy = 100%**

这说明当前实现中，项目隔离、未确认写操作阻断、重复副作用控制和缺证据拒答已经形成可执行的安全边界。

但 `critical_regression = 60%`，说明系统尚未满足完整的发布 Gate。

### 当前主要质量问题

V0 基线暴露出的主要问题集中在：

1. **Exact Identifier 检索链路**
   - 正式指标仅 `2/15`；
   - 多个 Identifier 类问题最终 Run `FAILED` 或没有形成预期 Evidence；
   - 当前 Exact Registry 的集成方式需要重新检查。

2. **Evidence Recall**
   - Recall@10 只有 `37.0%`；
   - 说明很多正确证据在进入生成阶段之前已经丢失。

3. **Current Version**
   - 当前版本命中率只有 `42.9%`；
   - 版本治理的“设计规则”已经存在，但实际检索 / 过滤链仍未稳定达到目标。

4. **Citation**
   - Citation ID Validity 只有 `48.0%`；
   - 部分 Case 没有成功进入可生成 Citation 的证据链。

5. **部分运行能力尚未进入 Production Runtime**
   - fuzzy Identifier suggestion / confirmation；
   - company-public Run scope；
   - Issue Key exact lookup。

这 3 类能力在 V0 中对应 3 个 `UNSCORABLE_RUNTIME_SCOPE` Case。

### Ablation Findings

V0 同时执行了受控变体和 shadow ablation。

#### `no_exact_registry`

禁用当前 Exact Registry 路径后：

| Metric | Baseline | Variant | Delta |
|---|---:|---:|---:|
| Exact-Identifier Hit@10 | 13.3% | **93.3%** | **+80.0pp** |
| Evidence Recall@10 | 37.0% | **77.8%** | **+40.7pp** |

这不是“Exact Registry 没有价值”的结论，而是一个非常强的诊断信号：

> **当前 Exact Registry 集成路径正在破坏后续检索效果，优先级高于继续叠加新的 RAG 策略。**

下一步应该优先检查：

```text
Identifier Extraction
  ↓
Registry Resolve Result
  ↓
Version / Document Scope
  ↓
RAGFlow Filter Composition
  ↓
Candidate Merge
  ↓
Evidence Governance
```

重点确认 Exact Match 是否错误缩窄范围、错误绑定版本、错误拼接 filter，或在 Exact Resolver 失败后缺少正确 fallback。

#### `single_round_only`

受控变体中：

- Evidence Recall@10：`37.0% -> 40.7%`
- Mean Latency：约 `17.1s -> 15.4s`

当前数据不支持“多轮检索已经有效提升质量”的结论，因此在修复基础检索链路前，不应优先增加更多 retrieval round。

#### Shadow Ablation

`pre_governance_shadow` 和 `pre_guard_shadow` 在可匹配的 10 个 Case 中没有观察到显著治理变化。

这说明当前 Evaluation 首先暴露的是**上游召回 / runtime chain 问题**；当正确 Evidence 没有进入候选集时，后面的 Governance 和 Citation Guard 无法弥补召回缺失。

### Evaluation 当前结论

```text
Safety boundary:      部分已经通过
Retrieval quality:    未通过
Version accuracy:     未通过
Citation validity:    未通过
Release gate:         未通过
```

当前工程优先级：

```text
P0  修复 Exact Identifier → Retrieval 集成回归
P0  修复基础 Evidence Recall
P0  修复 Current-Version 过滤 / 选择链
P1  修复 Citation ID 生成与绑定
P1  补齐 Issue Key exact lookup
P1  补齐 fuzzy Identifier confirmation
P2  再评估多轮检索 / Query Rewrite 等增强策略
```

---

## 数据与状态边界

PostgreSQL 不只是“聊天历史数据库”，而是整个系统的业务事实中心。

主要实体包括：

- `Client / Project`
- `ProjectMembership / KnowledgeSpace`
- `Document / DocumentVersion / ACL`
- `DocumentIdentifier`
- `BackgroundJob / IngestionJob`
- `Thread / AgentRun / AgentEvent`
- `EvidenceBundle / EvidenceSnapshot`
- `Answer / Citation`
- `IssueDraft / IssueCandidate`
- `SandboxIssue / SandboxIssueEvent`
- `ToolConfirmation`
- `IdempotencyRecord`
- `AuditLog`
- `SystemConfig / RetentionPolicy`

LangGraph Checkpoint 同样持久化到 PostgreSQL。

Graph State 尽量保存 ID / Reference，而不是无限累积完整 Query、Evidence 和 Answer Payload。

---

## API 概览

### Health / Metrics

```http
GET /live
GET /ready
GET /metrics
```

### Document Lifecycle

```http
POST   /api/v1/documents
POST   /api/v1/documents/{version_id}/submit-review
POST   /api/v1/documents/{version_id}/approve
POST   /api/v1/documents/{version_id}/publish
DELETE /api/v1/documents/{version_id}
```

### Agent Runs

```http
POST /api/v1/runs
POST /api/v1/runs/{run_id}/resume
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/events
```

受保护接口使用：

```http
Authorization: Bearer <JWT>
```

JWT 只负责认证。角色和项目访问权限由服务器从 Membership 重新计算，不接受客户端直接覆盖。

启动 API 后可访问：

```text
http://localhost:8000/docs
```

查看 FastAPI OpenAPI 文档。

---

## 快速启动

### 环境要求

- Python `3.12.x`
- `uv`
- Docker / Docker Compose
- PostgreSQL 16（Compose 已包含）
- RAGFlow `v0.26.4`
- 支持 `POST /chat/completions` 与 strict JSON Schema response format 的 OpenAI-compatible LLM Provider

> `compose.yaml` 只负责 PostgreSQL、API 和 Worker。RAGFlow 作为 companion service 独立运行。

### 1. Clone

```bash
git clone https://github.com/qidai11/it-outsourcing-knowledge-agent.git
cd it-outsourcing-knowledge-agent
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

至少检查：

```dotenv
DATABASE_URL=postgresql+asyncpg://project_agent:project_agent@localhost:5432/project_agent

RAGFLOW_BASE_URL=http://localhost:9380
RAGFLOW_API_KEY=...
RAGFLOW_EXPECTED_VERSION=v0.26.4

LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=...
LLM_MODEL_ALIAS=...

JWT_HS256_SECRET=replace-with-a-random-secret-at-least-32-bytes
JWT_ISSUER=project-agent
JWT_AUDIENCE=project-agent-api
```

不要提交真实 `.env`、API Key 或 JWT Secret。

### 3. 安装开发依赖

```bash
uv sync --all-groups
```

### 4. Docker Compose 启动

```bash
docker compose up -d postgres

docker compose run --rm app-api alembic upgrade head

docker compose up -d --build app-api app-worker
```

检查：

```bash
docker compose ps

curl -fsS http://127.0.0.1:8000/live
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:9101/metrics >/dev/null
```

正常 readiness：

```json
{
  "status": "ready",
  "configuration": "ok",
  "database": "ok"
}
```

### 5. 本机开发

如果 PostgreSQL、RAGFlow 和 LLM Provider 已经可用：

```bash
uv run alembic upgrade head

uv run uvicorn project_agent.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

另开终端启动 Worker：

```bash
uv run project-agent-worker
```

---

## 项目目录

```text
.
├── src/project_agent/
│   ├── agent/                  # LangGraph graphs / nodes / state / policy
│   ├── api/                    # FastAPI routes / dependencies
│   ├── application/            # ports / services / use cases
│   ├── domain/                 # 核心业务模型与枚举
│   ├── infrastructure/         # DB / RAGFlow / LLM / object store / tracker
│   ├── observability/          # logging / metrics / cost / sanitization
│   ├── runtime/                # API / QA / Issue / Worker production wiring
│   └── workers/                # queue / retry / reaper / run execution
│
├── evaluation/
│   └── datasets/v0/            # Synthetic V0 benchmark dataset
│
├── migrations/                 # Alembic migrations
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── e2e/
│   ├── reliability/
│   └── security/
│
├── docs/
│   ├── business/               # 产品边界、权限、文档、Issue 规则
│   ├── adr/                    # Architecture Decision Records
│   └── runbooks/               # RAGFlow、幂等、live gates 等运行手册
│
├── scripts/
├── compose.yaml
├── Dockerfile
├── alembic.ini
└── pyproject.toml
```

---

## 测试与质量检查

静态检查：

```bash
uv run ruff check src tests
uv run mypy src
git diff --check
```

完整测试：

```bash
uv run pytest
```

统一检查入口：

```bash
python scripts/run_checks.py
```

部分 PostgreSQL / RAGFlow / LLM Provider 测试属于显式 live gate，需要真实外部依赖和环境变量。

**被 skip 的 live test 不等于 live acceptance 已经通过。**

---

## 可观测性

API 暴露：

```http
GET /metrics
```

Worker 默认暴露：

```text
http://localhost:9101/metrics
```

当前指标覆盖：

- HTTP request count / latency；
- Agent Run outcome / duration；
- Queue claim / completion / retry / reaper；
- RAGFlow request / latency；
- Structured LLM request / latency / token usage；
- Citation Guard outcome；
- Authorization denial；
- Issue confirmation；
- Issue create / idempotency / reconciliation outcome。

日志使用结构化 JSON，并对异常信息和敏感字段执行 sanitization。

Run 还会记录：

- model alias；
- prompt version / hash；
- token usage；
- retrieval rounds；
- 配置价格后的 estimated cost；
- 状态变化与关键事件。

---

## 安全与可靠性原则

项目把下面这些条件当作程序硬约束，而不是“希望模型遵守”的 Prompt：

```text
跨项目 Evidence            = 0
未授权项目访问             = 0
非允许状态文档普通召回     = 0
跨项目 Citation            = 0
未确认 Issue 创建          = 0
重复创建副作用             = 0
```

其他规则：

- 请求体不能覆盖服务器计算出的角色；
- 过期 Membership 按无权限处理；
- Viewer 不能创建 Issue；
- LLM 不能直接批准 / 发布正式文档；
- LLM 不能自动认定真正的 duplicate Issue；
- 外部文档 / Prompt Injection 不能改变服务端权限边界；
- `legal_hold=true` 时禁止物理删除相关数据；
- Provider 使用有界 Retry，不执行无限重试；
- 写操作必须经过明确确认和幂等控制。

---

## 当前实现边界

### V1 已实现

- 多项目权限隔离；
- 文档上传、审核、批准、发布和删除生命周期；
- 项目独立知识空间；
- Exact Identifier Registry 基础能力；
- RAGFlow 检索适配；
- Structured LLM QA；
- Evidence / Citation 治理；
- QA / Issue Lookup / Issue Create LangGraph；
- Durable Run + SSE；
- PostgreSQL Job Queue + Worker；
- Sandbox Issue 查询；
- 人工确认后的幂等创建；
- Unknown Result Reconciliation；
- JSON Logging + Prometheus Metrics；
- Docker Compose 运行基线；
- Synthetic V0 Evaluation / Acceptance Gate。

### 当前不包含

- 生产 Jira / 禅道 / 飞书项目写入；
- 客户 Guest / SaaS 多租户；
- Multi-Agent；
- 长期 Memory；
- 自动修改代码或发布生产；
- 自动合并 PR；
- 自动合同责任判断；
- 自动报价和工期估算；
- LLM 自动发布正式文档；
- GraphRAG / RAPTOR；
- Kubernetes；
- Redis / Celery 等额外任务队列。

这些边界是有意保留的。

V1 优先验证：

```text
Project Isolation
      +
Knowledge Retrieval
      +
Evidence Governance
      +
Controlled Side Effects
      +
Durable Execution
      +
Evaluation
```

而不是不断扩大技术栈。

---

## 设计原则

这个项目最终想验证的不是：

> Agent 能不能调用很多工具？

而是：

> **如何让一个面向真实企业交付场景的 Agent，在多项目、多版本、多权限和有副作用操作的条件下，仍然给出可追溯、可复核、可恢复的结果。**

因此能力被明确拆成两类：

```text
LLM 擅长的部分
├── Query 理解
├── 结构化信息生成
├── Answer 生成
└── 有界 Revision

程序必须控制的部分
├── Authentication / Authorization
├── Project Isolation
├── Exact Identifier
├── Document Lifecycle
├── Authority Policy
├── Evidence Snapshot
├── Citation Validation
├── Human Confirmation
├── Idempotency
├── Retry / Recovery
└── Audit / Observability
```

核心工程取舍是：

> **把概率性的模型能力放在确定性的业务约束之内，并用 Evaluation 持续验证这些约束是否真的成立。**
