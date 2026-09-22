# Beta 物流导入 API 说明

- 文档编号：`B-API-001`
- 项目：`PRJ-LOGISTICS-BETA`
- 文档类型：`api_specification`
- 版本：`2.0`
- 生命周期：`PUBLISHED`

## 当前正式版本

Beta import API 当前正式版本为 **2.0**。

## POST /api/v1/import

v2.0 接受一个 JSON request，并通过该请求引用已经上传的 CSV object。

以下字段为必填：

- `object_uri`
- `carrier_code`
- `warehouse_code`
- `content_sha256`

## ERR-IMPORT-004

在 Beta 项目中，`ERR-IMPORT-004` 表示：

- 同一批次内 SSCC 重复；或
- SSCC 已经绑定到 active transport order。

发生冲突的行以 `duplicate_sscc` 被拒绝，已有 binding 不会被覆盖。

## 相邻错误码

- `ERR-IMPORT-003`：checksum mismatch。
- `ERR-IMPORT-005`：unknown carrier。
