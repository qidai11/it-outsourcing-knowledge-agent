# Sandbox Issue Schema and Workflow

> 版本：v0.1  
> 适配器：`SandboxProjectTrackerAdapter`

## 1. 真实性边界

V1 不连接真实生产 Jira、禅道、飞书项目或其他生产项目管理系统。

Sandbox 只用于验证：

- Issue 查询；
- 疑似重复候选；
- Issue Draft；
- 用户确认；
- 幂等创建；
- 创建后未知结果恢复；
- 权限拒绝；
- 故障注入。

## 2. Sandbox Issue 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `id` | UUID | Y | 内部主键 |
| `project_id` | UUID | Y | 强制项目隔离 |
| `issue_key` | string | Y | 如 `ALPHA-102` |
| `title` | string | Y | 标题 |
| `description` | text | Y | 描述 |
| `issue_type` | enum | Y | bug/task/support |
| `priority` | enum | Y | low/medium/high/critical |
| `status` | enum | Y | OPEN/IN_PROGRESS/RESOLVED/CLOSED/REOPENED |
| `module` | string | N | 模块 |
| `error_code` | string | N | 错误码 |
| `environment` | string | N | dev/test/uat/staging 等 |
| `reporter_id` | UUID | Y | 报告人 |
| `assignee_id` | UUID | N | 处理人 |
| `source` | string | Y | 固定 `sandbox` |
| `client_request_id` | string | N | 幂等请求号 |
| `created_at` | datetime | Y | 创建时间 |
| `updated_at` | datetime | Y | 更新时间 |

唯一约束：

```text
(project_id, issue_key)
(namespace, client_request_id)
```

## 3. Issue Draft

```text
project_id
title
description
issue_type
proposed_priority
module
environment
reproduction_steps[]
expected_behavior
actual_behavior
evidence_ids[]
possible_duplicate_issue_keys[]
```

Draft 不是 Issue，不产生外部副作用。

## 4. Issue 状态

```text
OPEN
→ IN_PROGRESS
→ RESOLVED
→ CLOSED

RESOLVED / CLOSED
→ REOPENED
→ IN_PROGRESS
```

V1 不让 LLM 自主改变状态。

## 5. 疑似重复候选

候选检索限定为：

```text
same project
+ error_code
+ module
+ title keywords
+ description keywords
+ status
+ created_at
+ optional semantic similarity for ranking
```

系统输出字段使用：

```text
possible_duplicates
```

禁止：

```text
duplicate=true
```

用户决策：

```text
查看现有 Issue
关联到现有 Issue
继续创建
取消
```

## 6. 创建确认

普通创建：

```text
Issue Draft
→ 检查 create_issue 权限
→ 展示最终字段
→ 用户明确确认
→ 创建 IN_PROGRESS 幂等记录
→ Sandbox create_issue
→ 保存 issue_key
→ SUCCEEDED
```

没有确认时：

```text
sandbox_issue_create_total 不增加
```

## 7. 升级确认

以下情况必须升级确认或阻止自动继续：

- `critical`；
- 客户可见（V1 默认不支持）；
- 发布阻塞；
- 含敏感数据；
- 涉及变更范围或交付计划。

## 8. 创建后响应丢失

```text
create_issue 已可能成功
→ 响应丢失
→ get_issue_by_request_id(project_id, client_request_id)
→ 找到：回填成功
→ 未找到且能确认未执行：最多重试一次
→ 无法确认：REQUIRES_RECONCILIATION
```

## 9. 故障注入场景

Sandbox 必须支持：

- 查询超时；
- 创建前失败；
- 创建成功后响应丢失；
- 重复 `client_request_id`；
- 项目无权限；
- 返回字段缺失；
- Issue 已关闭；
- 数据库暂时失败。

## 10. 权限

默认具有 `create_issue` 的角色：

```text
project_manager
developer
qa
implementation
support
```

`viewer` 不允许创建。

任何角色都必须先有有效的当前项目 Membership。
