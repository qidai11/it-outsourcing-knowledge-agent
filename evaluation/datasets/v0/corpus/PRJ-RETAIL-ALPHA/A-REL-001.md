# Alpha v1.8.3 发布运行手册

- 文档编号：`A-REL-001`
- 项目：`PRJ-RETAIL-ALPHA`
- 文档类型：`release_runbook`
- 版本：`v1.8.3`
- 生命周期：`PUBLISHED`

## 上线前与上线执行顺序

v1.8.3 的 mandatory pre-release sequence 为：

1. 确认 import queue 为空。
2. 备份 order header / detail 数据。
3. 应用 migration package `R2026.08.17.01`，并校验其 checksum。
4. 完成部署后，运行 import smoke test 与 export smoke test。
5. 持续监控 **15 分钟**；如果 smoke gate 失败，则执行已记录的 rollback。

上述步骤按照该顺序执行。
