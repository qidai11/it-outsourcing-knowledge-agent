# Task 3 — Ports 与测试替身

## 目标

建立 Application 层对外部能力的稳定边界，使后续 Agent / Use Case 只依赖本项目定义的规范化 DTO 和 Protocol，而不是直接依赖 RAGFlow、文件系统实现、Sandbox 数据库字段或具体 LLM SDK。

## 新增 Port

```text
KnowledgeIngestionPort
KnowledgeRetrievalPort
KnowledgeAdminPort
ObjectStorePort
ProjectTrackerPort
JobQueuePort
StructuredLLMPort
```

## 新增测试替身

```text
FakeKnowledgePort
InMemoryObjectStore
SandboxProjectTrackerAdapter   # Task 3 仅为 in-memory contract substitute
FakeJobQueue
FakeStructuredLLM
```

真正的 PostgreSQL `SandboxProjectTrackerAdapter` 按 V3.2 计划在 Task 12 实现；Task 3 不提前写数据库查询逻辑。

## Gate 3 核心约束

上层只看到：

```text
KnowledgeChunk
ProjectIssue
StoredObject
QueuedJob
StructuredLLMRequest
```

而不是：

```text
RAGFlow dataset/chunk 原始响应
sandbox_issues SQLAlchemy row
具体 LLM SDK response
本地文件绝对路径
```

这使真实 Adapter 可以在后续逐个替换 Fake，而不修改 Agent 的业务接口。

## 运行 Task 3

```bash
conda activate it-agent
cd ~/workspace/it-outsourcing-knowledge-agent
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"
uv sync --all-groups

uv run pytest tests/contract -v
```

完整回归：

```bash
python scripts/run_checks.py
```

如果 PostgreSQL 已启动，并希望同时验证 Gate 2 在线测试：

```bash
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
export RUN_POSTGRES_INTEGRATION=1
python scripts/run_checks.py
```

## 预期 Task 3 Contract Test

应覆盖：

- Knowledge 三类 Port 的同一 Fake 实现；
- Retrieval 项目隔离；
- Object Store round-trip；
- Project Tracker 项目隔离与 request_id 幂等；
- Job 不被两个 Worker 重复领取；
- Structured LLM 使用 Pydantic response model 校验；
- DTO 不暴露 provider-specific raw fields。

## Git 提交

Gate 通过后：

```bash
git add src/project_agent/application/ports tests/fakes tests/contract scripts/run_checks.py TASK3_README.md README.md
git commit -m "feat: define compact external ports"
```
