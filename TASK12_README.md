# Task 12 — Sandbox ProjectTracker Adapter 与 Issue 候选查询

## 状态与边界

Task 12 实现 V1 的第二条业务主链的只读阶段：

```text
已授权 Project Scope
→ SandboxProjectTrackerAdapter
→ 同项目历史 Issue
→ deterministic possible-duplicate ranking
→ ISSUE_CANDIDATES artifact
→ 用户选择：查看 / 关联 / 继续创建 / 取消
```

本阶段**不会创建 Issue，也不会自动判定 duplicate**。

V3.2 将真正的 `IssueDraft` 持久化、LangGraph interrupt 用户确认、
`client_request_id` 幂等和未知结果恢复留给 Task 13。

## 1. PostgreSQL Sandbox Adapter

真实 Adapter：

```text
src/project_agent/infrastructure/project_tracker/sandbox.py
```

实现 `ProjectTrackerPort`：

```text
search_issues
create_issue                # 仅底层能力，Task 12 node 不可达
get_issue_by_request_id     # 为 Task 13 对账预留
```

`search_issues()` 的第一条件永远是：

```text
sandbox_issues.project_id = 当前项目
```

然后才允许附加：

```text
error_code
module
status
title / description keyword
limit
```

因此同样的 `ERR-IMPORT-004` 即使同时存在 Alpha/Beta，也不会跨项目返回。

## 2. Candidate Ranking

排序是确定性 lexicographic priority：

```text
1. exact error code
2. exact module
3. title keyword overlap
4. description keyword overlap
5. status
6. optional semantic score
7. created_at recency tie-break
```

可选 semantic score 只能在更高优先级规则相同时微调，不能覆盖 error code/module。

输出名称固定为：

```text
possible_duplicates
```

禁止输出：

```text
duplicate=true
```

## 3. 用户选项

即使候选高度相似，也始终返回四个选项：

```text
view_existing_issue
link_existing_issue
continue_create
cancel
```

因此 Task 12 不会因为 AI/规则认为“很像”就阻止创建新 Issue，也不会自动关闭任何历史 Issue。

## 4. Agent Node

```text
src/project_agent/agent/nodes/search_issues.py
```

Node 必须先看到 Task 9 生成的 `access_scope_id`。

```text
no access_scope_id
→ refusal
→ PROJECT_SCOPE_REQUIRED
```

只有 `state.project_id` 确实属于当前 `ProjectAccessScope.allowed_project_ids` 才会发出 Sandbox 查询。

完整 Issue 列表不放进 LangGraph State；Node 只保存：

```text
issue_candidate_id
```

实际 candidate payload 落入 `agent_events` artifact。

## 5. 两项目 Seed

执行：

```bash
uv run python scripts/seed_sandbox_issues.py
```

会创建/复用：

```text
PRJ-RETAIL-ALPHA
PRJ-LOGISTICS-BETA
```

并 Seed：

```text
Alpha:
ALPHA-101  ERR-IMPORT-004 / import / OPEN
ALPHA-102  ERR-IMPORT-004 / import / RESOLVED / different root cause
ALPHA-103  ERR-IMPORT-005 / import / OPEN

Beta:
BETA-201   ERR-IMPORT-004 / import / OPEN
BETA-202   ERR-SETTLE-009 / settlement / IN_PROGRESS
```

故意复用错误码和相似标题，用于验证跨项目隔离与“相似并不等于 duplicate”。

## 6. Gate 12

离线：

```bash
uv run pytest tests/contract/project_tracker tests/e2e/test_issue_candidates.py -v
```

真实 PostgreSQL：

```bash
export RUN_POSTGRES_INTEGRATION=1
uv run pytest tests/contract/project_tracker -v
```

核心 Gate：

```text
cross-project Issue result = 0
automatic duplicate decision = 0
automatic Issue create side effect = 0
continue_create option always available
```

## 7. Task 13 接口

Task 13 将在本阶段结果之后增加：

```text
possible_duplicates
→ IssueDraft
→ permission re-check
→ explicit confirmation / interrupt
→ idempotency_records
→ Sandbox create_issue
→ response-lost reconciliation
```
