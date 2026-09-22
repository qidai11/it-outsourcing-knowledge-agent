# Beta 重复 SSCC 导入 UAT 规范

- 文档编号：`B-TEST-001`
- 项目：`PRJ-LOGISTICS-BETA`
- 文档类型：`approved_test_spec`
- 版本：`1.0`
- 生命周期：`PUBLISHED`

## UAT 验收场景

Beta import UAT 需要覆盖两类 SSCC：

### 新 SSCC

一个新的 SSCC 应能够成功导入。

### 已绑定 SSCC

如果 SSCC 已经绑定到状态为 `OPEN` 或 `IN_PROGRESS` 的 transport order：

- 导入必须返回 `ERR-IMPORT-004`；
- 不能创建第二条 `t_order_detail` binding。

该场景用于验证重复 logistics-unit identifier 的处理。
