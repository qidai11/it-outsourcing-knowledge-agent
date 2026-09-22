# IT Outsourcing Knowledge and Ticket Collaboration Agent

面向 **IT 外包 / 软件交付团队** 的多项目知识与工单协同 Agent。

项目聚焦真实交付过程中常见的四类问题：**资料分散、版本混用、跨项目数据隔离、知识到工单的受控衔接**。系统以 FastAPI 提供 API，以 LangGraph 编排业务流程，以 PostgreSQL 保存业务事实与运行状态，以 RAGFlow 承担文档解析和检索，并通过权限、版本、权威等级、Evidence Snapshot、Citation Guard、人工确认和幂等机制约束 Agent 行为。

> 当前定位：**internal-first, external-ready**。V1 面向公司内部项目成员，不是通用企业 AI 平台，也不直接连接生产 Jira / 禅道 / 飞书项目进行写操作。

---

## 1. 为什么做这个项目

IT 外包交付通常同时维护多个客户、多个项目。需求、接口说明、测试记录、实施手册和历史问题往往散落在不同位置，而且存在大量同名文件、旧版本文档和带编号的业务对象，例如：

```text
REQ-3.2.1
API-ORDER-017
BUG-1842
ERR-PAY-403
```

如果只做一个普通的「向量库 + LLM」RAG，容易出现几个工程问题：

- 查询精确编号时召回相邻编号，而不是目标对象；
- 新旧版本同时存在时，模型引用旧文档；
- 不同客户或项目的数据进入同一次回答；
- 检索分数高的资料覆盖了人工指定的正式/权威资料；
- 回答中的引用无法回溯到当时真正使用的证据；
- Agent 根据自然语言直接创建工单，造成误操作或重复副作用。

这个项目的核心不是「让 LLM 自己做更多」，而是把 LLM 放在一个有明确业务边界的执行系统中：**LLM 负责理解和生成，程序负责权限、状态、证据、确认和副作用控制。**

---

## 2. 核心业务场景

### 2.1 项目交付知识问答

用户在已授权项目范围内查询需求、接口、测试、实施或历史交付资料。

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

这条链路不是单纯 Vector Top-K：

1. JWT 只确认用户身份；
2. 项目权限从 PostgreSQL 中的当前 `ProjectMembership` 重新计算；
3. 对需求号、接口号、错误码等 Identifier 优先走精确注册表；
4. 再把项目、文档版本和知识空间约束下推到 RAGFlow；
5. 检索结果返回后再次做 Evidence ACL 后置校验；
6. 只允许当前、有效、满足 Authority Policy 的证据进入回答；
7. 最终引用绑定到冻结的 Evidence Snapshot；
8. Citation Guard 校验回答中的 claim/citation 关系，失败时只允许有限修订，否则拒答。

### 2.2 历史 Issue 查询

系统可以在当前项目内查询 Sandbox 历史 Issue，结合 `error_code`、`module`、关键词、状态等信号生成 `possible_duplicates` 候选。

```mermaid
flowchart LR
    A[Authorized Project] --> B[Issue Query]
    B --> C[Same-project Candidate Search]
    C --> D[possible_duplicates]
    D --> E[View / Link / Continue / Cancel]
```

系统不会把相似 Issue 自动判定为真正的 duplicate；候选只是给人的决策证据。

### 2.3 基于证据的 Issue 草稿与受控创建

当用户选择继续创建 Issue 时，系统先组合需求、测试、知识证据和历史 Issue，生成 Draft，再进入人工确认。

```mermaid
flowchart LR
    A[Authorized Scope] --> B[Retrieve Issue Evidence]
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

创建链路的关键约束：

- 没有明确确认，不产生创建副作用；
- Resume 请求必须绑定确认时的 payload hash；
- 真正执行前重新检查用户权限；
- 应用层和 Sandbox Provider 都有幂等约束；
- 对「请求已发送但响应丢失」的未知结果提供 reconciliation；
- V1 只写入 `SandboxProjectTrackerAdapter`，不直接写生产 Jira / 禅道 / 飞书项目。

---

## 3. 系统架构

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

| 层                  | 技术                             | 作用                                                         |
| ------------------- | -------------------------------- | ------------------------------------------------------------ |
| API                 | FastAPI                          | 文档、Run、SSE、健康检查、Metrics                            |
| Agent Orchestration | LangGraph                        | QA / Issue 流程、Interrupt、Resume、Checkpoint               |
| Database            | PostgreSQL 16                    | 权限、文档、Identifier、Run、Evidence、Issue、审计等业务事实 |
| Background Jobs     | PostgreSQL Job Queue             | Worker、Lease、Heartbeat、Retry、Reaper                      |
| Knowledge           | RAGFlow `v0.26.4`                | 文档解析、Chunk、检索与项目知识空间                          |
| LLM                 | OpenAI-compatible Structured API | Query Analysis、结构化生成、回答与修订                       |
| Object Storage      | LocalFileObjectStoreAdapter      | V1 源文件存储                                                |
| Issue Provider      | SandboxProjectTrackerAdapter     | V1 工单查询、创建与故障恢复验证                              |
| Persistence         | SQLAlchemy + Alembic             | 异步数据访问和 Schema Migration                              |
| Observability       | structlog + Prometheus           | JSON 日志、Run/Provider/Queue/Token 等指标                   |
| Tooling             | uv + Ruff + MyPy + Pytest        | 依赖、静态检查与自动化测试                                   |

---

## 4. 关键工程设计

### 4.1 项目级权限不是 Prompt 约束

系统不会把「你只能访问项目 A」只写进 Prompt。

认证后的 JWT 只提供可信 `user_id`，真正的访问范围由服务器根据当前数据库状态计算：

```text
JWT sub
→ active ProjectMembership
→ ProjectAccessScope
→ allowed knowledge spaces / document versions
→ retrieval down-push
→ Evidence post-filter
```

因此，即使 LLM 或检索服务返回了不属于当前项目的内容，也不能直接进入后续回答。

### 4.2 Exact Identifier + 范围受限检索

对于项目中的精确业务编号，系统采用两阶段思路：

```text
Query
→ Identifier Extraction
→ Project-scoped Exact Registry
→ constrained RAGFlow Retrieval
→ Evidence Governance
```

精确命中使用 PostgreSQL B-tree 路径；`pg_trgm` 只用于拼写建议，不用模糊结果覆盖精确业务事实。

这解决的是企业知识库里很常见的问题：用户查 `REQ-3.2.1` 时，Embedding 语义相近并不代表 `REQ-3.2.2` 可以替代目标需求。

### 4.3 文档生命周期与人工 Authority

文档状态：

```text
DRAFT
→ UNDER_REVIEW
→ APPROVED
→ PUBLISHED
→ SUPERSEDED / ARCHIVED / DELETE_PENDING / DELETED
```

**只有 `PUBLISHED` 文档可以进入普通知识检索。**

发布新版本时旧版本进入 `SUPERSEDED`；AI 可以提供 MetadataSuggestion，但不能自己批准 Authority，也不能自己发布正式文档。

### 4.4 Evidence Snapshot 与 Citation Guard

系统不会只保存最后一段自然语言答案。

回答前，会把经过 ACL、版本和 Authority 治理后的候选证据冻结为 Evidence Snapshot；最终 Citation 指向这些 Snapshot，而不是重新查询得到的动态结果。

```text
Retrieval Candidate
→ Governance
→ Evidence Bundle
→ Evidence Snapshot
→ Answer
→ Citation
```

这使回答具备可复核性：之后即使知识库内容变化，也可以知道某次 Run 当时依据了什么证据。

### 4.5 Human-in-the-loop 写操作

知识查询可以自动执行，但工单创建属于有副作用操作。

因此创建流程使用 LangGraph interrupt/resume，把「生成 Draft」和「真正创建」分开；用户确认之后仍要重新检查权限，并经过持久化幂等屏障。

### 4.6 Durable Run，而不是一次 HTTP 请求跑到底

Run API 把一次 Agent 执行建模为持久化业务对象。

支持三种业务模式：

```text
qa
issue_lookup
issue_create
```

执行由 PostgreSQL Job Queue 交给 Worker，Run 状态和事件写入数据库；客户端可以通过 SSE 消费事件，并使用 `Last-Event-ID` 继续读取。

这避免把长执行链绑定在一次同步 HTTP 请求生命周期内，也为重试、恢复、观测和人工确认提供稳定边界。

---

## 5. 数据与状态边界

PostgreSQL 不只是保存聊天历史，它是本项目的业务事实中心，主要包含：

- Client / Project；
- ProjectMembership / KnowledgeSpace；
- Document / DocumentVersion / ACL；
- DocumentIdentifier；
- BackgroundJob / IngestionJob；
- Thread / AgentRun / AgentEvent；
- EvidenceBundle / EvidenceSnapshot；
- Answer / Citation；
- IssueDraft / IssueCandidate；
- SandboxIssue / SandboxIssueEvent；
- ToolConfirmation；
- IdempotencyRecord；
- AuditLog；
- SystemConfig / RetentionPolicy。

LangGraph Checkpoint 同样持久化到 PostgreSQL。Graph State 尽量保存引用 ID，而不是无限累积完整 Query、Evidence 和 Answer Payload。

---

## 6. API 概览

### Health / Metrics

```text
GET  /live
GET  /ready
GET  /metrics
```

### Document Lifecycle

```text
POST   /api/v1/documents
POST   /api/v1/documents/{version_id}/submit-review
POST   /api/v1/documents/{version_id}/approve
POST   /api/v1/documents/{version_id}/publish
DELETE /api/v1/documents/{version_id}
```

### Agent Runs

```text
POST /api/v1/runs
POST /api/v1/runs/{run_id}/resume
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/events
```

受保护接口使用：

```http
Authorization: Bearer <JWT>
```

JWT 负责认证用户身份；角色和项目访问权限不会接受客户端自行声明，而是从数据库中的 Membership 重新计算。

启动 API 后可以通过 FastAPI OpenAPI 页面查看完整请求模型：

```text
http://localhost:8000/docs
```

---

## 7. 快速启动

### 7.1 环境要求

- Python `3.12.x`；
- `uv`；
- Docker / Docker Compose；
- PostgreSQL 16（Compose 已包含）；
- 可访问的 RAGFlow `v0.26.4`；
- 支持 `POST /chat/completions` 和 strict JSON Schema response format 的 OpenAI-compatible LLM Provider。

> `compose.yaml` 只启动 PostgreSQL、API 和 Worker。RAGFlow 是 companion service，需要单独运行，并通过 `RAGFLOW_BASE_URL` 连接。

### 7.2 配置

```bash
cp .env.example .env
```

至少检查以下配置：

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

### 7.3 安装开发依赖

```bash
uv sync --all-groups
```

### 7.4 使用 Docker Compose 启动

```bash
docker compose up -d postgres

docker compose run --rm app-api alembic upgrade head

docker compose up -d --build app-api app-worker
```

检查服务：

```bash
docker compose ps
curl -fsS http://127.0.0.1:8000/live
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:9101/metrics >/dev/null
```

正常的 readiness 响应：

```json
{
  "status": "ready",
  "configuration": "ok",
  "database": "ok"
}
```

### 7.5 本机开发方式

如果 PostgreSQL、RAGFlow 和 LLM Provider 已经可用：

```bash
uv run alembic upgrade head
uv run uvicorn project_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

另开一个终端启动 Worker：

```bash
uv run project-agent-worker
```

---

## 8. 项目目录

```text
.
├── src/project_agent/
│   ├── agent/                  # LangGraph graphs、nodes、state、policy
│   ├── api/                    # FastAPI routes / dependencies
│   ├── application/            # ports、services、use cases
│   ├── domain/                 # 核心业务模型与枚举
│   ├── infrastructure/         # DB / RAGFlow / LLM / object store / tracker
│   ├── observability/          # logging、metrics、cost、sanitization
│   ├── runtime/                # API / QA / Issue / Worker production wiring
│   └── workers/                # queue handlers、retry、reaper、run execution
├── migrations/                 # Alembic migrations
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── e2e/
│   ├── reliability/
│   └── security/
├── docs/
│   ├── business/               # 产品边界、权限、文档与 Issue 规则
│   ├── adr/                    # Architecture Decision Records
│   └── runbooks/               # RAGFlow、幂等、live gates 等运行手册
├── scripts/                    # checks、seed、live acceptance scripts
├── compose.yaml
├── Dockerfile
├── alembic.ini
└── pyproject.toml
```

---

## 9. 测试与质量检查

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

仓库也提供统一检查入口：

```bash
python scripts/run_checks.py
```

部分 PostgreSQL / RAGFlow / LLM provider 测试属于显式 live gate，需要对应外部依赖和环境变量，不应把因环境未启用而 skip 的测试当成 live acceptance 结果。

---

## 10. 可观测性

API 暴露 Prometheus metrics：

```text
GET /metrics
```

Worker 默认在：

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

日志使用结构化 JSON，并对异常信息和敏感字段进行 sanitization。Run 还会持久化模型别名、Prompt 版本/Hash、Token、检索轮次以及配置了价格时的估算成本。

---

## 11. 安全与可靠性原则

项目把以下条件作为硬约束，而不是依赖模型自行遵守：

```text
跨项目 Evidence            = 0
未授权项目访问             = 0
非 PUBLISHED 文档普通召回  = 0
跨项目 Citation            = 0
未确认 Issue 创建          = 0
重复创建副作用             = 0
```

其他关键规则：

- 请求体不能覆盖服务器计算出的角色；
- 过期 Membership 按无权限处理；
- Viewer 不能创建 Issue；
- LLM 不能直接批准或发布文档；
- LLM 不能自动认定真正的 duplicate Issue；
- 外部文本不能改变服务端权限边界；
- `legal_hold=true` 时禁止物理删除相关数据；
- Provider 调用使用有界重试，而不是无限重试。

---

## 12. 当前实现边界

V1 已实现的核心后端能力包括：

- 多项目权限隔离；
- 文档上传、审核、批准、发布和删除生命周期；
- 项目独立知识空间；
- Exact Identifier Registry；
- RAGFlow 检索适配；
- Structured LLM QA；
- Evidence / Citation 治理；
- QA / Issue Lookup / Issue Create LangGraph；
- Durable Run + SSE；
- PostgreSQL Job Queue + Worker；
- Sandbox Issue 查询和人工确认后的幂等创建；
- JSON Logging + Prometheus Metrics；
- Docker Compose 运行基线。

以下能力**不属于当前 V1**：

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

这些边界是有意保留的：V1 优先验证项目知识检索、证据可信度、权限隔离和受控工单闭环，而不是扩大技术栈。

---

## 13. Evaluation 状态

项目已经定义了正式评测目标，但 README 不把这些目标写成当前实测成绩。

主要目标包括：

| Metric                     | V1 Target |
| -------------------------- | --------: |
| Exact-Identifier Hit@10    |     ≥ 95% |
| Evidence Recall@10         |     ≥ 90% |
| Current-Version Hit Rate   |     ≥ 95% |
| Citation ID Validity       |      100% |
| 无答案拒答准确率           |     ≥ 90% |
| Cross-project Evidence     |         0 |
| Unconfirmed Issue Creation |         0 |
| Duplicate Side Effects     |         0 |

正式 Benchmark / Runner / Metrics / Ablation / Report 应以独立 Evaluation 流程产出的结果为准；在评测完成前，不应把目标值描述成项目已经取得的性能成绩。

---

## 14. 设计原则总结

这个项目最终想验证的不是「Agent 能不能调用很多工具」，而是：

> **如何让一个面向真实企业交付场景的 Agent，在多项目、多版本、多权限和有副作用操作的条件下，仍然能够给出可追溯、可复核、可恢复的结果。**

因此系统把能力划分为两类：

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

这也是整个项目最核心的工程取舍：**把概率性的模型能力放在确定性的业务约束之内。**
