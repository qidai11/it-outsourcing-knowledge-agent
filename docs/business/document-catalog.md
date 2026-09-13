# Document Catalog and Authority Policy

> 版本：v0.1

## 1. V1 文档类型

| document_category | 中文含义 | 常见 Identifier |
|---|---|---|
| `requirement_baseline` | 需求基线 | REQ 编号、版本号 |
| `approved_design` | 已批准设计 | 模块名、表名、字段名 |
| `api_specification` | API 接口文档 | API 路径、错误码、字段名 |
| `database_design` | 数据库设计 | 表名、字段名、索引名 |
| `approved_test_spec` | 测试/验收规范 | TC 编号、验收条件 |
| `release_runbook` | 发布/部署手册 | 版本号、配置项 |
| `approved_meeting_minutes` | 已确认会议纪要 | CR 编号、决定事项 |
| `issue_record` | 历史问题记录 | Issue Key、错误码 |

`informal_note` 作为 Authority Level 保留，但 V1 不把它当作正式项目文档 Category 的主类型。

## 2. AuthorityPolicy

由高到低：

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

1. 权威等级由人工选择；
2. LLM 可以提出 `MetadataSuggestion`，不能自动发布；
3. 相同主题发生冲突时，优先比较项目、当前有效性、版本替代关系和 Authority；
4. 不能仅凭文档“写得更详细”判断更权威；
5. 冲突无法确定时必须披露冲突，不能由模型自行选一个答案。

## 3. 模拟项目文档清单

### `company-public`

| doc_code | category | authority | current |
|---|---|---|---|
| CP-DEV-001 | approved_design | approved_design | yes |
| CP-REL-001 | release_runbook | release_runbook | yes |
| CP-ISSUE-001 | issue_record | issue_record | yes |

### `PRJ-RETAIL-ALPHA`

| doc_code | category | version | authority | planned_status |
|---|---|---|---|---|
| A-REQ-001 | requirement_baseline | 2.1 | requirement_baseline | PUBLISHED |
| A-REQ-001-OLD | requirement_baseline | 2.0 | requirement_baseline | SUPERSEDED |
| A-API-001 | api_specification | 1.4 | approved_design | PUBLISHED |
| A-DB-001 | database_design | 1.3 | approved_design | PUBLISHED |
| A-TEST-001 | approved_test_spec | 1.2 | approved_test_spec | PUBLISHED |
| A-REL-001 | release_runbook | v1.8.3 | release_runbook | PUBLISHED |
| A-MIN-001 | approved_meeting_minutes | 2026-07-18 | approved_meeting_minutes | PUBLISHED |
| A-ISSUE-001 | issue_record | current | issue_record | PUBLISHED |
| A-DRAFT-001 | requirement_baseline | 2.2-draft | requirement_baseline | DRAFT |
| A-DEL-001 | issue_record | legacy | issue_record | DELETE_PENDING |

### `PRJ-LOGISTICS-BETA`

| doc_code | category | version | authority | planned_status |
|---|---|---|---|---|
| B-REQ-001 | requirement_baseline | 1.6 | requirement_baseline | PUBLISHED |
| B-REQ-001-OLD | requirement_baseline | 1.5 | requirement_baseline | SUPERSEDED |
| B-API-001 | api_specification | 2.0 | approved_design | PUBLISHED |
| B-DB-001 | database_design | 1.1 | approved_design | PUBLISHED |
| B-TEST-001 | approved_test_spec | 1.0 | approved_test_spec | PUBLISHED |
| B-REL-001 | release_runbook | v2.4.0 | release_runbook | PUBLISHED |
| B-MIN-001 | approved_meeting_minutes | 2026-07-22 | approved_meeting_minutes | PUBLISHED |
| B-ISSUE-001 | issue_record | current | issue_record | PUBLISHED |
| B-DRAFT-001 | api_specification | 2.1-draft | approved_design | UNDER_REVIEW |

## 4. Identifier 冲突测试

以下 Identifier 故意同时存在于 Alpha 和 Beta：

```text
REQ-3.2.1
/api/v1/import
t_order_detail
ERR-IMPORT-004
```

系统必须使用：

```text
project_id + identifier_type + normalized_value
```

进行精确解析。

## 5. 人工元数据

每个上传文档至少维护：

```text
project_id
document_category
title
version_label
authority_level
lifecycle_status
visibility
effective_from
effective_to
supersedes_version_id
owner_user_id
```

V1 默认：

```text
visibility = internal_only
```
