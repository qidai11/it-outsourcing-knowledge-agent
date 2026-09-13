# Task 2 — PostgreSQL Schema 与领域模型

## 1. 本阶段目标

Task 2 只完成：

- 领域枚举与规则；
- 文档生命周期转换；
- ProjectMembership 有效期；
- SQLAlchemy 2 ORM Schema；
- PostgreSQL 16 本地开发容器；
- Alembic 初始迁移；
- Schema/约束/索引测试；
- CI 中的 PostgreSQL Gate。

本阶段**不实现** Repository、Ports、RAGFlow、LangGraph 业务工作流、真实 LLM。

## 2. Required tables

共 28 张业务表：

```text
clients
projects
project_memberships
project_knowledge_spaces
documents
document_versions
document_acl_bindings
document_identifiers
ingestion_jobs
ingestion_audits
background_jobs
threads
agent_runs
agent_events
evidence_bundles
evidence_snapshots
answers
citations
issue_drafts
issue_candidates
sandbox_projects
sandbox_issues
sandbox_issue_events
tool_confirmations
idempotency_records
audit_logs
system_configs
data_retention_policies
```

## 3. 关键唯一约束

```text
projects(company_id, code)
document_versions(document_id, version_no)
document_identifiers(project_id, identifier_type, normalized_value, document_version_id)
agent_events(run_id, sequence_no)
idempotency_records(namespace, request_id)
sandbox_issues(project_id, issue_key)
```

## 4. Exact Identifier 索引

```sql
CREATE INDEX idx_identifier_exact
ON document_identifiers (
    project_id,
    identifier_type,
    normalized_value
);
```

`pg_trgm` 仍保持可选，不在 0001 migration 中强制启用。

## 5. 领域不变量

### Document

只有：

```text
PUBLISHED
```

可以作为在线检索 Evidence。

禁止：

```text
DRAFT -> PUBLISHED
UNDER_REVIEW -> PUBLISHED
DELETE_PENDING -> PUBLISHED
DELETED -> PUBLISHED
```

### ProjectMembership

有效条件：

```text
valid_from <= now < valid_to
```

`valid_to = NULL` 表示没有结束时间。

### V1 默认值

```text
projects.delivery_mode = internal_only
projects.lifecycle_status = ACTIVE
documents.visibility = internal_only
```

## 6. 安装

```bash
conda activate it-agent
cd ~/workspace/it-outsourcing-knowledge-agent

export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"

uv lock
uv sync --all-groups
```

Task 2 新增主要依赖：

```text
SQLAlchemy 2 Async
asyncpg
Alembic
```

## 7. 启动 PostgreSQL

```bash
docker compose up -d postgres
```

检查：

```bash
docker compose ps
docker compose logs --tail=50 postgres
```

预期 PostgreSQL 为 `healthy`。

默认连接：

```text
postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent
```

## 8. 执行 Alembic Migration

```bash
uv run alembic current
uv run alembic heads
uv run alembic upgrade head
uv run alembic current
```

最终应显示：

```text
0001_initial (head)
```

查看表：

```bash
docker compose exec postgres \
  psql -U project_agent -d project_agent -c '\dt'
```

查看 Exact Identifier 索引：

```bash
docker compose exec postgres \
  psql -U project_agent -d project_agent \
  -c "SELECT indexname, indexdef FROM pg_indexes WHERE indexname='idx_identifier_exact';"
```

## 9. Gate 2 单独测试

先确认数据库已经迁移：

```bash
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
export RUN_POSTGRES_INTEGRATION=1
```

然后：

```bash
uv run pytest tests/unit/domain tests/integration/db -v
```

这里 `RUN_POSTGRES_INTEGRATION=1` 很重要。

没有它时，真实 PostgreSQL 测试会显示 skip；**skip 不能算 Gate 2 完成**。

## 10. 完整质量门禁

```bash
export RUN_POSTGRES_INTEGRATION=1
python scripts/run_checks.py
```

它会执行：

```text
Task 0 validator
Ruff
MyPy
全部 unit tests
Task 1 API integration tests
Task 2 DB metadata tests
Task 2 PostgreSQL live schema test
```

## 11. 停止数据库

保留数据：

```bash
docker compose stop postgres
```

重新启动：

```bash
docker compose start postgres
```

完全删除测试数据库：

```bash
docker compose down -v
```

注意：`-v` 会删除 PostgreSQL volume，仅在确认不需要当前开发数据时使用。

## 12. 推荐提交

全部 Gate 2 通过后：

```bash
git status

git add \
  pyproject.toml \
  alembic.ini \
  compose.yaml \
  migrations \
  src/project_agent/domain \
  src/project_agent/infrastructure \
  tests/unit/domain \
  tests/integration/db \
  scripts/run_checks.py \
  .github/workflows/ci.yml \
  TASK2_README.md

git commit -m "feat: add compact business persistence model"
```

## 13. Gate 2 完成标准

只有以下均满足，才记为 Task 2 完成：

- [ ] 28 张业务表迁移成功；
- [ ] `alembic current` 为 `0001_initial (head)`；
- [ ] 6 个指定唯一约束存在；
- [ ] `idx_identifier_exact` 存在且列顺序正确；
- [ ] 文档生命周期测试通过；
- [ ] 成员有效期测试通过；
- [ ] Agent Run 使用量/Prompt/成本字段存在；
- [ ] system_configs 存在；
- [ ] data_retention_policies 存在；
- [ ] Ruff 通过；
- [ ] MyPy 通过；
- [ ] PostgreSQL live integration test **不是 skip** 且通过；
- [ ] Task 0、Task 1 回归继续通过。
