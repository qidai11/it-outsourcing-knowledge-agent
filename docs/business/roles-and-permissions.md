# Roles and Permissions Matrix

> 版本：v0.1  
> 目的：冻结 V1 项目权限矩阵。  
> 注意：`company_admin` 是系统级角色，不属于 `ProjectMembership.role` 枚举。

## 1. ProjectMembership 角色

```text
project_manager
developer
qa
implementation
support
viewer
```

## 2. 系统级角色

```text
company_admin
```

`company_admin` 用于系统配置、公司级审计和应急治理，不代表可以绕过所有项目数据隔离。其跨项目读取必须作为明确的管理操作并记录审计。

## 3. 权限定义

| permission | 说明 |
|---|---|
| `query_knowledge` | 发起项目知识查询 |
| `view_source` | 查看有权限的引用源文档 |
| `search_issue` | 查询本项目 Sandbox Issue |
| `create_issue_draft` | 生成 Issue Draft |
| `create_issue` | 确认后创建 Sandbox Issue |
| `upload_document` | 上传源文件并形成 DRAFT |
| `edit_document_metadata` | 编辑人工元数据 |
| `submit_review` | 提交审核 |
| `approve_document` | 审核通过 |
| `publish_document` | 发布为 PUBLISHED |
| `archive_document` | 归档/发起下线 |
| `manage_members` | 管理项目成员 |
| `view_audit` | 查看项目审计 |
| `manage_system_config` | 修改系统级 Prompt/限流/保留策略 |

## 4. 权限矩阵

符号：`Y` 允许，`N` 不允许，`C` 条件允许。

| Permission | PM | Developer | QA | Implementation | Support | Viewer | Company Admin |
|---|---:|---:|---:|---:|---:|---:|---:|
| query_knowledge | Y | Y | Y | Y | Y | Y | C |
| view_source | Y | Y | Y | Y | Y | Y | C |
| search_issue | Y | Y | Y | Y | Y | Y | C |
| create_issue_draft | Y | Y | Y | Y | Y | N | C |
| create_issue | Y | Y | Y | Y | Y | N | C |
| upload_document | Y | Y | Y | Y | Y | N | C |
| edit_document_metadata | Y | C | C | C | C | N | C |
| submit_review | Y | Y | Y | Y | Y | N | C |
| approve_document | Y | N | N | N | N | N | C |
| publish_document | Y | N | N | N | N | N | C |
| archive_document | Y | N | N | N | N | N | C |
| manage_members | Y | N | N | N | N | N | C |
| view_audit | Y | N | N | N | N | N | Y |
| manage_system_config | N | N | N | N | N | N | Y |

### 条件权限说明

- 普通成员只有在被指定为该文档 `owner_user_id` 或具有明确委派时，才可以编辑正式元数据；
- `company_admin` 的项目数据读取必须有管理原因并记录 Audit Event；
- 所有权限都需要满足 `ProjectMembership.valid_from <= now < valid_to`（若 `valid_to` 不为空）；
- 用户不能通过请求体传入更高角色覆盖服务端身份。

## 5. 示例测试身份

| user_id | Alpha | Beta | 用途 |
|---|---|---|---|
| `u-admin` | company_admin | company_admin | 系统治理 |
| `u-alpha-pm` | project_manager | 无成员关系 | Alpha 发布、成员管理 |
| `u-alpha-dev` | developer | 无成员关系 | Alpha 查询与 Issue |
| `u-alpha-qa` | qa | 无成员关系 | Alpha 测试 |
| `u-beta-pm` | 无成员关系 | project_manager | Beta 管理 |
| `u-beta-dev` | 无成员关系 | developer | Beta 查询 |
| `u-beta-qa` | 无成员关系 | qa | Beta 查询 |
| `u-alpha-viewer` | viewer | 无成员关系 | 只读测试 |
| `u-expired` | 已过期 developer | 无成员关系 | 成员有效期测试 |
| `u-outsider` | 无成员关系 | 无成员关系 | 越权测试 |

## 6. 关键安全规则

1. 项目访问权限必须在检索前计算；
2. 检索结果返回后还要进行 Evidence ACL 后置校验；
3. Citation 必须属于当前 Run、当前项目和当前用户允许的文档版本；
4. 过期成员按无权限处理；
5. `viewer` 不能创建 Issue；
6. 没有 `create_issue` 权限时，即使 LLM 生成了 Draft，也不能触发写工具；
7. 任何外部文本都不能改变服务端计算出的角色和项目范围。
