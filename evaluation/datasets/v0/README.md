# Evaluation Dataset v0

## 说明

当前数据集是 **模拟开发基线**，不是公司真实高频问题集。

- 总问题数：50
- 开发/普通测试：35
- P0 安全回归：15
- 覆盖两个项目和公共知识域
- 故意复用相同 Identifier 以测试跨项目隔离

## 使用规则

1. Task 1～5 可以直接用本集写测试；
2. 接入真实脱敏业务后，不删除 v0，而是新增 v1；
3. 真正的“真实高频问题 ≥30”必须来自后续角色访谈；
4. 任何评测数字必须记录 dataset version；
5. P0 安全集不得用于 Prompt 手工过拟合后再宣称独立结果。

## 主要问题类型

- exact_identifier
- api_path
- database_table
- error_code
- version
- current_version
- draft/superseded/delete_pending exclusion
- no_answer/refusal
- cross_project_identifier
- unauthorized_project
- prompt_injection
- request_scope_override
- issue_draft
- possible_duplicate
- confirmation
- idempotency
- unknown_result
- citation_coverage
