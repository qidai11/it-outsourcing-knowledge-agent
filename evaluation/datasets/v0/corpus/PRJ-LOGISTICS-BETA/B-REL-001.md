# Beta v2.4.0 发布前检查手册

- 文档编号：`B-REL-001`
- 项目：`PRJ-LOGISTICS-BETA`
- 文档类型：`release_runbook`
- 版本：`v2.4.0`
- 生命周期：`PUBLISHED`

## 发布前检查

v2.4.0 发布前需要完成以下检查：

1. 确认 settlement / import jobs 已经 quiescent。
2. 在 staging 中验证 schema migration。
3. 验证 partner gateway connectivity。
4. 执行一个 valid import smoke case。
5. 执行一个 duplicate-SSCC import smoke case。
6. 在 change window 前确认 rollback package checksum 以及 rollback owner。

以上项目构成 v2.4.0 的 pre-release checks。
