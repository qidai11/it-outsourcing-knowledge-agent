# Product Positioning

> 产品定位：**Internal-first, External-ready**

## 1. V1 用户

仅公司内部项目成员：

- 项目经理；
- 开发；
- 测试；
- 实施；
- 支持；
- 只读成员。

## 2. V1 价值

不是建设“通用企业 AI 平台”，而是解决外包项目交付中的四个具体问题：

1. 文档散落，查找慢；
2. 同名/旧版本资料容易混用；
3. 不同客户项目不能串数据；
4. 问题转工单缺少证据、人工确认和幂等。

## 3. V1 数据策略

```text
projects.delivery_mode = internal_only
documents.visibility = internal_only
```

## 4. External-ready 的含义

External-ready 不表示 V1 已面向客户开放。

它只表示核心数据模型不封死后续能力：

- Client / Project；
- 每项目独立知识空间；
- ProjectAccessScope；
- Document Visibility；
- AuthorityPolicy；
- Evidence Snapshot；
- Citation Guard；
- Usage Records；
- 项目归档。

## 5. 不以“平台化”作为 V1 成功标准

V1 成功应优先证明：

- 查询是否真的更快；
- 当前版本是否稳定命中；
- 引用是否可复核；
- 项目隔离是否可靠；
- Issue 草稿是否减少重复录入；
- 用户是否愿意持续维护文档；
- 单项目资源消耗是否可接受。
