# Document Lifecycle

> 版本：v0.1

## 1. 状态集合

```text
DRAFT
UNDER_REVIEW
APPROVED
PUBLISHED
SUPERSEDED
ARCHIVED
DELETE_PENDING
DELETED
```

## 2. 核心不变量

**只有 `PUBLISHED` 可以进入知识检索。**

以下状态召回必须为 0：

```text
DRAFT
UNDER_REVIEW
APPROVED
SUPERSEDED
ARCHIVED
DELETE_PENDING
DELETED
```

## 3. 标准发布流程

```text
普通成员上传
    ↓
DRAFT
    ↓ submit_review
UNDER_REVIEW
    ↓ approve
APPROVED
    ↓ publish
PUBLISHED
```

## 4. 版本替代

```text
旧版本：PUBLISHED
新版本：APPROVED
    ↓ publish new version
新版本：PUBLISHED
旧版本：SUPERSEDED
```

替代操作需要在同一事务或可恢复业务操作中完成，避免同时出现两个“当前正式版本”。

## 5. 归档

当文档不再作为当前交付依据，但仍需保留历史：

```text
PUBLISHED / SUPERSEDED
→ ARCHIVED
```

归档文档不可进入普通检索，但可在具有明确历史查询意图、且应用层授权的专用历史流程中访问；V1 默认知识问答不检索 ARCHIVED。

## 6. 删除

逻辑流程：

```text
任一允许删除的非 DELETED 状态
→ DELETE_PENDING
→ 立即退出在线检索范围
→ 检查 retention policy
→ 检查 archive_before_delete
→ 检查 legal_hold
→ 写审计
→ 删除 RAGFlow 在线索引
→ 删除/归档源文件
→ DELETED
```

`legal_hold=true` 时禁止物理删除。

## 7. 允许的主要状态转换

| From | Action | To | Actor |
|---|---|---|---|
| DRAFT | submit_review | UNDER_REVIEW | uploader/owner |
| UNDER_REVIEW | request_changes | DRAFT | project_manager / reviewer |
| UNDER_REVIEW | approve | APPROVED | project_manager / delegated reviewer |
| APPROVED | publish | PUBLISHED | project_manager / authorized publisher |
| APPROVED | request_changes | DRAFT | reviewer |
| PUBLISHED | supersede | SUPERSEDED | system under authorized publish |
| PUBLISHED | archive | ARCHIVED | project_manager |
| SUPERSEDED | archive | ARCHIVED | project_manager |
| DRAFT | delete | DELETE_PENDING | owner / project_manager |
| UNDER_REVIEW | delete | DELETE_PENDING | project_manager |
| APPROVED | delete | DELETE_PENDING | project_manager |
| PUBLISHED | delete | DELETE_PENDING | project_manager |
| SUPERSEDED | delete | DELETE_PENDING | project_manager |
| ARCHIVED | delete | DELETE_PENDING | project_manager |
| DELETE_PENDING | physical_delete | DELETED | worker after policy checks |

## 8. 禁止转换

示例：

```text
DRAFT -> PUBLISHED               禁止跳过审核
UNDER_REVIEW -> PUBLISHED        禁止
DELETED -> PUBLISHED             禁止
DELETE_PENDING -> PUBLISHED      禁止
LLM -> PUBLISHED                 禁止
```

## 9. MetadataSuggestion

AI 只能预填：

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

人工确认后才能保存正式元数据。AI 的建议值与最终值都应进入审计。
