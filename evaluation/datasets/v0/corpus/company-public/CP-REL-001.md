# 公司通用上线变更流程

- 文档编号：`CP-REL-001`
- 空间：`company-public`
- 文档类型：`release_runbook`
- 生命周期：`PUBLISHED`

## 流程说明

公司通用上线变更按照以下顺序执行：

1. 创建 change record，记录本次变更。
2. 完成 peer review。
3. 在 staging 环境完成验证。
4. 获取 release approval。
5. 在约定的 scheduled window 内执行部署。
6. 部署后运行 smoke checks。
7. 记录 rollback 结果以及 post-release 结果。

上述步骤共同构成通用上线变更流程。
