# Task 6 — 文档上传、人工元数据与发布

## 状态

```text
TASK6_IMPLEMENTATION = COMPLETE
TASK6_GATE            = PASS (Fake provider / application workflow)
LIVE_POSTGRES_GATE    = 由开发机 RUN_POSTGRES_INTEGRATION=1 验证
LIVE_RAGFLOW_GATE     = 由开发机 RUN_RAGFLOW_INTEGRATION=1 验证
```

Task 6 的核心原则：**AI/规则只能建议元数据，最终项目、文档类型、版本、权威等级和发布行为都由人确认。**

## 新增能力

```text
原始文件
  ↓
LocalFileObjectStoreAdapter / ObjectStorePort
  ↓
人工确认元数据
  ↓
DRAFT
  ↓
UNDER_REVIEW
  ↓ 文档负责人
APPROVED
  ↓ 授权 publisher
RAGFlow ingest / parse
  ├─ FAILED  → 新版本保持 APPROVED；旧 PUBLISHED 继续可用
  ├─ RUNNING → 返回 ingestion_job_id；不重复上传
  └─ SUCCEEDED
       ↓
       新版本 PUBLISHED
       旧版本 SUPERSEDED
```

删除流程：

```text
PUBLISHED / 其他可删除状态
  ↓
DELETE_PENDING   ← 先持久化，立即失去 online-retrievable 资格
  ↓
RAGFlow cleanup
  ↓
后续 Retention Worker 再处理物理源文件删除
```

## 主要文件

```text
src/project_agent/application/ports/document_repository.py
src/project_agent/application/services/metadata_suggestion.py
src/project_agent/application/use_cases/upload_document.py
src/project_agent/application/use_cases/review_document.py
src/project_agent/application/use_cases/publish_document.py
src/project_agent/application/use_cases/delete_document.py
src/project_agent/infrastructure/db/repositories/documents.py
src/project_agent/api/v1/documents.py

tests/unit/documents/test_metadata_suggestion.py
tests/e2e/test_document_lifecycle.py
tests/fakes/document_repository.py
```

## MetadataSuggestion 输入

当前 Task 6 使用确定性基线，不调用真实 LLM。输入包括：

```text
filename
preview_text     # 首页/前若干段
project_id
project_code
existing_versions
```

输出沿用设计文档：

```text
suggested_project_id
suggested_document_category
suggested_version_label
suggested_authority_level
suggested_effective_from
suggested_supersedes_version_id
confidence
evidence
```

低于置信度阈值的字段保持 `None`。

注意：`MetadataSuggestion` **没有** `lifecycle_status`、`confirmed_by` 或 `publish` 能力。

## 人工确认记录

上传 API/Use Case 强制最终字段：

```text
project_id
document_category
version_label
authority_level
```

最终选择不从 Suggestion 自动复制；调用者必须提交人工确认值。

保存到：

```text
documents / document_versions      最终业务事实
audit_logs.details_json            suggestion + confidence + final + confirmed_by
```

因此后续可以复盘：

```text
AI/规则建议了什么？
置信度多少？
人最后选了什么？
是谁确认的？
```

## PostgreSQL Repository

`SqlAlchemyDocumentWorkflowRepository` 复用 Task 2 已有表，不新增迁移：

```text
documents
document_versions
project_knowledge_spaces
audit_logs
```

`complete_publication()` 会：

1. `SELECT ... FOR UPDATE` 锁定新版本；
2. 如果有 `supersedes_version_id`，同时锁定旧版本；
3. 确认新版本仍是 `APPROVED`；
4. 确认旧版本仍是 `PUBLISHED` 且属于同一 Document；
5. 新版本设 `PUBLISHED`；
6. 旧版本设 `SUPERSEDED`；
7. 在调用方 AsyncSession 事务内一起提交。

## API 边界

新增路由：

```text
POST   /api/v1/documents
POST   /api/v1/documents/{version_id}/submit-review
POST   /api/v1/documents/{version_id}/approve
POST   /api/v1/documents/{version_id}/publish
DELETE /api/v1/documents/{version_id}
```

Task 6 **没有伪造认证系统**。Actor 通过 App/Request state 注入用于测试和后续组合；Task 9 会替换为 JWT 身份 + PostgreSQL Membership 授权。

如果没有注入 `DocumentApiServices`，文档 API 返回 `503`，不会使用不可信请求体里的 `role` 作为权限。

## Gate 6

专项命令：

```bash
uv run pytest \
  tests/unit/documents/test_metadata_suggestion.py \
  tests/e2e/test_document_lifecycle.py \
  -v
```

当前生成版本验证结果：

```text
10 passed
```

覆盖：

- 强制人工元数据；
- 上传只能创建 DRAFT；
- 低置信度建议留空；
- 建议不能设置 lifecycle/publish；
- 人工最终值覆盖 Suggestion；
- Suggestion、confidence、final、confirmed_by 可审计；
- 上传者提交审核；
- 只有文档负责人可 APPROVE；
- 只有 `publish_document` 权限可 PUBLISH；
- 新版本解析失败不影响旧版；
- 解析成功后才 supersede 旧版；
- RUNNING 解析可按原 ingestion_job_id finalize，不重复上传；
- DELETE_PENDING 先于 Provider cleanup 生效。

## 应用增量包

```bash
conda activate it-agent
cd ~/workspace/it-outsourcing-knowledge-agent

unzip -o \
  ~/workspace/task6_document_publication_increment.zip \
  -d ~/workspace/it-outsourcing-knowledge-agent
```

Task 6 不新增第三方依赖，但建议同步环境：

```bash
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"
uv sync --all-groups
```

## 完整质量门禁

如果 PostgreSQL 和 RAGFlow 在线：

```bash
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
export RUN_POSTGRES_INTEGRATION=1
export RUN_RAGFLOW_INTEGRATION=1

python scripts/run_checks.py
```

如果当前只验证 Task 6 代码，不启用在线依赖：

```bash
uv run pytest \
  tests/unit/documents/test_metadata_suggestion.py \
  tests/e2e/test_document_lifecycle.py \
  -v
```

## 提交

所有你本机的 Ruff / MyPy / PostgreSQL / RAGFlow Gate 通过后：

```bash
git add \
  src/project_agent/application/ports/document_repository.py \
  src/project_agent/application/services/metadata_suggestion.py \
  src/project_agent/application/use_cases \
  src/project_agent/infrastructure/db/repositories \
  src/project_agent/api/v1/documents.py \
  src/project_agent/main.py \
  src/project_agent/domain/enums.py \
  tests/fakes \
  tests/unit/documents \
  tests/e2e \
  scripts/run_checks.py \
  README.md \
  TASK6_README.md

git commit -m "feat: add human governed document publication"
```

## 下一步

Task 7：Identifier Extraction 与 Registry。

Task 7 才把：

```text
REQ-3.2.1
/api/v1/import
t_order_detail
ERR-IMPORT-004
v1.8.3
```

从已发布文档中做确定性提取、标准化和 PostgreSQL B-tree 精确注册。
