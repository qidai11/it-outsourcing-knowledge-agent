# Alpha 订单导入 API 说明

- 文档编号：`A-API-001`
- 项目：`PRJ-RETAIL-ALPHA`
- 文档类型：`api_specification`
- 版本：`1.4`
- 生命周期：`PUBLISHED`

## 接口

`POST /api/v1/import`

## 请求字段

v1.4 的请求中，以下字段为必填：

- `file_id`
- `store_code`
- `import_mode`

`import_mode` 只能取：

- `validate_only`
- `commit`

`client_request_id` 为可选字段。

## 导入错误码

### ERR-IMPORT-004

在 Alpha 项目中，`ERR-IMPORT-004` 表示上传 CSV 的编码不符合要求。

接口接受：

- UTF-8
- UTF-8 with BOM

该错误发生在业务校验之前；出现该错误时，不写入任何订单行。

### 相邻错误码

- `ERR-IMPORT-003`：缺少必填列。
- `ERR-IMPORT-005`：订单行重复。
