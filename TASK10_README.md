# Task 10 — 最小知识问答 Graph

## 状态

Task 10 把 Task 5/7/8/9 的能力第一次串成最小项目知识问答工作流：

```text
Run reference
→ Prompt Snapshot
→ Query Analysis
→ Project Selection
→ ProjectAccessScope
→ Exact Identifier Resolver
→ Retrieval Plan
→ RAGFlow Retrieval
→ ACL Post-filter
→ No-Evidence Refusal / Answer Generation
```

Task 11 才实现 AuthorityPolicy、正式 Evidence Snapshot 语义和 Citation Guard；Task 10 不提前宣称引用已验证。

## LangGraph 基线

项目依赖：

```text
langgraph >= 1.2.10, < 1.3
langgraph-checkpoint-postgres >= 3.1.1, < 3.2
psycopg[binary] >= 3.2, < 4
```

生产/开发运行使用 `StateGraph`，Checkpoint 使用 `AsyncPostgresSaver`。

安全要求：

```text
LANGGRAPH_STRICT_MSGPACK=true
```

`async_postgres_saver()` 会在导入 checkpointer 前设置该值，并调用 `setup()` 初始化 LangGraph 自己的 checkpoint tables。

## Graph State

State 只保存引用和小型控制字段：

```text
run_id
thread_id
user_id
project_id
prompt_snapshot_id
query_analysis_id
project_selection_id
access_scope_id
retrieval_plan_id
evidence_bundle_id
answer_id
route
last_error_code
```

不会把这些内容塞进 checkpoint：

```text
完整 query text
完整 prompt
完整 Evidence
完整 Tool Result
完整 answer text
```

## Query Analysis

确定性提取并保留：

```text
PRJ-ERP-2026
REQ-3.2.1
BUG-1842
/api/v2/import
customer_id
t_order_detail
E1027
v1.8.3
```

最小版本暂不做 LLM Query Rewrite，因此：

```text
standalone_query = original query
```

这样 Exact Identifier 不会因为 Rewrite 被改写。

## 项目选择

顺序：

1. 调用方显式给出 `project_id`：必须属于当前用户有效 Membership；
2. Query 中出现唯一 Project Code：只能匹配当前用户有权项目；
3. Query 无项目，但用户只有一个有效项目：自动选择；
4. Query 无项目且用户有多个项目：返回 clarification，不执行 Retrieval；
5. Query 指向无权限项目：拒绝。

## Exact Identifier

先走 Task 7 Registry：

```text
(project_id, identifier_type, normalized_value)
```

只有“当前授权 PUBLISHED 集合中唯一命中”的 Identifier 才收窄 Retrieval 文档范围。

例如 Registry 同时保存：

```text
REQ-3.2.1 -> Alpha current version
REQ-3.2.1 -> Alpha old version
```

如果 Scope 只允许 current version，则唯一授权命中仍然是 current version。

多个精确 Identifier 分别唯一命中不同文档时，使用这些文档版本的并集。

无 Exact Hit 时不伪造命中，回退到当前授权文档集合的 Hybrid Retrieval。

## Retrieval

Task 9 `ProjectAccessPolicy` 在 Provider 前后各执行一次：

```text
RetrievalPlan
→ allowed document versions / Dataset down-push
→ KnowledgeRetrievalPort
→ project + version + Dataset post-filter
```

没有授权 Evidence：

```text
NO_AUTHORIZED_EVIDENCE
```

直接拒答，不调用 LLM。

## Prompt Snapshot 与 Token

Run 第一节点加载：

```text
prompt.qa.answer
```

并把：

```text
model_alias
prompt_version
prompt_content_hash
```

保存到 `agent_runs`。

具体 Prompt Snapshot 作为 Agent Event 持久化，State 只保存 Event ID。

LLM Adapter 通过 `StructuredLLMUsagePort` 返回：

```text
input_tokens
output_tokens
```

累计进 `agent_runs`。

## PostgreSQL Store

`SqlAlchemyQAGraphStore` 复用现有表，不新增业务 Migration：

```text
agent_runs
agent_events
evidence_bundles
evidence_snapshots
answers
```

Task 10 的 Evidence Snapshot 仅作为“授权后的原始 Retrieval Candidate 持久化”，Task 11 再加入 Authority、Packing、Citation Guard 的正式语义。

## Gate 10

先同步依赖：

```bash
conda activate it-agent
cd ~/workspace/it-outsourcing-knowledge-agent
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"
uv lock
uv sync --all-groups
```

专项测试：

```bash
uv run pytest \
  tests/unit/agent/test_query_analysis.py \
  tests/unit/agent/test_exact_resolver.py \
  tests/unit/agent/test_project_selection.py \
  tests/unit/agent/test_retrieve_and_answer.py \
  tests/unit/agent/test_state_references.py \
  tests/unit/agent/test_checkpoint_config.py \
  tests/e2e/test_project_qa.py \
  -v
```

期望：

- Exact Identifier 原文保留；
- Alpha/Beta 同编号不串项目；
- Unique authorized exact hit 收窄文档；
- 多项目无 project 时澄清；
- 无 Evidence 拒答且 LLM 调用数为 0；
- Prompt Version/Hash 被记录；
- input/output Token 被记录；
- State 不保存大对象。

真实 PostgreSQL Checkpoint Gate：

```bash
export RUN_POSTGRES_INTEGRATION=1
uv run pytest tests/integration/agent/test_postgres_checkpointer.py -v
```

然后运行总门禁：

```bash
python scripts/run_checks.py
```

## 提交

```bash
git add .
git commit -m "feat: add exact aware project qa graph"
```
