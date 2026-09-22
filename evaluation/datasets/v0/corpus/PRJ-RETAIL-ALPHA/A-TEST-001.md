# Alpha 导入与导出 UAT 验收规范

- 文档编号：`A-TEST-001`
- 项目：`PRJ-RETAIL-ALPHA`
- 文档类型：`approved_test_spec`
- 版本：`1.2`
- 生命周期：`PUBLISHED`

## 批量导入 UAT

订单批量导入至少覆盖以下验收场景：

1. 包含 **5,000** 条有效记录的文件可以成功导入。
2. 缺少必填值时，整个批次失败，并且 `t_order_detail` 写入数为 **0**。
3. 同一文件中出现重复 `(order_no, sku_code)` 时，整个批次失败。
4. 非 UTF-8 输入返回 `ERR-IMPORT-004`，并且写入数为 **0**。
5. 成功导入后，可以使用 `import_batch_id` 查询导入状态。

## Excel 日期导出 UAT

Excel 导出中的日期单元格必须是真实 spreadsheet date value，并显示为：

`yyyy-mm-dd`

日期不能表现为 serial-number text，也不能在 locale 变化时发生月、日对调。空日期保持为空。
