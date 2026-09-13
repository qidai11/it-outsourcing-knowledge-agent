# Task 11 — Authority、Evidence Snapshot 与 Citation Guard

## 状态

Task 11 在 Task 10 最小知识问答 Graph 上补齐证据治理闭环：

```text
ACL-filtered Retrieval Candidates
→ AuthorityPolicy / Current-Version / Effective-Date
→ Evidence Packing
→ Frozen Evidence Snapshot
→ Grounded Claim Generation
→ Citation Guard
→ valid: Answer + Citation rows
→ invalid: at most one revision
→ still invalid: refusal
```

本阶段不实现 Issue 写操作、Reflection、多 Agent 或长期 Memory。

## 1. AuthorityPolicy

人工确认的 `authority_level` 是唯一权威来源，排序固定为：

```text
signed_scope
approved_change
requirement_baseline
approved_meeting_minutes
approved_design
approved_test_spec
release_runbook
issue_record
informal_note
```

规则：

1. Retrieval score 不能覆盖 Authority；
2. 只允许 `PUBLISHED`、当前版本、当前有效期内的文档进入正式 Evidence Pack；
3. “文档更长/更详细”不能成为权威依据；
4. 显式冲突若存在唯一更高 Authority，则低 Authority 冲突值被压制；
5. 同一最高 Authority 的显式冲突无法自动决断，必须同时保留并要求冲突披露；
6. 未解决冲突组不能因为 `max_evidence` 被截断成单边证据。

V1 的确定性冲突识别使用 Provider/上游写入的：

```text
conflict_key
claim_value
```

系统不会仅因为两段自由文本不同就武断判断“语义冲突”。

## 2. Evidence Snapshot

Task 10 的原始 Retrieval Candidate 仍保留用于审计；Task 11 会额外生成正式的 `governed_evidence` Snapshot。

每个 Snapshot 固化：

```text
Evidence label (E1/E2/...)
project_id / project_code
document_version_id
document_category / title
version_no / version_label
authority_level
lifecycle_status / is_current
effective_from / effective_to
content
content_hash
retrieval score
knowledge_space_id
provider_ref
page_no / section
conflict_key / claim_value
unresolved_conflict
```

Snapshot 保存的是本次 Run 当时看到的证据事实，不在后续文档变更时回写。
`document_version_id` 同时复制进 Snapshot metadata；即使未来源版本经过合法 Retention 物理删除，历史 Answer 仍能保留当时的版本标识和内容快照。

## 3. Evidence Packing

默认最多选择 8 条 Evidence：

```text
Authority rank ASC
→ Retrieval score DESC
→ version_no DESC
```

同一 `document_version_id + content` 去重。

若已选择的一条 Evidence 属于“未解决冲突组”，该冲突组其余最高权威成员必须一并进入 Pack，即使因此临时超过 8 条；不能只留下冲突的一侧。

## 4. Grounded Answer Schema

Task 10 的自由 `answer_text` 不再作为最终可信答案格式。

LLM 现在输出：

```json
{
  "claims": [
    {
      "text": "连续登录失败 5 次后锁定账户 30 分钟。",
      "evidence_ids": ["E1"]
    }
  ],
  "conflict_disclosure": null
}
```

Application 根据通过 Guard 的 Claim 构造最终文本：

```text
连续登录失败 5 次后锁定账户 30 分钟。 [E1]
```

因此模型不能在 `answer_text` 之外偷偷加入一段无法追踪的自由事实。

## 5. Citation Guard

Guard 是确定性代码，不是第二个“裁判 LLM”。

每条事实 Claim 必须满足：

```text
至少 1 个 Evidence ID
Evidence ID 存在于本次 Frozen Bundle
Evidence project_id == 当前 Run project_id
Evidence lifecycle == PUBLISHED
Evidence is_current == true
```

因此 Claim-level Citation Coverage 必须为：

```text
1.0 / 100%
```

以下情况失败：

```text
UNCITED_CLAIM
UNKNOWN_EVIDENCE_ID
CROSS_PROJECT_EVIDENCE
NON_CURRENT_EVIDENCE
DUPLICATE_EVIDENCE_LABEL
MISSING_CONFLICT_DISCLOSURE
NO_FACTUAL_CLAIMS
```

## 6. 冲突披露

对于：

```text
conflict_key = REQ-3.2.1.lock_minutes
E1 claim_value = 30
E2 claim_value = 60
```

且 E1/E2 都属于同一最高 Authority 时，LLM 必须输出：

```json
{
  "conflict_disclosure": {
    "text": "当前两个同等级正式证据对锁定时长存在冲突，无法确定唯一值。",
    "evidence_ids": ["E1", "E2"]
  }
}
```

缺失任一冲突侧 Evidence ID，Guard 不通过。

## 7. 最多一次 Answer Revision

```text
Draft 1
→ Citation Guard FAIL
→ Revision 1
→ Citation Guard
```

若第二次仍失败：

```text
CITATION_GUARD_FAILED
→ refusal
```

不会形成：

```text
LLM → Guard → LLM → Guard → ... 无限循环
```

## 8. Citation 持久化

通过 Guard 后：

```text
answers
  ↓
citations
  ↓
evidence_snapshots
```

`CitationModel.citation_no` 保留原 Evidence Label 数字：

```text
[E2] → citation_no = 2
```

不会因为答案只使用 E2 就错误重编号为 Citation 1。

跨项目 Citation 永远不能落库。

## 9. Graph 变化

Task 10：

```text
retrieve
→ generate_answer
→ END
```

Task 11：

```text
retrieve
→ govern_evidence
→ generate_answer
→ citation_guard
    ├─ valid → END
    ├─ first invalid → revise_answer → citation_guard
    └─ second invalid → refuse → END
```

LangGraph State 仍然只保存引用：

```text
answer_draft_id
citation_guard_id
evidence_bundle_id
answer_id
revision_count
```

不会把 Evidence/Answer 正文放入 Checkpoint。

## 10. 数据库

Task 11 **不新增业务表，不新增 Alembic Migration**。

继续复用 Task 2 已有：

```text
evidence_bundles
evidence_snapshots
answers
citations
agent_events
```

Alembic head 仍为：

```text
0003_background_job_leases
```

## 11. Gate 11

### 离线/纯业务 Gate

```bash
uv run pytest \
  tests/unit/agent/test_authority_policy.py \
  tests/unit/agent/test_evidence_snapshot.py \
  tests/unit/agent/test_citation_guard.py \
  tests/unit/agent/test_answer_revision.py \
  tests/unit/agent/test_retrieve_and_answer.py \
  tests/security/test_cross_project_citation.py \
  -v
```

### PostgreSQL Gate

```bash
export RUN_POSTGRES_INTEGRATION=1

uv run pytest \
  tests/integration/evidence \
  -v
```

验证：

- Authority/Document Version metadata 来自 PostgreSQL；
- 同 Document 只有最高 `PUBLISHED version_no` 被标记 current；
- Frozen Snapshot 可持久化；
- Citation 正确引用 `evidence_snapshot_id`；
- 源 Document Version 后续删除时 Snapshot 仍保留冻结版本 ID。

### 完整回归

```bash
python scripts/run_checks.py
```

## 12. 提交

```bash
git add .
git commit -m "feat: add authority and citation guard"
```
