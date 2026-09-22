# Beta 物流单元批量导入需求基线

- 文档编号：`B-REQ-001`
- 项目：`PRJ-LOGISTICS-BETA`
- 文档类型：`requirement_baseline`
- 版本：`1.6`
- 生命周期：`PUBLISHED`

## 版本关系

Beta 当前正式 requirement baseline 为 **1.6**，并替代 1.5 版本。

## REQ-3.2.1：运输订单物流单元批量导入

在 Beta 项目中，`REQ-3.2.1` 定义运输订单的 logistics-unit batch import。

每行必须包含：

- `transport_order_no`
- `sscc`
- `ship_to_code`
- `package_count`

`sscc` 是 **18 位** logistics-unit identifier，并且不能已经绑定到另一张 active transport order。

单个批次最多 **2,000** 行。

出现无效行时，系统返回 row-level results；彼此独立的有效行可以继续处理。
