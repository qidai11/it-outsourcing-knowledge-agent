# 公司通用开发变更规范

- 文档编号：`CP-DEV-001`
- 空间：`company-public`
- 文档类型：`approved_design`
- 生命周期：`PUBLISHED`

## 适用范围

本规范用于需要变更数据库 Schema 或系统配置的开发工作。相关变更不能只留下最终修改结果，还需要保留能够供评审和回退使用的变更说明。

## 评审与变更记录

Schema 或配置变更需要完成 peer review。变更材料中应明确写出 migration / rollback note，使评审人员能够看到变更如何应用，以及发生问题时如何回退。

## 敏感信息处理

变更材料不得嵌入 secrets。配置项或变更说明可以描述需要调整的配置，但不能把实际 secret 写进变更产物。
